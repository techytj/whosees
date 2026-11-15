//! Windows blocking (Deep mode / admin): outbound Windows Firewall rules, all named "WhoSees …"
//! so they can always be found and removed. Rules exist only while a live view runs.
//!
//! Same rule list as Linux, plus {"kind":"app","value":"C:\\path\\to\\app.exe"} which blocks a
//! whole program (Windows Firewall supports per-program rules).

use std::collections::{BTreeSet, HashMap};
use std::net::IpAddr;
use std::os::windows::process::CommandExt;
use std::process::{Command, Stdio};

const PREFIX: &str = "WhoSees";
const CREATE_NO_WINDOW: u32 = 0x0800_0000;
const CHUNK: usize = 400; // addresses per firewall rule (keeps command lines short)

#[derive(Clone, Debug, serde::Deserialize)]
pub struct Rule { pub kind: String, pub value: String }

pub struct Blocker {
    pub available: bool,
    rules: Vec<Rule>,
    blocked: BTreeSet<IpAddr>,
    country_ranges: Vec<(IpAddr, IpAddr)>,
    names: Vec<String>, // firewall rules we created
    next: usize,
}

fn netsh(args: &[&str]) -> Result<(), String> {
    let o = Command::new("netsh").args(args).creation_flags(CREATE_NO_WINDOW)
        .stdout(Stdio::piped()).stderr(Stdio::piped()).output().map_err(|e| e.to_string())?;
    if o.status.success() { Ok(()) } else { Err(String::from_utf8_lossy(&o.stdout).trim().to_string()) }
}

fn remove_leftovers() {
    // Rules left behind by a crash: remove anything we own by its display name.
    let _ = Command::new("powershell.exe").creation_flags(CREATE_NO_WINDOW)
        .args(["-NoProfile", "-NonInteractive", "-Command",
               &format!("Get-NetFirewallRule -DisplayName '{PREFIX} *' -ErrorAction SilentlyContinue | Remove-NetFirewallRule")])
        .stdout(Stdio::null()).stderr(Stdio::null()).status();
}

impl Blocker {
    pub fn new(enabled: bool) -> Blocker {
        let b = Blocker { available: enabled, rules: vec![], blocked: BTreeSet::new(), country_ranges: vec![], names: vec![], next: 0 };
        if enabled { remove_leftovers(); }
        b
    }

    pub fn set_rules(&mut self, rules: Vec<Rule>, geo: Option<&crate::geo::Geo>) -> Result<(), String> {
        if !self.available { return Err("Blocking needs Deep mode (administrator permission)".into()); }
        self.rules = rules;
        self.blocked.clear();
        self.country_ranges.clear();
        for r in &self.rules {
            match r.kind.as_str() {
                "ip" => if let Ok(ip) = r.value.parse::<IpAddr>() { self.blocked.insert(ip); },
                "country" => if let Some(g) = geo { self.country_ranges.extend(g.country_ranges(&r.value)); },
                _ => {}
            }
        }
        self.sync()
    }

    pub fn has_rules(&self) -> bool { !self.rules.is_empty() }

    pub fn matches(&self, host: Option<&str>, company: Option<&str>) -> bool {
        self.rules.iter().any(|r| match r.kind.as_str() {
            "host" => host.is_some_and(|h| h == r.value || h.ends_with(&format!(".{}", r.value))),
            "company" => company.is_some_and(|c| c.eq_ignore_ascii_case(&r.value)),
            _ => false,
        })
    }

    pub fn blocks_app(&self, exe: Option<&str>) -> bool {
        exe.is_some_and(|e| self.rules.iter().any(|r| r.kind == "app" && r.value.eq_ignore_ascii_case(e)))
    }

    pub fn is_blocked(&self, ip: &IpAddr) -> bool {
        self.blocked.contains(ip) || self.country_ranges.iter().any(|(a, b)| a <= ip && ip <= b)
    }

    pub fn add(&mut self, ips: &[IpAddr]) -> bool {
        let new: Vec<IpAddr> = ips.iter().copied().filter(|ip| self.blocked.insert(*ip)).collect();
        if new.is_empty() || !self.available { return false; }
        let list: Vec<String> = new.iter().map(|i| i.to_string()).collect();
        let ok = self.add_rule(&list, None).is_ok();
        for ip in &new { kill_sockets(ip); }
        ok
    }

    fn add_rule(&mut self, remote: &[String], program: Option<&str>) -> Result<(), String> {
        self.next += 1;
        let name = format!("{PREFIX} block {}", self.next);
        let n = format!("name={name}");
        let mut args = vec!["advfirewall", "firewall", "add", "rule", n.as_str(), "dir=out", "action=block", "enable=yes", "profile=any"];
        let ip; let prog;
        if !remote.is_empty() { ip = format!("remoteip={}", remote.join(",")); args.push(&ip); }
        if let Some(p) = program { prog = format!("program={p}"); args.push(&prog); }
        netsh(&args)?;
        self.names.push(name);
        Ok(())
    }

    fn clear(&mut self) {
        for n in std::mem::take(&mut self.names) {
            let _ = netsh(&["advfirewall", "firewall", "delete", "rule", &format!("name={n}")]);
        }
    }

    fn sync(&mut self) -> Result<(), String> {
        self.clear();
        let mut entries: Vec<String> = self.blocked.iter().map(|i| i.to_string()).collect();
        for (a, b) in &self.country_ranges { entries.push(if a == b { a.to_string() } else { format!("{a}-{b}") }); }
        let mut err = None;
        for chunk in entries.chunks(CHUNK) {
            if let Err(e) = self.add_rule(chunk, None) { err = Some(e); }
        }
        let apps: Vec<String> = self.rules.iter().filter(|r| r.kind == "app").map(|r| r.value.clone()).collect();
        for app in apps {
            if let Err(e) = self.add_rule(&[], Some(&app)) { err = Some(e); }
            kill_app_sockets(&app);
        }
        for ip in self.blocked.clone() { kill_sockets(&ip); }
        match err { Some(e) => Err(e), None => Ok(()) }
    }

    /// Windows Firewall doesn't count per address; no counters here.
    pub fn counters(&self) -> HashMap<String, u64> { HashMap::new() }

    pub fn shutdown(&mut self) {
        if self.available { self.clear(); self.available = false; }
    }
}

impl Drop for Blocker { fn drop(&mut self) { self.shutdown(); } }

/// Close open IPv4 TCP connections to `ip` (SetTcpEntry with DELETE_TCB). IPv6 connections
/// are cut by the firewall on their next packet instead.
fn kill_sockets(ip: &IpAddr) {
    let IpAddr::V4(v4) = ip else { return };
    let Ok(mut d) = crate::diag::Diag::new() else { return };
    let Ok(socks) = d.dump() else { return };
    for s in socks.iter().filter(|s| s.remote == *ip) {
        if let IpAddr::V4(l) = s.local { delete_tcb(l, s.lport, *v4, s.rport); }
    }
}

fn kill_app_sockets(exe: &str) {
    let Ok(mut d) = crate::diag::Diag::new() else { return };
    let Ok(socks) = d.dump() else { return };
    let want = exe.to_lowercase();
    for s in socks {
        if s.state != 1 { continue; }
        if crate::procs::exe_of(s.pid).map(|e| e.to_lowercase()) != Some(want.clone()) { continue; }
        if let (IpAddr::V4(l), IpAddr::V4(r)) = (s.local, s.remote) { delete_tcb(l, s.lport, r, s.rport); }
    }
}

fn delete_tcb(local: std::net::Ipv4Addr, lport: u16, remote: std::net::Ipv4Addr, rport: u16) {
    use windows_sys::Win32::NetworkManagement::IpHelper::{SetTcpEntry, MIB_TCPROW_LH, MIB_TCPROW_LH_0};
    let row = MIB_TCPROW_LH {
        Anonymous: MIB_TCPROW_LH_0 { dwState: 12 }, // MIB_TCP_STATE_DELETE_TCB
        dwLocalAddr: u32::from_ne_bytes(local.octets()),
        dwLocalPort: (lport.to_be()) as u32,
        dwRemoteAddr: u32::from_ne_bytes(remote.octets()),
        dwRemotePort: (rport.to_be()) as u32,
    };
    unsafe { SetTcpEntry(&row); }
}
