//! whosees-agent: watches the machine's outgoing connections and prints one
//! JSON object per line on stdout. Exits when stdin closes, so it never outlives the UI.
//!
//!   whosees-agent --geo world.wtgeo [--interval 250] [--lan] [--once]
//!
//! Events: {"t":"hello"...} {"t":"open",...} {"t":"update",...} {"t":"close","id":N} {"t":"stats",...}

mod classify;
mod datatypes;
mod geo;
mod hosts;
mod http2;
mod sock;
mod threats;
#[cfg(target_os = "linux")] mod block;
#[cfg(target_os = "linux")] mod sslcap;
#[cfg(windows)] #[path = "win_block.rs"] mod block;
#[cfg(target_os = "linux")] mod diag;
#[cfg(target_os = "linux")] mod procs;
#[cfg(target_os = "linux")] mod sniff;
#[cfg(windows)] #[path = "win_diag.rs"] mod diag;
#[cfg(windows)] #[path = "win_procs.rs"] mod procs;
#[cfg(windows)] #[path = "win_dns.rs"] mod sniff;
#[cfg(windows)] #[path = "win_etw.rs"] mod etw;

use classify::Scope;
use diag::{Proto, Sock};
use serde::Serialize;
use std::collections::{HashMap, HashSet};
use std::io::{BufRead, Write};
use std::net::IpAddr;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

#[derive(Hash, PartialEq, Eq, Clone)]
struct Key { proto: Proto, local: IpAddr, lport: u16, remote: IpAddr, rport: u16 }

/// What threat checks need to know about a connection after it opened.
struct Meta { app_id: String, app_name: String, exe: Option<String>, known: bool, place: String, internet: bool, own: bool }

struct Conn { seen: Vec<datatypes::DataItem>, meta: Meta, host: Option<String>, id: u64, base_sent: u64, base_recv: u64, sent: u64, recv: u64, last_emit: Instant, emitted_sent: u64, emitted_recv: u64 }

#[derive(Serialize)]
struct OpenEv<'a> {
    t: &'static str,
    id: u64,
    ts: u64,
    existing: bool,
    proto: &'static str,
    service: &'static str,
    what: &'static str,
    encrypted: bool,
    scope: Scope,
    local: String,
    lport: u16,
    remote: String,
    rport: u16,
    app: &'a procs::AppInfo,
    #[serde(skip_serializing_if = "Option::is_none")]
    owner: Option<String>,
    category: &'a str,
    /// website name (Deep mode): from TLS SNI, HTTP Host or the DNS answer that led here
    #[serde(skip_serializing_if = "Option::is_none")]
    host: Option<String>,
    /// friendly name of the service behind the host ("Google Analytics", "YouTube")
    #[serde(skip_serializing_if = "Option::is_none")]
    site: Option<String>,
    geo: &'a geo::GeoInfo,
    #[serde(skip_serializing_if = "std::ops::Not::not")]
    blocked: bool,
    /// what kind of data: likely (from the destination) + seen (read from unencrypted traffic)
    data: Vec<datatypes::DataItem>,
    sent: u64,
    recv: u64,
}

pub static HOME: std::sync::OnceLock<String> = std::sync::OnceLock::new();
/// True when a "kind of company" rule covers every website name seen on this address (plus `extra`, the name this
/// connection asked for). An address that also serves an ordinary website is never blocked by such a rule.
fn only_matching_names(b: &block::Blocker, hostdb: &hosts::Hosts, seen: Option<&std::collections::HashSet<String>>, extra: Option<&str>) -> bool {
    let mut names = seen.into_iter().flatten().map(|s| s.as_str()).chain(extra).peekable();
    names.peek().is_some() && names.all(|n| b.matches_category(hostdb.lookup(n).map(|i| i.category.as_str())))
}

/// The WhoSees app itself (its program path, from the UI). Its own traffic is shown, never flagged as a threat.
pub static SELF_EXE: std::sync::OnceLock<String> = std::sync::OnceLock::new();
fn is_self(exe: Option<&str>) -> bool {
    let norm = |p: &str| p.replace('\\', "/").to_lowercase();
    matches!((exe, SELF_EXE.get()), (Some(e), Some(s)) if norm(e) == norm(s))
}
/// The desktop user's home (the agent may run as root in Deep mode).
pub fn home() -> String { HOME.get().cloned().unwrap_or_else(|| std::env::var("HOME").unwrap_or_default()) }

fn now_ms() -> u64 { SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_millis() as u64).unwrap_or(0) }

fn emit<T: Serialize>(out: &mut impl Write, v: &T) -> bool {
    serde_json::to_writer(&mut *out, v).is_ok() && out.write_all(b"\n").is_ok()
}

fn main() {
    let mut args = std::env::args().skip(1);
    let (mut geo_path, mut interval, mut lan, mut once, mut find) = (None::<PathBuf>, 250u64, false, false, None::<String>);
    let (mut deep, mut cats_path) = (false, None::<PathBuf>);
    let (mut connect, mut token) = (None::<String>, String::new());
    let mut threats_dir = None::<PathBuf>;
    let mut blocking = false; // the app passes --blocking; blocking also needs Deep mode (firewall rules need admin rights)
    // Payload reading: OFF by default, its own consent separate from Deep mode.
    // Reads the plaintext apps send over TLS (in memory only, kinds not bodies).
    let mut read_payloads = false;
    while let Some(a) = args.next() {
        match a.as_str() {
            "--geo" => geo_path = args.next().map(PathBuf::from),
            "--interval" => interval = args.next().and_then(|s| s.parse().ok()).unwrap_or(250).max(50),
            "--lan" => lan = true,
            "--once" => once = true,
            "--find-city" => find = args.next(),
            #[cfg(windows)]
            "--dump-dns" => { sniff::dump(); return; }
            "--deep" => deep = true,
            "--categories" => cats_path = args.next().map(PathBuf::from),
            "--home" => if let Some(h) = args.next() { let _ = HOME.set(h); },
            "--self-exe" => if let Some(e) = args.next() { let _ = SELF_EXE.set(e); },
            // Elevated on Windows (UAC): talk to the UI over a local socket instead of pipes.
            "--connect" => connect = args.next(),
            "--threats" => threats_dir = args.next().map(PathBuf::from),
            "--blocking" => blocking = true,
            "--read-payloads" => read_payloads = true,
            "--token" => token = args.next().unwrap_or_default(),
            "-h" | "--help" => { eprintln!("usage: whosees-agent --geo FILE [--interval MS] [--lan] [--once]"); return; }
            _ => { eprintln!("unknown argument {a}"); std::process::exit(2); }
        }
    }

    let geo = geo_path.as_ref().and_then(|p| match geo::Geo::open(p) {
        Ok(g) => Some(g),
        Err(e) => { eprintln!("geo database unavailable: {e}"); None }
    });
    let empty_geo = geo::GeoInfo::default();
    if let Some(q) = find {
        let hits = geo.as_ref().map(|g| g.find_cities(&q, 12)).unwrap_or_default();
        println!("{}", serde_json::to_string(&hits).unwrap());
        return;
    }

    let (input, output): (Box<dyn BufRead + Send>, Box<dyn Write>) = match &connect {
        Some(addr) => {
            let addr: std::net::SocketAddr = match addr.parse() { Ok(a) => a, Err(_) => std::process::exit(2) };
            if !addr.ip().is_loopback() { std::process::exit(2); } // only ever talk to this computer
            let s = match std::net::TcpStream::connect_timeout(&addr, Duration::from_secs(5)) { Ok(s) => s, Err(_) => std::process::exit(3) };
            let _ = s.set_nodelay(true);
            let mut w = s.try_clone().expect("socket");
            let _ = writeln!(w, "{token}");
            (Box::new(std::io::BufReader::new(s)), Box::new(w))
        }
        None => (Box::new(std::io::BufReader::new(std::io::stdin())), Box::new(std::io::stdout())),
    };

    let running = Arc::new(AtomicBool::new(true));
    let (cmd_tx, cmd_rx) = std::sync::mpsc::channel::<serde_json::Value>();
    if !once {
        let r = running.clone();
        std::thread::spawn(move || {
            // Commands from the UI, one JSON object per line. Stop on EOF or {"cmd":"stop"}.
            for line in input.lines() {
                let Ok(l) = line else { break };
                let Ok(v) = serde_json::from_str::<serde_json::Value>(&l) else { continue };
                if v["cmd"] == "stop" { break; }
                let _ = cmd_tx.send(v);
            }
            r.store(false, Ordering::SeqCst);
        });
    }

    let mut out = std::io::BufWriter::new(output);
    let mut diag = match diag::Diag::new() {
        Ok(d) => d,
        Err(e) => { let _ = emit(&mut out, &serde_json::json!({"t":"error","msg":format!("socket table unavailable: {e}")})); std::process::exit(1); }
    };
    let mut procs = procs::Procs::new();
    let hostdb = cats_path.as_ref().and_then(|p| hosts::Hosts::load(p).map_err(|e| eprintln!("categories unavailable: {e}")).ok()).unwrap_or_default();

    // Deep mode: packet headers -> hostnames + UDP byte counts.
    let (obs_tx, obs_rx) = std::sync::mpsc::channel::<sniff::Obs>();
    let udp = Arc::new(std::sync::Mutex::new(sniff::UdpBytes::default()));
    let mut deep_on = false;
    // Windows: hostnames come from the system DNS cache, which needs no admin rights.
    #[cfg(windows)]
    let etw_dns_tx = obs_tx.clone();
    let lookup_tx = obs_tx.clone(); // background lookups for newly blocked websites
    #[cfg(target_os = "linux")]
    let sslcap_tx = obs_tx.clone(); // decrypted-payload "data" events (if --read-payloads)
    if deep || cfg!(windows) {
        match sniff::start(obs_tx, udp.clone(), running.clone()) {
            Ok(()) => deep_on = cfg!(target_os = "linux"), // Windows DNS cache reader isn't Deep mode
            Err(e) => { emit(&mut out, &serde_json::json!({"t":"warn","msg":format!("Deep mode unavailable ({e}). Showing standard view.")})); }
        }
    }
    // Linux Deep mode, opt-in: read the plaintext apps send over TLS (eBPF
    // uprobes). Off unless --read-payloads; in memory only; kinds not bodies.
    #[cfg(target_os = "linux")]
    let payloads_on = if deep_on && read_payloads {
        match sslcap::start(sslcap_tx, running.clone()) {
            Ok(()) => true,
            Err(e) => {
                emit(&mut out, &serde_json::json!({"t":"warn","msg":format!("Payload reading unavailable ({e}).")}));
                false
            }
        }
    } else {
        let _ = sslcap_tx;
        false
    };
    #[cfg(not(target_os = "linux"))]
    let payloads_on = { let _ = read_payloads; false };

    // Windows Deep mode: kernel network tracing (ETW).
    #[cfg(windows)]
    let etw_flows: etw::Flows = Default::default();
    #[cfg(windows)]
    let _etw = if deep {
        match etw::start(etw_flows.clone(), etw_dns_tx) {
            Ok(t) => { deep_on = true; Some(t) }
            Err(e) => { emit(&mut out, &serde_json::json!({"t":"warn","msg":format!("Deep mode unavailable ({e}). Showing standard view.")})); None }
        }
    } else { None };

    let mut blocker = block::Blocker::new(deep_on && blocking);
    let mut threats = threats_dir.as_ref().map(|d| threats::Threats::load(d)).unwrap_or_default();
    let mut last_block_stats = Instant::now();
    let mut described: HashSet<IpAddr> = HashSet::new(); // stopped addresses already described to the UI (blockstats "where")
    let mut dns: HashMap<IpAddr, String> = HashMap::new();
    // every website name seen on each address: a "kind of company" block skips addresses shared with ordinary websites (CDNs, clouds)
    let mut ip_names: HashMap<IpAddr, std::collections::HashSet<String>> = HashMap::new();
    let mut early: Vec<(sniff::Obs, bool)> = Vec::new(); // seen while waiting for the next tick (lookups already acted on)
    let mut flow_host: HashMap<(Proto, sniff::FlowKey), String> = HashMap::new();
    let mut pending_data: HashMap<Key, Vec<datatypes::DataItem>> = HashMap::new(); // seen before the connection was reported

    emit(&mut out, &serde_json::json!({
        "t": "hello", "version": env!("CARGO_PKG_VERSION"), "os": std::env::consts::OS,
        "mode": if deep_on { "deep" } else { "standard" }, "blocking": blocker.available, "threats": [threats.loaded.0, threats.loaded.1], "geo": geo.is_some(), "read_payloads": payloads_on, "ts": now_ms()
    }));
    let _ = out.flush();

    let mut conns: HashMap<Key, Conn> = HashMap::new();
    let mut next_id = 1u64;
    let mut first = true;
    let mut last_stats = Instant::now();
    let (mut total_sent, mut total_recv, mut closed_sent, mut closed_recv) = (0u64, 0u64, 0u64, 0u64);

    while running.load(Ordering::SeqCst) {
        let tick = Instant::now();
        let mut socks = match diag.dump() { Ok(s) => s, Err(e) => { eprintln!("dump: {e}"); Vec::new() } };

        // Fold in what the packet reader learned since the last tick.
        let mut late_hosts: Vec<(Key, String)> = Vec::new();
        let mut late_data: Vec<(Key, Vec<datatypes::DataItem>)> = Vec::new();
        let mut dns_late: Vec<(IpAddr, String)> = Vec::new();
        let batch: Vec<(sniff::Obs, bool)> = early.drain(..).chain(std::iter::from_fn(|| obs_rx.try_recv().ok()).map(|o| (o, false))).collect();
        for (o, handled) in batch {
            match o {
                sniff::Obs::Dns { name, ips } => {
                    if let Some(a) = threats.check_lookup(&name) {
                        emit(&mut out, &serde_json::json!({"t":"alert","conn":null,"host":name,"remote":ips.first().map(|i| i.to_string()),"alert":a}));
                    }
                    if !handled {
                        if let Some(t) = block_on_lookup(&mut blocker, &hostdb, &mut ip_names, &name, &ips) {
                            emit(&mut out, &serde_json::json!({"t":"blockhost","host":name,"ips":t}));
                        }
                    }
                    for ip in &ips { dns.insert(*ip, name.clone()); }
                    dns_late.extend(ips.into_iter().map(|ip| (ip, name.clone())));
                }
                sniff::Obs::Data { tcp, flow, items } => {
                    let proto = if tcp { Proto::Tcp } else { Proto::Udp };
                    let k = Key { proto, local: flow.0, lport: flow.1, remote: flow.2, rport: flow.3 };
                    pending_data.entry(k.clone()).or_default().extend(items.iter().cloned());
                    late_data.push((k, items));
                }
                sniff::Obs::Host { tcp, flow, host } => {
                    let proto = if tcp { Proto::Tcp } else { Proto::Udp };
                    late_hosts.push((Key { proto, local: flow.0, lport: flow.1, remote: flow.2, rport: flow.3 }, host.clone()));
                    flow_host.insert((proto, flow), host);
                }
            }
        }
        // UI commands (block rules)
        while let Ok(c) = cmd_rx.try_recv() {
            if c["cmd"] == "rules" {
                let rules: Vec<block::Rule> = serde_json::from_value(c["rules"].clone()).unwrap_or_default();
                let n = rules.len();
                // Look up blocked websites ourselves (in the background, so a slow DNS server can't
                // freeze the live view). The answers arrive like any DNS answer and get blocked there,
                // before an app connects (otherwise its first request could slip through).
                let hosts: Vec<String> = rules.iter().filter(|r| r.kind == "host").flat_map(|r| [r.value.clone(), format!("www.{}", r.value)]).collect();
                let tx = lookup_tx.clone();
                std::thread::spawn(move || {
                    use std::net::ToSocketAddrs;
                    for h in hosts {
                        let ips: Vec<IpAddr> = (h.as_str(), 443).to_socket_addrs().map(|a| a.map(|x| x.ip()).collect()).unwrap_or_default();
                        if !ips.is_empty() { let _ = tx.send(sniff::Obs::Dns { name: h, ips }); }
                    }
                });
                let r = blocker.set_rules(rules, geo.as_ref());
                // re-check addresses we already know about
                if r.is_ok() && blocker.has_rules() {
                    let known: Vec<IpAddr> = dns.iter().filter(|(_, h)| {
                        let hi = hostdb.lookup(h);
                        blocker.matches_name(Some(h.as_str()), hi.map(|i| i.owner.as_str()))
                    }).map(|(ip, _)| *ip).collect();
                    blocker.add(&known);
                    let by_cat: Vec<IpAddr> = ip_names.iter().filter(|(_, names)| only_matching_names(&blocker, &hostdb, Some(names), None)).map(|(ip, _)| *ip).collect();
                    blocker.add_category(&by_cat);
                    let open: Vec<IpAddr> = conns.keys().filter(|k| {
                        let h = dns.get(&k.remote).map(|s| s.as_str());
                        let gi = geo.as_ref().map(|g| g.lookup(k.remote));
                        let hi = h.and_then(|h| hostdb.lookup(h));
                        let owner = hi.map(|i| i.owner.clone()).or_else(|| gi.and_then(|g| g.org).map(|o| classify::owner_short(&o)));
                        blocker.matches_name(h, owner.as_deref())
                    }).map(|k| k.remote).collect();
                    blocker.add(&open);
                    let open_cat: Vec<IpAddr> = conns.keys().filter(|k| only_matching_names(&blocker, &hostdb, ip_names.get(&k.remote), dns.get(&k.remote).map(|s| s.as_str()))).map(|k| k.remote).collect();
                    blocker.add_category(&open_cat);
                }
                emit(&mut out, &serde_json::json!({"t":"rules","ok":r.is_ok(),"count":n,"error":r.err()}));
                if let Some(w) = blocker.warning.take() { emit(&mut out, &serde_json::json!({"t":"warn","msg":w})); }
            }
        }
        if dns.len() > 50_000 { dns.clear(); }
        if flow_host.len() > 50_000 { flow_host.clear(); }
        if pending_data.len() > 5_000 { pending_data.clear(); }
        #[cfg(windows)]
        if deep_on { merge_etw(&mut socks, &etw_flows); }
        if deep_on {
            if let Ok(u) = udp.lock() {
                for s in socks.iter_mut().filter(|s| s.proto == Proto::Udp) {
                    if let Some(&(a, b)) = u.map.get(&(s.local, s.lport, s.remote, s.rport)) { s.bytes_sent = a; s.bytes_recv = b; }
                }
            }
        }

        // Local TCP ports that are listening: connections on them are incoming, not outgoing.
        let listening: HashSet<u16> = socks.iter()
            .filter(|s| s.proto == Proto::Tcp && s.state == diag::TCP_LISTEN).map(|s| s.lport).collect();

        let mut seen: HashSet<Key> = HashSet::with_capacity(socks.len());
        for s in socks.iter().filter(|s| wanted(s, &listening, lan)) {
            let key = Key { proto: s.proto, local: s.local, lport: s.lport, remote: s.remote, rport: s.rport };
            seen.insert(key.clone());
            match conns.get_mut(&key) {
                Some(c) => {
                    // Counters are lifetime totals from the kernel: only count what moved since we first saw it.
                    c.sent = c.sent.max(s.bytes_sent.saturating_sub(c.base_sent));
                    c.recv = c.recv.max(s.bytes_recv.saturating_sub(c.base_recv));
                    if (c.sent != c.emitted_sent || c.recv != c.emitted_recv) && c.last_emit.elapsed() >= Duration::from_millis(500) {
                        emit(&mut out, &serde_json::json!({"t":"update","id":c.id,"sent":c.sent,"recv":c.recv,
                            "ds": c.sent - c.emitted_sent, "dr": c.recv - c.emitted_recv}));
                        c.emitted_sent = c.sent; c.emitted_recv = c.recv; c.last_emit = Instant::now();
                        if c.meta.internet && !c.meta.own {
                            if let Some(a) = threats.check_upload(&c.meta.app_id, &c.meta.app_name, c.meta.exe.as_deref(), s.remote, c.host.as_deref(), c.sent, c.recv, c.meta.known, &c.meta.place) {
                                emit(&mut out, &serde_json::json!({"t":"alert","conn":c.id,"host":c.host,"remote":s.remote.to_string(),"alert":a}));
                            }
                        }
                    }
                }
                None => {
                    let id = next_id; next_id += 1;
                    let mut app = procs.app_for_sock(s);
                    let own = is_self(app.exe.as_deref());
                    if own { app.name = "WhoSees".into(); app.system = false; }
                    let g = geo.as_ref().map(|g| g.lookup(s.remote));
                    let g = g.as_ref().unwrap_or(&empty_geo);
                    let (svc, what, enc) = classify::service(s.proto, s.rport);
                    let sc = classify::scope(s.remote);
                    let host = flow_host.get(&(s.proto, (s.local, s.lport, s.remote, s.rport))).cloned()
                        .or_else(|| dns.get(&s.remote).cloned());
                    let hi = host.as_deref().and_then(|h| hostdb.lookup(h));
                    let category: &str = match (sc, hi) {
                        (Scope::Internet, Some(i)) => &i.category,
                        (Scope::Internet, None) => g.org.as_deref().map(classify::category_for_org).unwrap_or("other"),
                        _ => "local",
                    };
                    let owner = hi.map(|i| i.owner.clone()).filter(|o| !o.is_empty()).or_else(|| g.org.as_deref().map(classify::owner_short));
                    let site = hi.map(|i| i.service.clone());
                    let place = match (&g.city, &g.country) {
                        (Some(c), Some(cc)) => format!("{}, {cc}", c.split(" (").next().unwrap_or(c)),
                        (None, Some(cc)) => cc.clone(), _ => "unknown location".into() };
                    let known = hi.is_some() || matches!(category, "cloud" | "cdn" | "streaming" | "social" | "messaging");
                    let meta = Meta { app_id: app.id.clone(), app_name: app.name.clone(), exe: app.exe.clone(), known, place, internet: sc == Scope::Internet, own };
                    let app_blocked = blocker.blocks_app(app.exe.as_deref());
                    let by_name = blocker.matches_name(host.as_deref(), owner.as_deref());
                    let by_cat = !by_name && only_matching_names(&blocker, &hostdb, ip_names.get(&s.remote), host.as_deref());
                    let blocked = sc == Scope::Internet && (app_blocked || blocker.is_blocked(&s.remote) || by_name || by_cat);
                    if blocked && !app_blocked && !blocker.is_blocked(&s.remote) { if by_name { blocker.add(&[s.remote]); } else { blocker.add_category(&[s.remote]); } }
                    emit(&mut out, &OpenEv {
                        t: "open", id, ts: now_ms(), existing: first,
                        proto: if s.proto == Proto::Tcp { "tcp" } else { "udp" },
                        service: svc, what, encrypted: enc, scope: sc,
                        local: s.local.to_string(), lport: s.lport, remote: s.remote.to_string(), rport: s.rport,
                        app: &app, owner, category, host: host.clone(), site, geo: g, blocked,
                        data: { let mut d = datatypes::likely_for(category, svc, enc); d.extend(pending_data.remove(&key).unwrap_or_default()); d },
                        sent: 0, recv: 0,
                    });
                    // Already open when the live view started: its history isn't part of this session.
                    // Opened during the session: everything it has moved so far counts.
                    let (bs, br) = if first { (s.bytes_sent, s.bytes_recv) } else { (0, 0) };
                    let (cs, cr) = (s.bytes_sent - bs, s.bytes_recv - br);
                    if meta.internet && !meta.own {
                        for a in threats.check_conn(&meta.app_id, &meta.app_name, meta.exe.as_deref(), s.remote, s.rport, host.as_deref(), meta.known, &meta.place) {
                            emit(&mut out, &serde_json::json!({"t":"alert","conn":id,"host":host,"remote":s.remote.to_string(),"alert":a}));
                        }
                    }
                    conns.insert(key, Conn { seen: vec![], meta, host, id, base_sent: bs, base_recv: br, sent: cs, recv: cr, last_emit: Instant::now() - Duration::from_secs(1),
                                             emitted_sent: 0, emitted_recv: 0 });
                }
            }
        }
        // Data types read from unencrypted traffic after the connection was reported
        for (k, items) in late_data {
            if let Some(c) = conns.get_mut(&k) {
                let new: Vec<datatypes::DataItem> = items.into_iter().filter(|d| !c.seen.contains(d)).collect();
                if !new.is_empty() {
                    c.seen.extend(new.iter().cloned());
                    pending_data.remove(&k);
                    emit(&mut out, &serde_json::json!({"t":"data","id":c.id,"items":new}));
                }
            }
        }
        // Names learned from DNS after a connection was first reported (Windows polls its DNS cache).
        for (ip, h) in dns_late {
            for (k, c) in conns.iter() {
                if k.remote == ip && c.host.is_none() { late_hosts.push((k.clone(), h.clone())); }
            }
        }
        // Hostnames that arrived after the connection was first reported.
        for (k, h) in late_hosts {
            if let Some(c) = conns.get_mut(&k) {
                if c.host.as_deref() != Some(h.as_str()) {
                    let hi = hostdb.lookup(&h);
                    if c.meta.internet && !c.meta.own {
                        for a in threats.check_host(&c.meta.app_id, &c.meta.app_name, &h, c.meta.known || hi.is_some()) {
                            emit(&mut out, &serde_json::json!({"t":"alert","conn":c.id,"host":h,"remote":k.remote.to_string(),"alert":a}));
                        }
                    }
                    emit(&mut out, &serde_json::json!({"t":"host","id":c.id,"host":h,
                        "category": hi.map(|i| i.category.as_str()), "owner": hi.map(|i| i.owner.as_str()), "site": hi.map(|i| i.service.as_str()),
                        "data": hi.map(|i| datatypes::likely_for(&i.category, classify::service(k.proto, k.rport).0, classify::service(k.proto, k.rport).2))}));
                    c.host = Some(h);
                }
            }
        }
        conns.retain(|k, c| {
            if seen.contains(k) { return true; }
            closed_sent += c.sent; closed_recv += c.recv;
            emit(&mut out, &serde_json::json!({"t":"close","id":c.id,"sent":c.sent,"recv":c.recv}));
            false
        });

        if blocker.has_rules() && last_block_stats.elapsed() >= Duration::from_secs(2) {
            last_block_stats = Instant::now();
            let c = blocker.counters();
            // An address blocked from its first lookup never shows up as a connection: say where each stopped address
            // is (once), so the map can still show the attempts.
            let mut wh = serde_json::Map::new();
            for ip_s in c.keys() {
                let Ok(ip) = ip_s.parse::<IpAddr>() else { continue };
                if !described.insert(ip) { continue; }
                let g = geo.as_ref().map(|g| g.lookup(ip));
                let g = g.as_ref().unwrap_or(&empty_geo);
                let host = dns.get(&ip).cloned();
                let hi = host.as_deref().and_then(|h| hostdb.lookup(h));
                let sc = classify::scope(ip);
                let category: &str = match (sc, hi) {
                    (Scope::Internet, Some(i)) => &i.category,
                    (Scope::Internet, None) => g.org.as_deref().map(classify::category_for_org).unwrap_or("other"),
                    _ => "local",
                };
                let owner = hi.map(|i| i.owner.clone()).filter(|o| !o.is_empty()).or_else(|| g.org.as_deref().map(classify::owner_short));
                wh.insert(ip_s.clone(), serde_json::json!({"host": host, "owner": owner, "category": category,
                    "site": hi.map(|i| i.service.clone()), "scope": sc, "geo": g}));
            }
            if !c.is_empty() { emit(&mut out, &serde_json::json!({"t":"blockstats","ips":c,"where":wh})); }
        }
        if last_stats.elapsed() >= Duration::from_secs(1) || first {
            let (s, r) = conns.values().fold((closed_sent, closed_recv), |(a, b), c| (a + c.sent, b + c.recv));
            emit(&mut out, &serde_json::json!({"t":"stats","ts":now_ms(),"open":conns.len(),"sent":s,"recv":r,
                "rate_sent": s.saturating_sub(total_sent), "rate_recv": r.saturating_sub(total_recv)}));
            total_sent = s; total_recv = r; last_stats = Instant::now();
        }
        if out.flush().is_err() { break; } // UI went away
        first = false;
        if once { break; }
        // Wait for the next tick, but act on website lookups the moment they're seen: an app connects right after
        // its lookup, so a block must be in the firewall before the connection gets going.
        let deadline = Instant::now() + Duration::from_millis(interval).saturating_sub(tick.elapsed());
        loop {
            let left = deadline.saturating_duration_since(Instant::now());
            if left.is_zero() { break; }
            match obs_rx.recv_timeout(left) {
                Ok(sniff::Obs::Dns { name, ips }) => {
                    if let Some(t) = block_on_lookup(&mut blocker, &hostdb, &mut ip_names, &name, &ips) {
                        emit(&mut out, &serde_json::json!({"t":"blockhost","host":name,"ips":t}));
                        let _ = out.flush();
                    }
                    early.push((sniff::Obs::Dns { name, ips }, true));
                }
                Ok(o) => early.push((o, false)),
                Err(std::sync::mpsc::RecvTimeoutError::Timeout) => break,
                Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => { std::thread::sleep(left); break; }
            }
        }
    }
}

/// A website lookup was seen: block its addresses now if a rule covers it. Returns the addresses newly blocked.
fn block_on_lookup(blocker: &mut block::Blocker, hostdb: &hosts::Hosts, ip_names: &mut HashMap<IpAddr, std::collections::HashSet<String>>,
                   name: &str, ips: &[IpAddr]) -> Option<Vec<IpAddr>> {
    if ip_names.len() > 100_000 { ip_names.clear(); }
    for ip in ips { ip_names.entry(*ip).or_default().insert(name.to_lowercase()); }
    if !blocker.has_rules() { return None; }
    let hi = hostdb.lookup(name);
    if blocker.matches_name(Some(name), hi.map(|i| i.owner.as_str())) {
        return blocker.add(ips).then(|| ips.to_vec());
    }
    if blocker.matches_category(hi.map(|i| i.category.as_str())) {
        let t: Vec<IpAddr> = ips.iter().copied().filter(|ip| only_matching_names(blocker, hostdb, ip_names.get(ip), None)).collect();
        return (!t.is_empty() && blocker.add_category(&t)).then_some(t);
    }
    blocker.release(ips); // an ordinary website shares these addresses: a tracker rule mustn't take it down
    None
}

/// Windows Deep mode: add byte counts from ETW, plus flows the socket table never showed
/// (UDP/QUIC, and TCP connections that opened and closed between two polls).
#[cfg(windows)]
fn merge_etw(socks: &mut Vec<Sock>, flows: &etw::Flows) {
    let Ok(mut m) = flows.lock() else { return };
    m.retain(|_, f| f.last.elapsed() < Duration::from_secs(if f.closed { 3 } else { 30 }));
    let mut in_table = HashSet::new();
    for s in socks.iter_mut() {
        let k = etw::EtwKey { proto: s.proto, local: s.local, lport: s.lport, remote: s.remote, rport: s.rport };
        if let Some(f) = m.get(&k) { s.bytes_sent = f.sent; s.bytes_recv = f.recv; in_table.insert(k); }
    }
    for (k, f) in m.iter() {
        if in_table.contains(k) { continue; }
        // keep a TCP flow alive briefly after it closes so short connections are still reported
        let live = if k.proto == Proto::Tcp { !f.closed || f.last.elapsed() < Duration::from_secs(2) } else { f.last.elapsed() < Duration::from_secs(10) };
        if !live { continue; }
        socks.push(Sock { proto: k.proto, state: 1, local: k.local, lport: k.lport, remote: k.remote, rport: k.rport,
                          uid: 0, inode: 0, pid: f.pid, bytes_sent: f.sent, bytes_recv: f.recv });
    }
}

fn wanted(s: &Sock, listening: &HashSet<u16>, lan: bool) -> bool {
    if s.rport == 0 || s.remote.is_unspecified() { return false; }     // listening / unconnected
    if s.proto == Proto::Tcp {
        if s.state == diag::TCP_LISTEN { return false; }
        if listening.contains(&s.lport) { return false; }               // incoming connection to a server here
        // TIME_WAIT(6) / CLOSE(7): already finished, ignore so they don't flash up as new
        if s.state == sock::TCP_TIME_WAIT || s.state == sock::TCP_CLOSE { return false; }
    }
    match classify::scope(s.remote) {
        Scope::Internet => true,
        Scope::Lan => lan,
        Scope::Loopback => false,
    }
}
