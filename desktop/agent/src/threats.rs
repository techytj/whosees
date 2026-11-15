//! Suspicious / malicious activity detection. Everything is local: offline threat lists plus
//! simple behaviour checks. Each finding becomes an alert with a suggested block rule.
//!
//! High:   destination on a threat list (malware / phishing / botnet control servers).
//! Medium: program running from a download/temp folder talking to the internet; regular
//!         "check-in" connections (beaconing); heavy one-way uploads to an unknown destination;
//!         ports typical of remote-control tools; random-looking (algorithm-generated) names.

use serde::Serialize;
use std::collections::{HashMap, HashSet};
use std::net::IpAddr;
use std::path::Path;
use std::time::Instant;

#[derive(Serialize, Clone)]
pub struct BlockHint { pub kind: &'static str, pub value: String, pub label: String }

#[derive(Serialize, Clone)]
pub struct Alert {
    pub severity: &'static str, // "high" | "medium"
    pub kind: &'static str,
    pub title: String,
    pub detail: String,
    pub block: BlockHint,
}

#[derive(Default)]
pub struct Threats {
    domains: HashSet<String>,
    ips: HashMap<IpAddr, String>,
    seen: HashSet<String>,                          // alert keys already raised this session
    opens: HashMap<(String, IpAddr), Vec<Instant>>, // (app, remote) -> connection start times
    pub loaded: (usize, usize),
}

const BAD_PORTS: &[(u16, &str)] = &[
    (4444, "a port used by hacking tools (Metasploit)"), (1337, "a port popular with hacking tools"),
    (31337, "a port popular with hacking tools"), (6667, "IRC, often used to control botnets"),
    (6697, "IRC, often used to control botnets"), (23, "Telnet, an unencrypted remote login"),
    (2323, "Telnet, often used by IoT malware"), (5555, "Android debugging, abused by malware"),
    (9001, "the Tor network"), (9030, "the Tor network"),
];

impl Threats {
    /// Load domains.txt and ips.txt ("ip<TAB>label<TAB>source") from `dir`. Missing files are fine.
    pub fn load(dir: &Path) -> Threats {
        let mut t = Threats::default();
        if let Ok(s) = std::fs::read_to_string(dir.join("domains.txt")) {
            t.domains = s.lines().filter(|l| !l.starts_with('#') && !l.is_empty()).map(|l| l.trim().to_lowercase()).collect();
        }
        if let Ok(s) = std::fs::read_to_string(dir.join("ips.txt")) {
            for l in s.lines().filter(|l| !l.starts_with('#')) {
                let mut p = l.split('\t');
                if let (Some(ip), Some(label)) = (p.next(), p.next()) {
                    if let Ok(ip) = ip.trim().parse() { t.ips.insert(ip, label.to_string()); }
                }
            }
        }
        t.loaded = (t.domains.len(), t.ips.len());
        t
    }

    fn bad_domain(&self, host: &str) -> Option<String> {
        let mut h = host.trim_end_matches('.');
        loop {
            if self.domains.contains(h) { return Some(h.to_string()); }
            match h.find('.') { Some(i) if h[i + 1..].contains('.') => h = &h[i + 1..], _ => return None }
        }
    }

    fn once(&mut self, key: String) -> bool { self.seen.insert(key) }

    /// A DNS answer arrived (before any connection): catches lookups of malicious sites.
    pub fn check_lookup(&mut self, host: &str) -> Option<Alert> {
        let bad = self.bad_domain(host)?;
        if !self.once(format!("lookup|{bad}")) { return None; }
        Some(Alert {
            severity: "high", kind: "malicious-lookup",
            title: format!("Something looked up a dangerous website: {host}"),
            detail: format!("{bad} is on a list of websites used for malware, phishing or scams. If you didn't just click a strange link, something on this device may be infected."),
            block: BlockHint { kind: "host", value: bad.clone(), label: bad },
        })
    }

    /// A new connection. `app_id`/`app_name`/`exe`: who; `cloud_like`: destination is a big known provider.
    #[allow(clippy::too_many_arguments)]
    pub fn check_conn(&mut self, app_id: &str, app_name: &str, exe: Option<&str>, remote: IpAddr, rport: u16,
                      host: Option<&str>, known_service: bool, place: &str) -> Vec<Alert> {
        let mut out = vec![];
        let ip_block = |label: String| BlockHint { kind: "ip", value: remote.to_string(), label };
        let app_block = |exe: Option<&str>| match exe {
            // Android: "apps" are user ids ("uid:10123")
            Some(e) if e.starts_with("uid:") => BlockHint { kind: "uid", value: e[4..].to_string(), label: app_name.to_string() },
            Some(e) if cfg!(windows) => BlockHint { kind: "app", value: e.to_string(), label: app_name.to_string() },
            _ => BlockHint { kind: "ip", value: remote.to_string(), label: remote.to_string() },
        };
        let dest = host.map(|h| h.to_string()).unwrap_or_else(|| remote.to_string());

        if let Some(label) = self.ips.get(&remote).cloned() {
            if self.once(format!("ip|{app_id}|{remote}")) {
                out.push(Alert { severity: "high", kind: "malicious-server",
                    title: format!("{app_name} is talking to a known malicious server"),
                    detail: format!("{dest} ({place}) is listed as: {label}. Legitimate apps almost never connect to these."),
                    block: ip_block(format!("{dest} (malicious server)")) });
            }
        }
        if let Some(h) = host { out.extend(self.check_host(app_id, app_name, h, known_service)); }
        if let Some(e) = exe {
            let l = e.to_lowercase().replace('\\', "/");
            let risky = ["/downloads/", "/tmp/", "/dev/shm/", "/appdata/local/temp/", "/windows/temp/", "/var/tmp/"]
                .iter().any(|d| l.contains(d));
            if risky && self.once(format!("loc|{app_id}")) {
                let folder = if l.contains("/downloads/") { "your Downloads folder" } else { "a temporary folder" };
                out.push(Alert { severity: "medium", kind: "risky-location",
                    title: format!("A program in {folder} is using the internet"),
                    detail: format!("{app_name} ({e}) is running from {folder} and connected to {dest} ({place}). Installers do this, but so does malware. If you don't recognise it, close it and delete the file it came from."),
                    block: app_block(exe) });
            }
        }
        if let Some((_, why)) = BAD_PORTS.iter().find(|(p, _)| *p == rport) {
            if self.once(format!("port|{app_id}|{rport}")) {
                out.push(Alert { severity: "medium", kind: "suspicious-port",
                    title: format!("{app_name} is using port {rport}"),
                    detail: format!("Port {rport} is {why}. Connected to {dest} ({place})."),
                    block: ip_block(dest.clone()) });
            }
        }
        // Beaconing: many new connections from one app to one unknown destination at a steady rhythm.
        if !known_service {
            let v = self.opens.entry((app_id.to_string(), remote)).or_default();
            v.push(Instant::now());
            let mut rhythm = None;
            if v.len() >= 6 {
                // judge the rhythm of the most recent check-ins only
                let gaps: Vec<f64> = v[v.len() - 6..].windows(2).map(|w| (w[1] - w[0]).as_secs_f64()).collect();
                let mean = gaps.iter().sum::<f64>() / gaps.len() as f64;
                let sd = (gaps.iter().map(|g| (g - mean).powi(2)).sum::<f64>() / gaps.len() as f64).sqrt();
                if mean >= 3.0 && sd / mean < 0.15 { rhythm = Some(mean); }
                if v.len() > 40 { v.drain(..20); }
            }
            if let Some(mean) = rhythm {
                if self.once(format!("beacon|{app_id}|{remote}")) {
                    out.push(Alert { severity: "medium", kind: "beaconing",
                        title: format!("{app_name} is checking in with a server every {:.0} seconds", mean),
                        detail: format!("{app_name} keeps opening new connections to {dest} ({place}) at a very regular rhythm. Updaters do this, but it's also how malware contacts its controller."),
                        block: app_block(exe) });
                }
            }
        }
        out
    }

    /// Checks that only need the website name (also used when the name arrives after the connection).
    pub fn check_host(&mut self, app_id: &str, app_name: &str, h: &str, known_service: bool) -> Vec<Alert> {
        let mut out = vec![];
        if let Some(bad) = self.bad_domain(h) {
            if self.once(format!("dom|{app_id}|{bad}")) {
                out.push(Alert { severity: "high", kind: "malicious-website",
                    title: format!("{app_name} connected to a dangerous website"),
                    detail: format!("{h} is on a list of websites used for malware, phishing or scams."),
                    block: BlockHint { kind: "host", value: bad.clone(), label: bad } });
            }
        }
        if !known_service && looks_generated(h) && self.once(format!("dga|{app_id}|{h}")) {
            out.push(Alert { severity: "medium", kind: "random-name",
                title: format!("{app_name} contacted a random-looking website"),
                detail: format!("{h} looks machine-generated. Some malware creates names like this to find its control server."),
                block: BlockHint { kind: "host", value: h.to_string(), label: h.to_string() } });
        }
        out
    }

    /// Called as byte counts grow: heavy one-way uploads to somewhere unknown.
    pub fn check_upload(&mut self, app_id: &str, app_name: &str, exe: Option<&str>, remote: IpAddr, host: Option<&str>,
                        sent: u64, recv: u64, known_service: bool, place: &str) -> Option<Alert> {
        if known_service || sent < 20 * 1024 * 1024 || sent < recv.saturating_mul(10) { return None; }
        if !self.once(format!("upload|{app_id}|{remote}")) { return None; }
        let dest = host.map(|h| h.to_string()).unwrap_or_else(|| remote.to_string());
        Some(Alert { severity: "medium", kind: "upload",
            title: format!("{app_name} is uploading a lot of data"),
            detail: format!("{app_name} has sent {} MB to {dest} ({place}) and received almost nothing back. Backups and uploads do this; so does data theft.", sent / (1024 * 1024)),
            block: match exe { Some(e) if e.starts_with("uid:") => BlockHint { kind: "uid", value: e[4..].to_string(), label: app_name.to_string() },
                               Some(e) if cfg!(windows) => BlockHint { kind: "app", value: e.to_string(), label: app_name.to_string() },
                               _ => BlockHint { kind: "ip", value: remote.to_string(), label: dest } } })
    }
}

/// Heuristic for algorithm-generated domain names: a long first label with few vowels and
/// high character variety, or lots of digits mixed in.
pub fn looks_generated(host: &str) -> bool {
    let parts: Vec<&str> = host.split('.').collect();
    if parts.len() < 2 { return false; }
    let label = parts[parts.len() - 2];
    if label.len() < 12 || label.contains('-') { return false; }
    let vowels = label.chars().filter(|c| "aeiou".contains(*c)).count() as f64 / label.len() as f64;
    let digits = label.chars().filter(|c| c.is_ascii_digit()).count();
    let mut freq = HashMap::new();
    for c in label.chars() { *freq.entry(c).or_insert(0f64) += 1.0; }
    let n = label.len() as f64;
    let entropy: f64 = freq.values().map(|f| { let p = f / n; -p * p.log2() }).sum();
    (vowels < 0.2 && entropy > 3.5) || (digits >= 4 && entropy > 3.7)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn generated_names() {
        assert!(looks_generated("xjw7qkv2rtzpl9.com"));
        assert!(looks_generated("qwrtzpkxvbnmlkjh.net"));
        assert!(!looks_generated("www.wikipedia.org"));
        assert!(!looks_generated("googleusercontent.com"));
        assert!(!looks_generated("api.anthropic.com"));
        assert!(!looks_generated("speedtest.tokyo2.linode.com"));
    }
    #[test]
    fn domain_suffix_and_once() {
        let mut t = Threats::default();
        t.domains.insert("evil.example".into());
        assert!(t.check_lookup("cdn.evil.example").is_some());
        assert!(t.check_lookup("cdn.evil.example").is_none(), "alerts only once");
        assert!(t.bad_domain("example").is_none());
        assert!(t.bad_domain("notevil.example").is_none());
    }
    #[test]
    fn beaconing_needs_a_steady_rhythm() {
        let mut t = Threats::default();
        let ip: IpAddr = "203.0.113.9".parse().unwrap();
        let k = ("app".to_string(), ip);
        let now = Instant::now();
        t.opens.insert(k.clone(), (0..5).map(|i| now - std::time::Duration::from_secs(50 - i * 10)).collect());
        let a = t.check_conn("app", "App", None, ip, 443, None, false, "Somewhere");
        assert!(a.iter().any(|x| x.kind == "beaconing"));
        let mut t = Threats::default();
        t.opens.insert(k, [50, 47, 30, 28, 3].iter().map(|s| now - std::time::Duration::from_secs(*s)).collect());
        assert!(!t.check_conn("app", "App", None, ip, 443, None, false, "Somewhere").iter().any(|x| x.kind == "beaconing"));
    }
}
