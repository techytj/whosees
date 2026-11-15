//! Turn port numbers and network owners into human words.

use crate::diag::Proto;
use std::net::IpAddr;

#[derive(Clone, Copy, PartialEq, Eq, Debug, serde::Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Scope { Internet, Lan, Loopback }

pub fn scope(ip: IpAddr) -> Scope {
    match ip {
        IpAddr::V4(a) => {
            let o = a.octets();
            if a.is_loopback() { Scope::Loopback }
            else if a.is_private() || a.is_link_local() || a.is_multicast() || a.is_broadcast() || (o[0] == 100 && (o[1] & 0xC0) == 64) { Scope::Lan }
            else { Scope::Internet }
        }
        IpAddr::V6(a) => {
            let s = a.segments()[0];
            if a.is_loopback() { Scope::Loopback }
            else if (s & 0xfe00) == 0xfc00 || (s & 0xffc0) == 0xfe80 || a.is_multicast() { Scope::Lan }
            else { Scope::Internet }
        }
    }
}

/// (short protocol label, plain-English description, encrypted?)
pub fn service(proto: Proto, port: u16) -> (&'static str, &'static str, bool) {
    use Proto::*;
    match (proto, port) {
        (Tcp, 443) | (Tcp, 8443) => ("HTTPS", "Encrypted web traffic", true),
        (Udp, 443) => ("QUIC", "Encrypted web traffic (HTTP/3)", true),
        (Tcp, 80) | (Tcp, 8080) => ("HTTP", "Unencrypted web traffic", false),
        (_, 53) => ("DNS", "Looking up a website's address", false),
        (_, 853) => ("DoT", "Encrypted address lookup", true),
        (Udp, 123) => ("NTP", "Setting the clock", false),
        (Tcp, 22) => ("SSH", "Secure remote login", true),
        (Tcp, 25) | (Tcp, 465) | (Tcp, 587) => ("SMTP", "Sending email", true),
        (Tcp, 993) | (Tcp, 143) => ("IMAP", "Checking email", true),
        (Tcp, 995) | (Tcp, 110) => ("POP3", "Checking email", true),
        (Tcp, 5228..=5230) => ("Push", "Push notifications", true),
        (Tcp, 5222) | (Tcp, 5223) => ("XMPP", "Chat / push messages", true),
        (_, 3478) | (_, 3479) | (Udp, 19302..=19309) => ("STUN", "Voice / video call setup", false),
        (Udp, 3480..=3481) | (Udp, 50000..=50059) => ("Media", "Voice / video call", true),
        (Tcp, 1883) => ("MQTT", "Smart-device messages", false),
        (Tcp, 8883) => ("MQTTS", "Smart-device messages (encrypted)", true),
        (Udp, 51820) => ("WireGuard", "VPN tunnel", true),
        (_, 1194) => ("OpenVPN", "VPN tunnel", true),
        (Tcp, 3389) => ("RDP", "Remote desktop", true),
        (Tcp, 21) => ("FTP", "File transfer", false),
        (_, 6881..=6889) => ("BitTorrent", "File sharing", false),
        (_, 27015..=27050) => ("Steam", "Gaming", false),
        (Udp, 5353) => ("mDNS", "Finding devices on your network", false),
        (Udp, 1900) => ("SSDP", "Finding devices on your network", false),
        (Tcp, 445) | (Tcp, 139) => ("SMB", "Network drive", false),
        (Tcp, 631) => ("IPP", "Printing", false),
        (Tcp, 32400) => ("Plex", "Media streaming", false),
        (Tcp, 8096) | (Tcp, 8920) => ("Jellyfin", "Media streaming", false),
        (Tcp, _) => ("TCP", "Other data", false),
        (Udp, _) => ("UDP", "Other data", false),
    }
}

/// Category from the network owner's name. Hostname-based categories come with Deep mode.
/// A "category" block rule: one category, or "tracking" = every tracking, advertising and analytics company.
pub fn category_matches(rule: &str, category: &str) -> bool {
    rule == category || (rule == "tracking" && matches!(category, "tracker" | "ads" | "analytics"))
}

pub fn category_for_org(org: &str) -> &'static str {
    let o = org.to_lowercase();
    const RULES: &[(&str, &[&str])] = &[
        ("social", &["facebook", "meta platforms", "twitter", "x corp", "tiktok", "bytedance", "snap inc", "pinterest", "reddit", "linkedin"]),
        ("streaming", &["netflix", "spotify", "twitch", "valve", "disney", "hulu", "roku", "deezer", "tidal"]),
        ("messaging", &["whatsapp", "telegram", "discord", "signal messenger", "zoom video", "slack"]),
        ("ads", &["criteo", "taboola", "outbrain", "appnexus", "xandr", "pubmatic", "rubicon", "magnite", "the trade desk", "applovin", "ironsource", "inmobi"]),
        ("analytics", &["new relic", "datadog", "mixpanel", "amplitude", "hotjar", "functional software", "comscore", "nielsen", "appsflyer", "branch metrics"]),
        ("cdn", &["cloudflare", "akamai", "fastly", "edgecast", "limelight", "edgio", "stackpath", "bunny", "cdn77"]),
        ("cloud", &["amazon", "google", "microsoft", "oracle", "digitalocean", "hetzner", "ovh", "linode", "vultr", "alibaba", "tencent", "ibm", "github", "apple"]),
    ];
    for (cat, keys) in RULES {
        if keys.iter().any(|k| o.contains(k)) { return cat; }
    }
    "other"
}

/// Short, friendly owner name: "Google LLC" -> "Google", "Facebook, Inc." -> "Meta".
pub fn owner_short(org: &str) -> String {
    let o = org.to_lowercase();
    const KNOWN: &[(&str, &str)] = &[
        ("facebook", "Meta"), ("meta platforms", "Meta"), ("google", "Google"), ("amazon", "Amazon"),
        ("microsoft", "Microsoft"), ("apple", "Apple"), ("cloudflare", "Cloudflare"), ("akamai", "Akamai"),
        ("fastly", "Fastly"), ("netflix", "Netflix"), ("valve", "Valve (Steam)"), ("spotify", "Spotify"),
        ("twitter", "X (Twitter)"), ("x corp", "X (Twitter)"), ("bytedance", "TikTok"), ("tiktok", "TikTok"),
        ("hetzner", "Hetzner"), ("ovh", "OVH"), ("digitalocean", "DigitalOcean"), ("oracle", "Oracle"),
        ("github", "GitHub"), ("discord", "Discord"), ("telegram", "Telegram"), ("whatsapp", "WhatsApp"),
        ("zoom video", "Zoom"), ("anthropic", "Anthropic"), ("openai", "OpenAI"), ("linode", "Linode"),
        ("functional software", "Sentry"),
    ];
    for (k, v) in KNOWN { if o.contains(k) { return v.to_string(); } }
    let mut s = org.trim().to_string();
    for suf in [", Inc.", " Inc.", " Inc", " LLC", " Ltd.", " Ltd", " Limited", " GmbH", " B.V.", " S.A.", " Corporation", " Corp.", " Co.", " AG", " plc", " SAS"] {
        if let Some(x) = s.strip_suffix(suf) { s = x.trim_end_matches(',').trim().to_string(); }
    }
    s
}

#[cfg(test)]
mod tests {
    #[test]
    fn tracking_rule_covers_trackers_ads_and_analytics() {
        for c in ["tracker", "ads", "analytics"] { assert!(super::category_matches("tracking", c)); }
        for c in ["cdn", "cloud", "social", "other"] { assert!(!super::category_matches("tracking", c)); }
        assert!(super::category_matches("social", "social"));
    }
}
