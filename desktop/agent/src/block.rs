//! Blocking (Linux, needs root): a private nftables table that rejects traffic to chosen
//! addresses. It only exists while a live view runs and is deleted on exit.
//!
//! Rules arrive from the UI as a full list (idempotent):
//!   {"cmd":"rules","rules":[{"kind":"host","value":"doubleclick.net"},{"kind":"company","value":"Criteo"},
//!                            {"kind":"ip","value":"1.2.3.4"},{"kind":"country","value":"RU"}]}
//! Hosts and companies are matched against DNS answers and new connections as they happen,
//! and their addresses are added to the firewall set on the fly.

use std::collections::{BTreeSet, HashMap};
use std::io::Write;
use std::net::IpAddr;
use std::process::{Command, Stdio};

const TABLE: &str = "whosees";

#[derive(Clone, Debug, serde::Deserialize)]
pub struct Rule { pub kind: String, pub value: String }

pub struct Blocker {
    pub available: bool,
    rules: Vec<Rule>,
    blocked: BTreeSet<IpAddr>,
    country_ranges: Vec<(IpAddr, IpAddr)>,
    pub error: Option<String>,
}

fn nft(script: &str) -> Result<(), String> {
    let mut c = Command::new("nft").arg("-f").arg("-").stdin(Stdio::piped()).stdout(Stdio::null()).stderr(Stdio::piped())
        .spawn().map_err(|e| e.to_string())?;
    c.stdin.take().unwrap().write_all(script.as_bytes()).map_err(|e| e.to_string())?;
    let o = c.wait_with_output().map_err(|e| e.to_string())?;
    if o.status.success() { Ok(()) } else { Err(String::from_utf8_lossy(&o.stderr).trim().to_string()) }
}

impl Blocker {
    /// Create the (empty) table. Removes any table left behind by a crashed earlier run.
    pub fn new(enabled: bool) -> Blocker {
        let mut b = Blocker { available: false, rules: vec![], blocked: BTreeSet::new(), country_ranges: vec![], error: None };
        if !enabled { return b; }
        let _ = nft(&format!("delete table inet {TABLE}\n"));
        let script = format!(
            "table inet {TABLE} {{\n\
             set b4 {{ type ipv4_addr; flags interval; counter; }}\n\
             set b6 {{ type ipv6_addr; flags interval; counter; }}\n\
             chain out {{ type filter hook output priority 0; policy accept;\n\
               ip daddr @b4 reject\n  ip6 daddr @b6 reject\n }}\n}}\n");
        match nft(&script) { Ok(()) => b.available = true, Err(e) => b.error = Some(e) }
        b
    }

    pub fn set_rules(&mut self, rules: Vec<Rule>, geo: Option<&crate::geo::Geo>) -> Result<(), String> {
        if !self.available { return Err(self.error.clone().unwrap_or_else(|| "blocking unavailable".into())); }
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

    /// Does a hostname / company match a rule?
    pub fn matches(&self, host: Option<&str>, company: Option<&str>) -> bool {
        self.rules.iter().any(|r| match r.kind.as_str() {
            "host" => host.is_some_and(|h| h == r.value || h.ends_with(&format!(".{}", r.value))),
            "company" => company.is_some_and(|c| c.eq_ignore_ascii_case(&r.value)),
            _ => false,
        })
    }

    /// Per-app blocking isn't available on Linux (yet).
    pub fn blocks_app(&self, _exe: Option<&str>) -> bool { false }

    pub fn is_blocked(&self, ip: &IpAddr) -> bool {
        self.blocked.contains(ip) || self.country_ranges.iter().any(|(a, b)| a <= ip && ip <= b)
    }

    /// Add addresses that turned out to belong to a blocked host/company. Returns true if new.
    pub fn add(&mut self, ips: &[IpAddr]) -> bool {
        let mut new = vec![];
        for ip in ips { if self.blocked.insert(*ip) { new.push(*ip); } }
        if new.is_empty() || !self.available { return false; }
        let (v4, v6): (Vec<_>, Vec<_>) = new.iter().partition(|i| i.is_ipv4());
        let mut s = String::new();
        if !v4.is_empty() { s += &format!("add element inet {TABLE} b4 {{ {} }}\n", join(&v4)); }
        if !v6.is_empty() { s += &format!("add element inet {TABLE} b6 {{ {} }}\n", join(&v6)); }
        let ok = nft(&s).is_ok();
        // The firewall stops new packets; also close connections that are already open.
        for ip in &new { kill_sockets(ip); }
        ok
    }

    fn sync(&mut self) -> Result<(), String> {
        let mut s = format!("flush set inet {TABLE} b4\nflush set inet {TABLE} b6\n");
        let (v4, v6): (Vec<IpAddr>, Vec<IpAddr>) = self.blocked.iter().partition(|i| i.is_ipv4());
        let mut e4: Vec<String> = v4.iter().map(|i| i.to_string()).collect();
        let mut e6: Vec<String> = v6.iter().map(|i| i.to_string()).collect();
        for (a, b) in &self.country_ranges {
            let e = if a == b { a.to_string() } else { format!("{a}-{b}") };
            if a.is_ipv4() { e4.push(e) } else { e6.push(e) }
        }
        // interval sets reject overlaps: let nft merge them
        if !e4.is_empty() { s += &format!("add element inet {TABLE} b4 {{ {} }}\n", e4.join(", ")); }
        if !e6.is_empty() { s += &format!("add element inet {TABLE} b6 {{ {} }}\n", e6.join(", ")); }
        nft(&s)
    }

    /// Packets rejected per address since the session started.
    pub fn counters(&self) -> HashMap<String, u64> {
        let mut out = HashMap::new();
        if !self.available || self.blocked.is_empty() { return out; }
        let Ok(o) = Command::new("nft").args(["-j", "list", "table", "inet", TABLE]).output() else { return out };
        let Ok(v) = serde_json::from_slice::<serde_json::Value>(&o.stdout) else { return out };
        for item in v["nftables"].as_array().into_iter().flatten() {
            for el in item["set"]["elem"].as_array().into_iter().flatten() {
                let e = &el["elem"];
                let (Some(val), Some(n)) = (e["val"].as_str(), e["counter"]["packets"].as_u64()) else { continue };
                if n > 0 { out.insert(val.to_string(), n); }
            }
        }
        out
    }

    pub fn shutdown(&mut self) {
        if self.available { let _ = nft(&format!("delete table inet {TABLE}\n")); self.available = false; }
    }
}

impl Drop for Blocker { fn drop(&mut self) { self.shutdown(); } }

/// Close open TCP connections to `ip` (kernel sock_destroy, like `ss -K dst IP`).
pub fn kill_sockets(ip: &IpAddr) {
    let _ = Command::new("ss").args(["-K", "dst", &ip.to_string()]).stdout(Stdio::null()).stderr(Stdio::null()).status();
}

fn join(v: &[&IpAddr]) -> String { v.iter().map(|i| i.to_string()).collect::<Vec<_>>().join(", ") }
