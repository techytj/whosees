//! "What's being sent": the type of data leaving the device, with no lists to maintain.
//!
//! Seen   - read directly from unencrypted traffic (plain HTTP requests, DNS lookups).
//! Likely - what this kind of destination typically receives, from its category
//!          (the traffic itself is encrypted, so the contents can't be read).

use serde::Serialize;

#[derive(Serialize, Clone, Debug, PartialEq)]
pub struct DataItem {
    pub kind: &'static str,
    pub label: &'static str,
    pub basis: &'static str, // "seen" | "likely"
    #[serde(skip_serializing_if = "Option::is_none")]
    pub detail: Option<String>,
}

fn seen(kind: &'static str, label: &'static str, detail: Option<String>) -> DataItem { DataItem { kind, label, basis: "seen", detail } }
fn likely(kind: &'static str, label: &'static str) -> DataItem { DataItem { kind, label, basis: "likely", detail: None } }

/// Likely contents for an encrypted connection, from what the destination is.
pub fn likely_for(category: &str, service: &str, encrypted: bool) -> Vec<DataItem> {
    let mut v = match category {
        "ads" => vec![likely("advertising-id", "Advertising ID"), likely("device", "Device details"), likely("ads", "Which ads you see and tap")],
        "analytics" => vec![likely("usage", "How you use the app"), likely("device", "Device details")],
        "tracker" => vec![likely("activity", "Your activity in apps and websites"), likely("device", "Device details")],
        "social" => vec![likely("activity", "What you view, like and post"), likely("account", "Your account")],
        "messaging" => vec![likely("messages", "Messages and calls"), likely("account", "Your account")],
        "streaming" => vec![likely("media", "What you watch or listen to"), likely("account", "Your account")],
        "cdn" => vec![likely("files", "Requests for images, video and files")],
        "cloud" => vec![likely("app-data", "App or account data")],
        _ => vec![],
    };
    match service {
        "DNS" => v.push(likely("website-names", "Names of websites you visit")),
        "NTP" => v = vec![likely("time", "A clock check (no personal data)")],
        "SMTP" | "IMAP" | "POP3" => v.push(likely("email", "Email")),
        "STUN" | "Media" => v.push(likely("calls", "Voice or video call")),
        _ => {}
    }
    if !encrypted && service != "NTP" && !v.iter().any(|d| d.kind == "unencrypted") {
        v.push(likely("unencrypted", "Unencrypted: readable on your network"));
    }
    v
}

/// A plaintext DNS query going out: the website name is visible to anyone on the path.
pub fn seen_dns(name: &str) -> DataItem {
    seen("website-names", "Website name you looked up (unencrypted)", Some(name.to_string()))
}

/// Inspect the start of an unencrypted HTTP request (request line, headers, beginning of the body).
pub fn inspect_http(payload: &[u8]) -> Vec<DataItem> {
    let text = String::from_utf8_lossy(&payload[..payload.len().min(8192)]);
    let mut lines = text.split("\r\n");
    let Some(req) = lines.next() else { return vec![] };
    let mut parts = req.split(' ');
    let (Some(method), Some(target)) = (parts.next(), parts.next()) else { return vec![] };
    if !["GET", "POST", "PUT", "HEAD", "PATCH", "OPTIONS", "DELETE"].contains(&method) { return vec![] }
    let mut out: Vec<DataItem> = vec![seen("browsing", "The page or file requested (unencrypted)", Some(trim(target, 120)))];
    let mut body = String::new();
    let mut in_body = false;
    for l in lines {
        if in_body { body.push_str(l); body.push('\n'); continue; }
        if l.is_empty() { in_body = true; continue; }
        let Some((k, v)) = l.split_once(':') else { continue };
        match k.trim().to_ascii_lowercase().as_str() {
            "user-agent" => out.push(seen("device", "Device and app details", Some(trim(v.trim(), 100)))),
            "cookie" => out.push(seen("cookies", "Cookies (can identify you)", None)),
            "referer" => out.push(seen("browsing", "The page you came from", Some(trim(v.trim(), 100)))),
            _ => {}
        }
    }
    let query = target.split_once('?').map(|(_, q)| q).unwrap_or("");
    for (k, v) in params(query).into_iter().chain(params(&body.replace('\n', "&"))) {
        classify_param(&k, &v, &mut out);
    }
    // free-text checks across the whole request
    let all = format!("{target} {body}");
    if let Some(e) = find_email(&all) { push(&mut out, seen("email", "Your email address", Some(e))); }
    dedupe(out)
}

fn classify_param(k: &str, v: &str, out: &mut Vec<DataItem>) {
    let k = k.to_ascii_lowercase();
    let v = urldecode(v);
    if v.is_empty() { return; }
    let num = |s: &str| s.parse::<f64>().ok();
    match k.as_str() {
        "lat" | "latitude" | "lng" | "lon" | "long" | "longitude" | "ll" | "geo" | "location" | "loc" => {
            let coordish = num(&v).is_some_and(|x| x.abs() <= 180.0 && v.contains('.'))
                || v.split(',').filter_map(|p| num(p.trim())).count() == 2;
            if coordish { push(out, seen("location", "Your location", Some(v.clone()))); }
        }
        "adid" | "gaid" | "aaid" | "idfa" | "advertising_id" | "advertisingid" | "ad_id" | "ifa" | "maid" | "rdid" if looks_uuid(&v) =>
            push(out, seen("advertising-id", "Advertising ID", Some(v.clone()))),
        "email" | "e" | "mail" | "user_email" if v.contains('@') => push(out, seen("email", "Your email address", Some(v.clone()))),
        "phone" | "msisdn" | "tel" | "mobile" | "phone_number" if v.chars().filter(|c| c.is_ascii_digit()).count() >= 7 =>
            push(out, seen("phone", "Your phone number", Some(v.clone()))),
        "q" | "query" | "search" | "s" | "term" | "keyword" | "keywords" => push(out, seen("search", "What you searched for", Some(trim(&v, 80)))),
        "uid" | "user_id" | "userid" | "device_id" | "deviceid" | "android_id" | "cid" | "client_id" | "uuid" =>
            push(out, seen("identifier", "An ID that identifies you or your device", Some(trim(&v, 60)))),
        "password" | "pass" | "pwd" => push(out, seen("password", "A password (sent unencrypted!)", None)),
        _ => {}
    }
}

fn params(q: &str) -> Vec<(String, String)> {
    q.split(['&', ';']).filter_map(|kv| { let (k, v) = kv.split_once('=')?; Some((k.trim().to_string(), v.trim().to_string())) }).collect()
}
fn urldecode(s: &str) -> String {
    let b = s.as_bytes(); let mut out = Vec::with_capacity(b.len()); let mut i = 0;
    while i < b.len() {
        match b[i] {
            b'+' => { out.push(b' '); i += 1; }
            b'%' if i + 2 < b.len() => {
                if let Ok(x) = u8::from_str_radix(std::str::from_utf8(&b[i + 1..i + 3]).unwrap_or("zz"), 16) { out.push(x); i += 3; } else { out.push(b'%'); i += 1; }
            }
            c => { out.push(c); i += 1; }
        }
    }
    String::from_utf8_lossy(&out).into_owned()
}
fn looks_uuid(s: &str) -> bool {
    let h: String = s.chars().filter(|c| *c != '-').collect();
    h.len() == 32 && h.chars().all(|c| c.is_ascii_hexdigit()) && h != "00000000000000000000000000000000"
}
fn find_email(s: &str) -> Option<String> {
    let s = urldecode(s);
    for w in s.split(|c: char| c.is_whitespace() || "&=?,;\"'<>()[]{}".contains(c)) {
        if let Some((a, d)) = w.split_once('@') {
            if !a.is_empty() && d.contains('.') && !d.starts_with('.') && d.len() > 3 && a.len() < 64 && !a.contains('/') { return Some(w.to_string()); }
        }
    }
    None
}
fn trim(s: &str, n: usize) -> String { if s.chars().count() > n { format!("{}…", s.chars().take(n).collect::<String>()) } else { s.to_string() } }
fn push(out: &mut Vec<DataItem>, d: DataItem) { if !out.iter().any(|x| x.kind == d.kind && x.detail == d.detail) { out.push(d); } }
fn dedupe(v: Vec<DataItem>) -> Vec<DataItem> { let mut o = vec![]; for d in v { push(&mut o, d); } o }

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn finds_location_adid_email_search() {
        let r = b"GET /track?lat=43.6532&lng=-79.3832&gaid=38400000-8cf0-11bd-b23e-10b96e40000d&email=jane%40example.com&q=cheap+flights HTTP/1.1\r\nHost: ads.example\r\nUser-Agent: Mozilla/5.0 (Linux; Android 16)\r\nCookie: sid=1\r\n\r\n";
        let d = inspect_http(r);
        let kinds: Vec<&str> = d.iter().map(|x| x.kind).collect();
        for k in ["location", "advertising-id", "email", "search", "device", "cookies", "browsing"] { assert!(kinds.contains(&k), "missing {k}: {kinds:?}"); }
        assert!(d.iter().all(|x| x.basis == "seen"));
        assert_eq!(d.iter().find(|x| x.kind == "search").unwrap().detail.as_deref(), Some("cheap flights"));
    }
    #[test]
    fn post_body_and_phone() {
        let r = b"POST /api HTTP/1.1\r\nHost: x\r\nContent-Type: application/x-www-form-urlencoded\r\n\r\nphone=%2B1+416+555+0199&latitude=51.5&longitude=-0.12";
        let kinds: Vec<&str> = inspect_http(r).iter().map(|x| x.kind).collect();
        assert!(kinds.contains(&"phone") && kinds.contains(&"location"), "{kinds:?}");
    }
    #[test]
    fn no_false_positives() {
        let r = b"GET /images/logo.png?v=3 HTTP/1.1\r\nHost: cdn.example\r\n\r\n";
        let kinds: Vec<&str> = inspect_http(r).iter().map(|x| x.kind).collect();
        assert_eq!(kinds, vec!["browsing"]);
        assert!(inspect_http(b"\x16\x03\x01 not http").is_empty());
        assert!(inspect_http(b"GET /?lat=hello HTTP/1.1\r\n\r\n").iter().all(|d| d.kind != "location"));
    }
    #[test]
    fn likely_by_category() {
        let ads: Vec<&str> = likely_for("ads", "HTTPS", true).iter().map(|d| d.kind).collect();
        assert!(ads.contains(&"advertising-id"));
        assert!(likely_for("other", "HTTP", false).iter().any(|d| d.kind == "unencrypted"));
        assert_eq!(likely_for("other", "NTP", false).len(), 1);
    }
}
