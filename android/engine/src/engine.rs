//! The forwarding + analysis core. Platform-neutral: the tun fd, the "who owns this connection"
//! lookup and event delivery are injected, so it can be tested on Linux too.

use crate::classify::{self, Scope};
use crate::sock::Proto;
use crate::{datatypes, geo, hosts, sniff, threats};
use ipstack::{IpStack, IpStackConfig, IpStackStream};
use serde::Serialize;
use std::collections::{HashMap, HashSet};
use std::net::{IpAddr, SocketAddr};
use std::os::fd::RawFd;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use tokio::io::{AsyncReadExt, AsyncWriteExt};

#[derive(serde::Deserialize, Clone, Default)]
#[serde(default)]
pub struct Config {
    pub geo: Option<PathBuf>,
    pub categories: Option<PathBuf>,
    pub threats: Option<PathBuf>,
    /// The phone's real DNS servers (captured before the VPN starts) - lookups go where they always went.
    #[serde(deserialize_with = "lenient_ips")] pub upstream_dns: Vec<IpAddr>,
    /// The DNS address the VPN advertises to apps; queries to it are forwarded upstream.
    pub virtual_dns: Option<IpAddr>,
    #[serde(default)] pub lan: bool,
    /// Tests only: pin upstream sockets to this interface (Android excludes our app from the VPN instead).
    #[serde(default)] pub bind_device: Option<String>,
}

/// Who owns a connection (Android: ConnectivityManager.getConnectionOwnerUid + PackageManager).
#[derive(Clone, Serialize, Default)]
pub struct AppInfo { pub id: String, pub name: String, #[serde(skip_serializing_if = "Option::is_none")] pub icon: Option<String>, pub system: bool, pub uid: i64,
    /// Android: sensitive permissions the app holds (location, contacts, ...), so the UI can say what *could* be included
    #[serde(skip_serializing_if = "Vec::is_empty", default)] pub perms: Vec<String> }
pub type Owner = Arc<dyn Fn(Proto, SocketAddr, SocketAddr) -> AppInfo + Send + Sync>;

#[allow(dead_code)]
struct Flow {
    id: u64, proto: Proto, remote: IpAddr, rport: u16, host: Option<String>,
    app: AppInfo, known: bool, place: String, internet: bool,
    sent: AtomicU64, recv: AtomicU64, closed: AtomicBool, kill: AtomicBool,
    emitted: Mutex<(u64, u64, Option<Instant>)>,
}
impl Flow {
    fn new(id: u64, proto: Proto, remote: IpAddr, rport: u16) -> Flow {
        Flow { id, proto, remote, rport, host: None, app: AppInfo::default(), known: false, place: String::new(), internet: false,
               sent: AtomicU64::new(0), recv: AtomicU64::new(0), closed: AtomicBool::new(false), kill: AtomicBool::new(false),
               emitted: Mutex::new((0, 0, None)) }
    }
}

#[derive(Default)]
struct Rules {
    ips: HashSet<IpAddr>, hosts: Vec<String>, companies: Vec<String>, uids: HashSet<i64>,
    ranges: Vec<(IpAddr, IpAddr)>, any: bool,
}
impl Rules {
    fn blocks(&self, remote: IpAddr, host: Option<&str>, owner: Option<&str>, uid: i64) -> bool {
        self.any && (self.uids.contains(&uid) || self.ips.contains(&remote)
            || self.ranges.iter().any(|(a, b)| *a <= remote && remote <= *b)
            || host.is_some_and(|h| self.hosts.iter().any(|r| h == r || h.ends_with(&format!(".{r}"))))
            || owner.is_some_and(|o| self.companies.iter().any(|c| c.eq_ignore_ascii_case(o))))
    }
}

pub struct Shared {
    cfg: Config,
    geo: Option<geo::Geo>,
    hostdb: hosts::Hosts,
    threats: Mutex<threats::Threats>,
    dns: Mutex<HashMap<IpAddr, String>>,
    rules: Mutex<Rules>,
    flows: Mutex<HashMap<u64, Arc<Flow>>>,
    next_id: AtomicU64,
    events: Mutex<Vec<String>>,
    owner: Owner,
    totals: Mutex<(u64, u64)>, // bytes of finished flows
    running: AtomicBool,
}

pub struct Engine { pub shared: Arc<Shared>, rt: Option<tokio::runtime::Runtime>, tun_fd: RawFd }

fn now_ms() -> u64 { SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_millis() as u64).unwrap_or(0) }

impl Shared {
    fn emit(&self, v: serde_json::Value) {
        if let Ok(mut e) = self.events.lock() { if e.len() < 20_000 { e.push(v.to_string()); } }
    }

    fn describe(&self, remote: IpAddr, host: Option<&str>) -> (geo::GeoInfo, &'static str, Option<String>, Option<String>, bool, String) {
        let g = self.geo.as_ref().map(|g| g.lookup(remote)).unwrap_or_default();
        let hi = host.and_then(|h| self.hostdb.lookup(h));
        let sc = classify::scope(remote);
        let category: &'static str = match (sc, hi) {
            (Scope::Internet, Some(i)) => leak(&i.category),
            (Scope::Internet, None) => g.org.as_deref().map(classify::category_for_org).unwrap_or("other"),
            _ => "local",
        };
        let owner = hi.map(|i| i.owner.clone()).filter(|o| !o.is_empty()).or_else(|| g.org.as_deref().map(classify::owner_short));
        let site = hi.map(|i| i.service.clone());
        let known = hi.is_some() || matches!(category, "cloud" | "cdn" | "streaming" | "social" | "messaging");
        let place = match (&g.city, &g.country) {
            (Some(c), Some(cc)) => format!("{}, {cc}", c.split(" (").next().unwrap_or(c)),
            (None, Some(cc)) => cc.clone(), _ => "unknown location".into() };
        (g, category, owner, site, known, place)
    }

    /// A new connection: report it (with threat checks) and decide whether it may proceed.
    /// Would this connection be blocked, judging by what we know before contacting the server?
    fn pre_check(&self, proto: Proto, local: SocketAddr, remote: SocketAddr) -> (AppInfo, Option<String>, bool) {
        let app = (self.owner)(proto, local, remote);
        let host = self.dns.lock().ok().and_then(|d| d.get(&remote.ip()).cloned());
        let owner = self.describe(remote.ip(), host.as_deref()).2;
        let blocked = classify::scope(remote.ip()) == Scope::Internet
            && self.rules.lock().map(|r| r.blocks(remote.ip(), host.as_deref(), owner.as_deref(), app.uid)).unwrap_or(false);
        (app, host, blocked)
    }

    fn open(&self, proto: Proto, local: SocketAddr, remote: SocketAddr, host: Option<String>, app: Option<AppInfo>, seen: Vec<datatypes::DataItem>) -> (Arc<Flow>, bool) {
        let app = app.unwrap_or_else(|| (self.owner)(proto, local, remote));
        let host = host.or_else(|| self.dns.lock().ok()?.get(&remote.ip()).cloned());
        let (g, category, owner, site, known, place) = self.describe(remote.ip(), host.as_deref());
        let sc = classify::scope(remote.ip());
        let blocked = sc == Scope::Internet && self.rules.lock().map(|r| r.blocks(remote.ip(), host.as_deref(), owner.as_deref(), app.uid)).unwrap_or(false);
        let id = self.next_id.fetch_add(1, Ordering::Relaxed);
        let (svc, what, enc) = classify::service(proto, remote.port());
        let report = sc == Scope::Internet || (sc == Scope::Lan && self.cfg.lan);
        let mut f = Flow::new(id, proto, remote.ip(), remote.port());
        f.host = host.clone(); f.app = app.clone(); f.known = known; f.place = place.clone(); f.internet = sc == Scope::Internet;
        let flow = Arc::new(f);
        if report {
            let mut data = datatypes::likely_for(category, svc, enc);
            data.extend(seen);
            self.emit(serde_json::json!({
                "t": "open", "id": id, "ts": now_ms(), "existing": false,
                "proto": if proto == Proto::Tcp { "tcp" } else { "udp" }, "service": svc, "what": what, "encrypted": enc,
                "scope": sc, "local": local.ip().to_string(), "lport": local.port(), "remote": remote.ip().to_string(), "rport": remote.port(),
                "app": app, "owner": owner, "category": category, "host": host, "site": site, "geo": g, "blocked": blocked, "sent": 0, "recv": 0, "data": data }));
            if sc == Scope::Internet {
                let exe = Some(format!("uid:{}", app.uid));
                let alerts = self.threats.lock().map(|mut t| t.check_conn(&app.id, &app.name, exe.as_deref(), remote.ip(), remote.port(), host.as_deref(), known, &place)).unwrap_or_default();
                for a in alerts { self.emit(serde_json::json!({"t":"alert","conn":id,"host":host,"remote":remote.ip().to_string(),"alert":a})); }
            }
            if !blocked { self.flows.lock().unwrap().insert(id, flow.clone()); }
        }
        (flow, blocked)
    }

    #[allow(dead_code)]
    fn learned_host(&self, flow: &Flow, host: &str) {
        let hi = self.hostdb.lookup(host);
        self.emit(serde_json::json!({"t":"host","id":flow.id,"host":host,
            "category": hi.map(|i| i.category.as_str()), "owner": hi.map(|i| i.owner.as_str()), "site": hi.map(|i| i.service.as_str())}));
        if flow.internet {
            let alerts = self.threats.lock().map(|mut t| t.check_host(&flow.app.id, &flow.app.name, host, flow.known || hi.is_some())).unwrap_or_default();
            for a in alerts { self.emit(serde_json::json!({"t":"alert","conn":flow.id,"host":host,"remote":flow.remote.to_string(),"alert":a})); }
        }
    }

    fn dns_answer(&self, payload: &[u8]) {
        let Some((name, ips)) = sniff::dns_answer(payload) else { return };
        if let Ok(mut d) = self.dns.lock() { for ip in &ips { d.insert(*ip, name.clone()); } if d.len() > 50_000 { d.clear(); } }
        if let Some(a) = self.threats.lock().ok().and_then(|mut t| t.check_lookup(&name)) {
            self.emit(serde_json::json!({"t":"alert","conn":null,"host":name,"remote":ips.first().map(|i| i.to_string()),"alert":a}));
        }
    }

    pub fn set_rules(&self, rules: &serde_json::Value) {
        let mut r = Rules::default();
        for x in rules.as_array().into_iter().flatten() {
            let (k, v) = (x["kind"].as_str().unwrap_or(""), x["value"].as_str().unwrap_or("").to_string());
            match k {
                "ip" => if let Ok(ip) = v.parse() { r.ips.insert(ip); },
                "host" => r.hosts.push(v.to_lowercase()),
                "company" => r.companies.push(v),
                "uid" => if let Ok(u) = v.parse() { r.uids.insert(u); },
                "country" => if let Some(g) = &self.geo { r.ranges.extend(g.country_ranges(&v)); },
                _ => {}
            }
        }
        r.any = !(r.ips.is_empty() && r.hosts.is_empty() && r.companies.is_empty() && r.uids.is_empty() && r.ranges.is_empty());
        // cut open connections that are now blocked
        for f in self.flows.lock().unwrap().values() {
            let owner = self.describe(f.remote, f.host.as_deref()).2;
            if r.blocks(f.remote, f.host.as_deref(), owner.as_deref(), f.app.uid) { f.kill.store(true, Ordering::SeqCst); }
        }
        let n = rules.as_array().map(|a| a.len()).unwrap_or(0);
        *self.rules.lock().unwrap() = r;
        self.emit(serde_json::json!({"t":"rules","ok":true,"count":n,"error":null}));
    }

    /// Periodic: byte-count updates, closes, totals, upload checks.
    fn tick(&self, last_stats: &mut (Instant, u64, u64)) {
        let mut done = vec![];
        let flows: Vec<Arc<Flow>> = self.flows.lock().unwrap().values().cloned().collect();
        for f in &flows {
            let (s, r) = (f.sent.load(Ordering::Relaxed), f.recv.load(Ordering::Relaxed));
            let mut em = f.emitted.lock().unwrap();
            if (s, r) != (em.0, em.1) && em.2.is_none_or(|t| t.elapsed() >= Duration::from_millis(500)) {
                self.emit(serde_json::json!({"t":"update","id":f.id,"sent":s,"recv":r,"ds":s - em.0,"dr":r - em.1}));
                *em = (s, r, Some(Instant::now()));
                if f.internet {
                    let exe = Some(format!("uid:{}", f.app.uid));
                    let a = self.threats.lock().ok().and_then(|mut t| t.check_upload(&f.app.id, &f.app.name, exe.as_deref(), f.remote, f.host.as_deref(), s, r, f.known, &f.place));
                    if let Some(a) = a { self.emit(serde_json::json!({"t":"alert","conn":f.id,"host":f.host,"remote":f.remote.to_string(),"alert":a})); }
                }
            }
            if f.closed.load(Ordering::Relaxed) { done.push(f.id); }
        }
        if !done.is_empty() {
            let mut fl = self.flows.lock().unwrap();
            let mut tot = self.totals.lock().unwrap();
            for id in done {
                if let Some(f) = fl.remove(&id) {
                    let (s, r) = (f.sent.load(Ordering::Relaxed), f.recv.load(Ordering::Relaxed));
                    tot.0 += s; tot.1 += r;
                    self.emit(serde_json::json!({"t":"close","id":id,"sent":s,"recv":r}));
                }
            }
        }
        if last_stats.0.elapsed() >= Duration::from_secs(1) {
            let tot = *self.totals.lock().unwrap();
            let fl = self.flows.lock().unwrap();
            let (s, r) = fl.values().fold(tot, |(a, b), f| (a + f.sent.load(Ordering::Relaxed), b + f.recv.load(Ordering::Relaxed)));
            self.emit(serde_json::json!({"t":"stats","ts":now_ms(),"open":fl.len(),"sent":s,"recv":r,
                "rate_sent": s.saturating_sub(last_stats.1), "rate_recv": r.saturating_sub(last_stats.2)}));
            *last_stats = (Instant::now(), s, r);
        }
    }
}

/// Accept DNS server addresses even if some can't be parsed (e.g. "fe80::1%wlan0"): skip those,
/// never fail the whole config (that would silently break DNS and location lookups).
fn lenient_ips<'de, D: serde::Deserializer<'de>>(d: D) -> Result<Vec<IpAddr>, D::Error> {
    let v: Vec<String> = serde::Deserialize::deserialize(d).unwrap_or_default();
    Ok(v.iter().filter_map(|s| s.split('%').next()?.parse::<IpAddr>().ok())
        .filter(|ip| !matches!(ip, IpAddr::V6(a) if (a.segments()[0] & 0xffc0) == 0xfe80)) // link-local needs an interface
        .collect())
}

fn leak(s: &str) -> &'static str {
    // categories come from a small fixed set; intern them so events can borrow them
    match s { "ads" => "ads", "analytics" => "analytics", "tracker" => "tracker", "social" => "social", "messaging" => "messaging",
              "streaming" => "streaming", "cdn" => "cdn", "cloud" => "cloud", "local" => "local", _ => "other" }
}

// ---------- tun device as an async packet stream ----------
struct Tun { fd: tokio::io::unix::AsyncFd<RawFd> }
impl tokio::io::AsyncRead for Tun {
    fn poll_read(self: std::pin::Pin<&mut Self>, cx: &mut std::task::Context<'_>, buf: &mut tokio::io::ReadBuf<'_>) -> std::task::Poll<std::io::Result<()>> {
        loop {
            let mut g = match self.fd.poll_read_ready(cx) { std::task::Poll::Ready(r) => r?, std::task::Poll::Pending => return std::task::Poll::Pending };
            let un = buf.initialize_unfilled();
            match g.try_io(|f| { let n = unsafe { libc::read(*f.get_ref(), un.as_mut_ptr() as *mut _, un.len()) }; if n < 0 { Err(std::io::Error::last_os_error()) } else { Ok(n as usize) } }) {
                Ok(Ok(n)) => { buf.advance(n); return std::task::Poll::Ready(Ok(())); }
                Ok(Err(e)) => return std::task::Poll::Ready(Err(e)),
                Err(_would_block) => continue,
            }
        }
    }
}
impl tokio::io::AsyncWrite for Tun {
    fn poll_write(self: std::pin::Pin<&mut Self>, cx: &mut std::task::Context<'_>, data: &[u8]) -> std::task::Poll<std::io::Result<usize>> {
        loop {
            let mut g = match self.fd.poll_write_ready(cx) { std::task::Poll::Ready(r) => r?, std::task::Poll::Pending => return std::task::Poll::Pending };
            match g.try_io(|f| { let n = unsafe { libc::write(*f.get_ref(), data.as_ptr() as *const _, data.len()) }; if n < 0 { Err(std::io::Error::last_os_error()) } else { Ok(n as usize) } }) {
                Ok(r) => return std::task::Poll::Ready(r),
                Err(_would_block) => continue,
            }
        }
    }
    fn poll_flush(self: std::pin::Pin<&mut Self>, _: &mut std::task::Context<'_>) -> std::task::Poll<std::io::Result<()>> { std::task::Poll::Ready(Ok(())) }
    fn poll_shutdown(self: std::pin::Pin<&mut Self>, _: &mut std::task::Context<'_>) -> std::task::Poll<std::io::Result<()>> { std::task::Poll::Ready(Ok(())) }
}

impl Engine {
    pub fn start(tun_fd: RawFd, cfg: Config, owner: Owner) -> std::io::Result<Engine> {
        unsafe { let fl = libc::fcntl(tun_fd, libc::F_GETFL); libc::fcntl(tun_fd, libc::F_SETFL, fl | libc::O_NONBLOCK); }
        let geo = cfg.geo.as_ref().and_then(|p| geo::Geo::open(p).ok());
        let hostdb = cfg.categories.as_ref().and_then(|p| hosts::Hosts::load(p).ok()).unwrap_or_default();
        let thr = cfg.threats.as_ref().map(|d| threats::Threats::load(d)).unwrap_or_default();
        let loaded = thr.loaded;
        let shared = Arc::new(Shared {
            cfg: cfg.clone(), geo, hostdb, threats: Mutex::new(thr), dns: Default::default(), rules: Default::default(),
            flows: Default::default(), next_id: AtomicU64::new(1), events: Default::default(), owner,
            totals: Default::default(), running: AtomicBool::new(true),
        });
        shared.emit(serde_json::json!({"t":"hello","version":env!("CARGO_PKG_VERSION"),"os":"android","mode":"vpn","blocking":true,
            "geo": shared.geo.is_some(), "threats": [loaded.0, loaded.1], "ts": now_ms()}));
        let rt = tokio::runtime::Builder::new_multi_thread().worker_threads(4).enable_all().thread_name("wt-engine").build()?;
        let sh = shared.clone();
        rt.spawn(async move {
            #[allow(deprecated)]
            let tun = match tokio::io::unix::AsyncFd::new(tun_fd) { Ok(f) => Tun { fd: f }, Err(e) => { sh.emit(serde_json::json!({"t":"error","msg":e.to_string()})); return; } };
            let mut ic = IpStackConfig::default();
            ic.mtu_unchecked(1500);
            // Apps keep connections open quietly for a long time (streaming, push, chat). The stack's
            // 60 s default cut them off and apps reported "can't connect". Match a typical home router.
            ic.udp_timeout(Duration::from_secs(120));
            let mut tcp = ipstack::TcpConfig::default();
            tcp.timeout = Duration::from_secs(3600);
            ic.with_tcp_config(tcp);
            let mut stack = IpStack::new(ic, tun);
            let ticker = sh.clone();
            tokio::spawn(async move {
                let mut ls = (Instant::now(), 0, 0);
                while ticker.running.load(Ordering::Relaxed) { ticker.tick(&mut ls); tokio::time::sleep(Duration::from_millis(250)).await; }
            });
            while sh.running.load(Ordering::Relaxed) {
                match stack.accept().await {
                    Ok(IpStackStream::Tcp(tcp)) => { let s = sh.clone(); tokio::spawn(async move { tcp_flow(s, tcp).await }); }
                    Ok(IpStackStream::Udp(udp)) => { let s = sh.clone(); tokio::spawn(async move { udp_flow(s, udp).await }); }
                    Ok(_) => {}
                    Err(e) => { sh.emit(serde_json::json!({"t":"error","msg":format!("network stack stopped: {e}")})); break; }
                }
            }
        });
        Ok(Engine { shared, rt: Some(rt), tun_fd })
    }

    pub fn poll(&self) -> String {
        let v: Vec<String> = std::mem::take(&mut *self.shared.events.lock().unwrap());
        format!("[{}]", v.join(","))
    }

    pub fn command(&self, json: &str) {
        let Ok(v) = serde_json::from_str::<serde_json::Value>(json) else { return };
        if v["cmd"] == "rules" { self.shared.set_rules(&v["rules"]); }
    }

    pub fn stop(&mut self) {
        self.shared.running.store(false, Ordering::SeqCst);
        if let Some(rt) = self.rt.take() {
            rt.shutdown_timeout(Duration::from_millis(500));
            unsafe { libc::close(self.tun_fd); } // we own the VPN's fd; closing it ends the VPN tunnel
        }
    }
}

impl Drop for Engine { fn drop(&mut self) { self.stop(); } }

async fn tcp_flow(sh: Arc<Shared>, mut app: ipstack::IpStackTcpStream) {
    let (local, mut remote) = (app.local_addr(), app.peer_addr());
    // DNS over TCP (large answers) to the VPN's DNS address goes to the real DNS server.
    // Private DNS probes (port 853) to that address are refused at once so Android falls back immediately.
    if Some(remote.ip()) == sh.cfg.virtual_dns {
        match (remote.port(), sh.cfg.upstream_dns.first()) {
            (53, Some(u)) => remote = SocketAddr::new(*u, 53),
            _ => { close_fast(&mut app).await; return; }
        }
    }
    // Blocked by address, known name, company or app? Then never contact the server at all,
    // and close the app's side straight away so it fails fast instead of hanging.
    let (who, dns_host, pre_blocked) = sh.pre_check(Proto::Tcp, local, remote);
    if pre_blocked {
        let (flow, _) = sh.open(Proto::Tcp, local, remote, dns_host, Some(who), vec![]);
        close_fast(&mut app).await;
        flow.closed.store(true, Ordering::Relaxed);
        return;
    }
    // Connect upstream; meanwhile the first bytes from the app (TLS ClientHello / HTTP request) carry the website name.
    let dev = sh.cfg.bind_device.clone();
    let up = tokio::time::timeout(Duration::from_secs(15), async move {
        let s = if remote.is_ipv4() { tokio::net::TcpSocket::new_v4()? } else { tokio::net::TcpSocket::new_v6()? };
        if let Some(d) = dev { s.bind_device(Some(d.as_bytes()))?; }
        s.connect(remote).await
    });
    let mut first = vec![0u8; 4096];
    let (up, n) = tokio::join!(up, tokio::time::timeout(Duration::from_millis(400), app.read(&mut first)));
    let n = match n { Ok(Ok(n)) => n, _ => 0 };
    let host = if n > 5 && first[0] == 0x16 { sniff::tls_sni(&first[..n]) } else { None }.or(dns_host);
    let seen = if n > 0 && first[0] != 0x16 { datatypes::inspect_http(&first[..n]) } else { vec![] };
    let (flow, blocked) = sh.open(Proto::Tcp, local, remote, host, Some(who), seen);
    if blocked { let _ = app.shutdown().await; flow.closed.store(true, Ordering::Relaxed); return; } // name matched a block: nothing was sent
    let Ok(Ok(mut up)) = up else { let _ = app.shutdown().await; flow.closed.store(true, Ordering::Relaxed); return };
    if n > 0 { if up.write_all(&first[..n]).await.is_err() { flow.closed.store(true, Ordering::Relaxed); return; } flow.sent.fetch_add(n as u64, Ordering::Relaxed); }
    let (mut ar, mut aw) = tokio::io::split(app);
    let (mut ur, mut uw) = up.into_split();
    let f1 = flow.clone(); let f2 = flow.clone();
    let a2u = async move { let mut b = vec![0u8; 16384]; loop { if f1.kill.load(Ordering::Relaxed) { break; }
        match ar.read(&mut b).await { Ok(0) | Err(_) => break, Ok(n) => { if uw.write_all(&b[..n]).await.is_err() { break; } f1.sent.fetch_add(n as u64, Ordering::Relaxed); } } }
        let _ = uw.shutdown().await; };
    let u2a = async move { let mut b = vec![0u8; 16384]; loop { if f2.kill.load(Ordering::Relaxed) { break; }
        match ur.read(&mut b).await { Ok(0) | Err(_) => break, Ok(n) => { if aw.write_all(&b[..n]).await.is_err() { break; } f2.recv.fetch_add(n as u64, Ordering::Relaxed); } } }
        let _ = aw.shutdown().await; };
    let killer = { let f = flow.clone(); async move { while !f.kill.load(Ordering::Relaxed) { tokio::time::sleep(Duration::from_millis(200)).await; } } };
    tokio::select! { _ = async { tokio::join!(a2u, u2a) } => {}, _ = killer => {} }
    flow.closed.store(true, Ordering::Relaxed);
}

/// End an app's connection right away. ipstack can't refuse a connection, so let its local
/// handshake finish and then close: the app sees an immediate end instead of waiting for a timeout.
async fn close_fast(app: &mut ipstack::IpStackTcpStream) {
    let mut one = [0u8; 1];
    let _ = tokio::time::timeout(Duration::from_millis(100), app.read(&mut one)).await;
    let _ = app.shutdown().await;
}

async fn udp_flow(sh: Arc<Shared>, mut app: ipstack::IpStackUdpStream) {
    let (local, remote) = (app.local_addr(), app.peer_addr());
    // DNS sent to the VPN's own DNS address goes to the phone's real DNS server instead.
    let is_dns = remote.port() == 53;
    let target = match (sh.cfg.virtual_dns, sh.cfg.upstream_dns.first()) {
        (Some(v), Some(u)) if is_dns && remote.ip() == v => SocketAddr::new(*u, 53),
        _ => remote,
    };
    let (flow, blocked) = if is_dns && Some(remote.ip()) == sh.cfg.virtual_dns {
        (Arc::new(Flow::new(0, Proto::Udp, remote.ip(), 53)), false) // the phone's own lookups: analysed, not listed as a destination
    } else { sh.open(Proto::Udp, local, remote, None, None, vec![]) };
    if blocked { return; }
    let bind: SocketAddr = if target.is_ipv4() { "0.0.0.0:0".parse().unwrap() } else { "[::]:0".parse().unwrap() };
    let Ok(sock) = tokio::net::UdpSocket::bind(bind).await else { flow.closed.store(true, Ordering::Relaxed); return };
    if let Some(d) = &sh.cfg.bind_device { let _ = sock.bind_device(Some(d.as_bytes())); }
    if sock.connect(target).await.is_err() { flow.closed.store(true, Ordering::Relaxed); return; }
    let sock = Arc::new(sock);
    let mut b = vec![0u8; 65536]; let mut r = vec![0u8; 65536];
    loop {
        if flow.kill.load(Ordering::Relaxed) || !sh.running.load(Ordering::Relaxed) { break; }
        tokio::select! {
            n = app.read(&mut b) => match n { Ok(0) | Err(_) => break, Ok(n) => { if sock.send(&b[..n]).await.is_err() { break; } flow.sent.fetch_add(n as u64, Ordering::Relaxed); } },
            n = sock.recv(&mut r) => match n { Err(_) => break, Ok(n) => {
                if is_dns { sh.dns_answer(&r[..n]); }
                if app.write_all(&r[..n]).await.is_err() { break; }
                flow.recv.fetch_add(n as u64, Ordering::Relaxed); } },
            _ = tokio::time::sleep(Duration::from_secs(120)) => break,
        }
    }
    flow.closed.store(true, Ordering::Relaxed);
}
