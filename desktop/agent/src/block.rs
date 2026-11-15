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

#[derive(Clone, Copy, PartialEq)]
enum Fw { Nft, Ipt }

pub struct Blocker {
    pub available: bool,
    fw: Fw,
    ipt6: bool,                  // iptables backend: ip6tables available too
    /// Something on the block list can't be enforced here (told to the person once, as a warning).
    pub warning: Option<String>,
    rules: Vec<Rule>,
    blocked: BTreeSet<IpAddr>,
    cat_ips: BTreeSet<IpAddr>,  // blocked only because of a "kind of company" rule
    country_ranges: Vec<(IpAddr, IpAddr)>,
    carried: HashMap<String, u64>, // packets counted before the firewall's set was last rebuilt
    pub error: Option<String>,
}

fn nft(script: &str) -> Result<(), String> {
    let mut c = Command::new("nft").arg("-f").arg("-").stdin(Stdio::piped()).stdout(Stdio::null()).stderr(Stdio::piped())
        .spawn().map_err(|e| if e.kind() == std::io::ErrorKind::NotFound {
            "blocking needs nftables, which isn't installed. Install the nftables package (for example sudo apt install nftables or sudo pacman -S nftables), then start a new live view.".to_string()
        } else { e.to_string() })?;
    c.stdin.take().unwrap().write_all(script.as_bytes()).map_err(|e| e.to_string())?;
    let o = c.wait_with_output().map_err(|e| e.to_string())?;
    if o.status.success() { Ok(()) } else { Err(String::from_utf8_lossy(&o.stderr).trim().to_string()) }
}

// ---------- iptables: the fallback when nft isn't installed (Arch-based systems often have only iptables) ----------
const CHAIN: &str = "WHOSEES";
fn ipt(v6: bool, args: &[&str]) -> Result<(), String> {
    let o = Command::new(if v6 { "ip6tables" } else { "iptables" }).arg("-w").args(args).stdout(Stdio::null()).stderr(Stdio::piped())
        .output().map_err(|e| e.to_string())?;
    if o.status.success() { Ok(()) } else { Err(String::from_utf8_lossy(&o.stderr).trim().to_string()) }
}
fn ipt_teardown(v6: bool) {
    for _ in 0..8 { if ipt(v6, &["-D", "OUTPUT", "-j", CHAIN]).is_err() { break; } }
    let _ = ipt(v6, &["-F", CHAIN]);
    let _ = ipt(v6, &["-X", CHAIN]);
}
fn ipt_setup(v6: bool) -> Result<(), String> {
    ipt_teardown(v6);
    ipt(v6, &["-N", CHAIN])?;
    ipt(v6, &["-I", "OUTPUT", "1", "-j", CHAIN])
}
fn installed(cmd: &str) -> bool {
    Command::new(cmd).arg("--version").stdout(Stdio::null()).stderr(Stdio::null()).status().is_ok()
}

impl Blocker {
    /// Create the (empty) table. Removes any table left behind by a crashed earlier run.
    pub fn new(enabled: bool) -> Blocker {
        let mut b = Blocker { available: false, fw: Fw::Nft, ipt6: false, warning: None, rules: vec![], blocked: BTreeSet::new(), cat_ips: BTreeSet::new(), country_ranges: vec![], carried: HashMap::new(), error: None };
        if !enabled { return b; }
        let forced = std::env::var("WT_FIREWALL").ok(); // tests: try the fallback on a system that has both
        if forced.as_deref() == Some("iptables") || (!installed("nft") && installed("iptables")) {
            b.fw = Fw::Ipt;
            match ipt_setup(false) { Ok(()) => b.available = true, Err(e) => b.error = Some(e) }
            b.ipt6 = b.available && ipt_setup(true).is_ok();
            return b;
        }
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
        self.carry();
        self.rules = rules;
        self.blocked.clear();
        self.cat_ips.clear();
        self.country_ranges.clear();
        for r in &self.rules {
            match r.kind.as_str() {
                "ip" => if let Ok(ip) = r.value.parse::<IpAddr>() { self.blocked.insert(ip); },
                "country" if self.fw == Fw::Ipt => self.warning = Some("Blocking a whole country needs nftables, which isn't installed. Your other blocks work. Install the nftables package to block countries too.".into()),
                "country" => if let Some(g) = geo { self.country_ranges.extend(g.country_ranges(&r.value)); },
                _ => {}
            }
        }
        self.sync()
    }

    pub fn has_rules(&self) -> bool { !self.rules.is_empty() }

    /// Does a hostname / company match a rule?
    /// A website or company rule: blocks every address that name uses.
    pub fn matches_name(&self, host: Option<&str>, company: Option<&str>) -> bool {
        self.rules.iter().any(|r| match r.kind.as_str() {
            "host" => host.is_some_and(|h| h == r.value || h.ends_with(&format!(".{}", r.value))),
            "company" => company.is_some_and(|c| c.eq_ignore_ascii_case(&r.value)),
            _ => false,
        })
    }

    /// A "kind of company" rule (e.g. every tracker), judged by a website name's category, never by a guess
    /// from the address owner. The caller also checks the address isn't shared with ordinary websites.
    pub fn matches_category(&self, category: Option<&str>) -> bool {
        self.rules.iter().any(|r| match r.kind.as_str() {
            "category" => category.is_some_and(|c| crate::classify::category_matches(&r.value, c)),
            _ => false,
        })
    }

    /// Per-app blocking isn't available on Linux (yet).
    pub fn blocks_app(&self, _exe: Option<&str>) -> bool { false }

    /// Block addresses for a "kind of company" rule. Remembered separately: if an ordinary website later turns up on
    /// one of them (a shared CDN or cloud address), `release` unblocks it again.
    pub fn add_category(&mut self, ips: &[IpAddr]) -> bool {
        for ip in ips { if !self.blocked.contains(ip) { self.cat_ips.insert(*ip); } }
        self.add(ips)
    }
    pub fn release(&mut self, ips: &[IpAddr]) -> bool {
        let gone: Vec<IpAddr> = ips.iter().copied().filter(|ip| self.cat_ips.remove(ip)).collect();
        if gone.is_empty() { return false; }
        self.carry();
        for ip in &gone { self.blocked.remove(ip); }
        let _ = self.sync();
        true
    }

    pub fn is_blocked(&self, ip: &IpAddr) -> bool {
        self.blocked.contains(ip) || self.country_ranges.iter().any(|(a, b)| a <= ip && ip <= b)
    }

    /// Add addresses that turned out to belong to a blocked host/company. Returns true if new.
    pub fn add(&mut self, ips: &[IpAddr]) -> bool {
        let mut new = vec![];
        for ip in ips { if self.blocked.insert(*ip) { new.push(*ip); } }
        if new.is_empty() || !self.available { return false; }
        let ok = if self.fw == Fw::Ipt { new.iter().all(|ip| self.ipt_add(ip)) } else {
            let (v4, v6): (Vec<_>, Vec<_>) = new.iter().partition(|i| i.is_ipv4());
            let mut s = String::new();
            if !v4.is_empty() { s += &format!("add element inet {TABLE} b4 {{ {} }}\n", join(&v4)); }
            if !v6.is_empty() { s += &format!("add element inet {TABLE} b6 {{ {} }}\n", join(&v6)); }
            nft(&s).is_ok()
        };
        // The firewall stops new packets; also close connections that are already open.
        for ip in &new { kill_sockets(ip); }
        ok
    }

    fn ipt_add(&self, ip: &IpAddr) -> bool {
        if ip.is_ipv6() && !self.ipt6 { return false; }
        ipt(ip.is_ipv6(), &["-A", CHAIN, "-d", &ip.to_string(), "-j", "REJECT"]).is_ok()
    }

    fn sync(&mut self) -> Result<(), String> {
        if self.fw == Fw::Ipt {
            ipt(false, &["-F", CHAIN])?;
            if self.ipt6 { let _ = ipt(true, &["-F", CHAIN]); }
            for ip in &self.blocked { self.ipt_add(ip); }
            return Ok(());
        }
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

    /// Packets rejected per address since the session started. The firewall's own counters restart whenever its set
    /// is rebuilt (a block added or released), so what was counted before that is carried over.
    pub fn counters(&self) -> HashMap<String, u64> {
        let mut out = self.carried.clone();
        if !self.blocked.is_empty() { for (k, v) in self.read_counters() { *out.entry(k).or_default() += v; } }
        out
    }

    /// Keep the counts before the set is rebuilt, which zeroes them.
    fn carry(&mut self) {
        for (k, v) in self.read_counters() { *self.carried.entry(k).or_default() += v; }
    }

    fn read_counters(&self) -> HashMap<String, u64> {
        let mut out = HashMap::new();
        if !self.available { return out; }
        if self.fw == Fw::Ipt {
            for v6 in [false, true] {
                if v6 && !self.ipt6 { continue; }
                let Ok(o) = Command::new(if v6 { "ip6tables" } else { "iptables" }).args(["-w", "-L", CHAIN, "-v", "-n", "-x"]).output() else { continue };
                for l in String::from_utf8_lossy(&o.stdout).lines().skip(2) {
                    let f: Vec<&str> = l.split_whitespace().collect();
                    let Some(n) = f.first().and_then(|x| x.parse::<u64>().ok()) else { continue };
                    let dst = f.iter().rev().find_map(|t| t.split('/').next().and_then(|a| a.parse::<IpAddr>().ok()).filter(|a| !a.is_unspecified()));
                    if let (Some(d), true) = (dst, n > 0) { out.insert(d.to_string(), n); }
                }
            }
            return out;
        }
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
        if !self.available { return; }
        if self.fw == Fw::Ipt { ipt_teardown(false); if self.ipt6 { ipt_teardown(true); } }
        else { let _ = nft(&format!("delete table inet {TABLE}\n")); }
        self.available = false;
    }
}

impl Drop for Blocker { fn drop(&mut self) { self.shutdown(); } }

/// Close open TCP connections to `ip` (kernel sock_destroy, like `ss -K dst IP`).
pub fn kill_sockets(ip: &IpAddr) {
    let _ = Command::new("ss").args(["-K", "dst", &ip.to_string()]).stdout(Stdio::null()).stderr(Stdio::null()).status();
}

fn join(v: &[&IpAddr]) -> String { v.iter().map(|i| i.to_string()).collect::<Vec<_>>().join(", ") }
