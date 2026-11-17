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

/// Inspect the start of an **unencrypted** HTTP/1 request seen on the wire
/// (request line, headers, beginning of the body). Detail is left intact —
/// this is the pre-existing plaintext-HTTP path used by `sniff.rs`.
pub fn inspect_http(payload: &[u8]) -> Vec<DataItem> {
    let text = String::from_utf8_lossy(&payload[..payload.len().min(8192)]);
    let Some((method, target, headers, body)) = parse_http1(&text) else { return vec![] };
    dedupe(scan_request(&method, &target, &headers, &body, false))
}

/// Inspect **decrypted** TLS plaintext captured in Deep mode (OpenSSL/NSS
/// uprobes). Routes HTTP/1 vs HTTP/2, runs the same matchers, and then MASKS
/// every item's `detail` — the report shows *kinds*, never raw bodies.
/// Stateless: a fresh HPACK decoder, fine for self-contained first requests.
///
/// Also returns the request's host/`:authority` (lowercased, port stripped).
/// The host NEVER enters a DataItem or the report; the capture layer uses it
/// only to confirm which already-tracked connection a write belongs to. None
/// when absent or unparseable.
pub fn inspect_payload_host(payload: &[u8]) -> (Vec<DataItem>, Option<String>) {
    if crate::http2::is_h2_preface(payload) {
        let mut h = crate::http2::Hpack::new();
        inspect_payload_h2_host(&mut h, payload)
    } else {
        let text = String::from_utf8_lossy(&payload[..payload.len().min(8192)]);
        match parse_http1(&text) {
            Some((m, t, hd, b)) => {
                let host = hd.iter().find(|(k, _)| k == "host").and_then(|(_, v)| normalize_host(v));
                (dedupe(scan_request(&m, &t, &hd, &b, true).into_iter().map(mask).collect()), host)
            }
            None => (vec![], None),
        }
    }
}

/// Stateful HTTP/2 variant for one connection: the caller owns the HPACK
/// decoder so indexed headers across writes resolve. Masked like above, and
/// returns the `:authority` for connection confirmation (never stored).
pub fn inspect_payload_h2_host(
    hpack: &mut crate::http2::Hpack,
    payload: &[u8],
) -> (Vec<DataItem>, Option<String>) {
    let (items, host) = inspect_h2(hpack, payload);
    (dedupe(items.into_iter().map(mask).collect()), host)
}

fn inspect_h2(hpack: &mut crate::http2::Hpack, payload: &[u8]) -> (Vec<DataItem>, Option<String>) {
    let mut out = Vec::new();
    let mut host = None;
    for req in crate::http2::parse_frames(payload, hpack) {
        if host.is_none() {
            host = normalize_host(&req.authority);
        }
        let body = String::from_utf8_lossy(&req.body).into_owned();
        out.extend(scan_request(&req.method, &req.path, &req.headers, &body, true));
    }
    (out, host)
}

/// Normalize a Host / `:authority` value to a bare lowercase hostname for
/// connection matching: drop any userinfo, strip a numeric port, unwrap IPv6
/// brackets. None when empty.
fn normalize_host(h: &str) -> Option<String> {
    let h = h.trim();
    let h = h.rsplit('@').next().unwrap_or(h); // strip userinfo if present
    let h = match h.rsplit_once(':') {
        Some((host, port)) if !port.is_empty() && port.bytes().all(|b| b.is_ascii_digit()) => host,
        _ => h,
    };
    let h = h.trim_matches(|c| c == '[' || c == ']');
    if h.is_empty() { None } else { Some(h.to_ascii_lowercase()) }
}

/// Parse an HTTP/1 request head into (method, target, lowercased headers, body).
fn parse_http1(text: &str) -> Option<(String, String, Vec<(String, String)>, String)> {
    let mut lines = text.split("\r\n");
    let req = lines.next()?;
    let mut parts = req.split(' ');
    let (method, target) = (parts.next()?, parts.next()?);
    if !["GET", "POST", "PUT", "HEAD", "PATCH", "OPTIONS", "DELETE"].contains(&method) { return None; }
    let mut headers = Vec::new();
    let mut body = String::new();
    let mut in_body = false;
    for l in lines {
        if in_body { body.push_str(l); body.push('\n'); continue; }
        if l.is_empty() { in_body = true; continue; }
        if let Some((k, v)) = l.split_once(':') {
            headers.push((k.trim().to_ascii_lowercase(), v.trim().to_string()));
        }
    }
    Some((method.to_string(), target.to_string(), headers, body))
}

/// Shared matcher core over a parsed request. Produces UNMASKED items;
/// `enc` only tweaks a label. Masking (for decrypted traffic) is applied by
/// the caller (`inspect_payload*`).
fn scan_request(_method: &str, target: &str, headers: &[(String, String)], body: &str, enc: bool) -> Vec<DataItem> {
    let page_label = if enc { "The page or file requested" } else { "The page or file requested (unencrypted)" };
    let mut out: Vec<DataItem> = vec![seen("browsing", page_label, Some(trim(target, 120)))];
    for (k, v) in headers {
        match k.as_str() {
            "user-agent" => out.push(seen("device", "Device and app details", Some(trim(v, 100)))),
            "cookie" => {
                push(&mut out, seen("cookies", "Cookies (can identify you)", None));
                if looks_auth_cookie(v) { push(&mut out, seen("auth", "A login token or session cookie", None)); }
            }
            "referer" => out.push(seen("browsing", "The page you came from", Some(trim(v, 100)))),
            "authorization" => push(&mut out, seen("auth", "A login token or session cookie", None)),
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
    out
}

/// A Cookie header carries a session/login token if any cookie *name* looks like one.
fn looks_auth_cookie(cookie: &str) -> bool {
    cookie.split(';').any(|kv| {
        let name = kv.split('=').next().unwrap_or("").trim().to_ascii_lowercase();
        matches!(name.as_str(),
            "session" | "sessionid" | "sid" | "token" | "auth" | "jwt" | "sess"
            | "access_token" | "auth_token" | "csrftoken" | "connect.sid")
            || name.ends_with("session") || name.ends_with("sessionid")
            || name.ends_with("token") || name.ends_with("_sid") || name.ends_with("auth")
    })
}

/// Redact a DataItem's detail for the decrypted path: keep the *kind*, drop or
/// mask the value. Guardrail: raw bodies never leave the agent.
fn mask(mut d: DataItem) -> DataItem {
    d.detail = match d.kind {
        "email" => d.detail.as_deref().map(mask_email),
        "phone" => d.detail.as_deref().map(|s| mask_tail(s, 2)),
        "advertising-id" | "identifier" => d.detail.as_deref().map(|s| mask_tail(s, 4)),
        // precise value is the sensitive part — keep only the kind
        "location" | "search" | "auth" | "password" | "cookies" => None,
        // the User-Agent is a strong fingerprint; keep the kind, drop the string
        "device" => None,
        // only the first path segment: deep paths carry ids, tokens and names
        "browsing" => d.detail.as_deref().map(coarse_path),
        _ => d.detail,
    };
    d
}

fn mask_email(s: &str) -> String {
    match s.split_once('@') {
        Some((local, domain)) => {
            let first = local.chars().next().unwrap_or('*');
            format!("{first}***@{domain}")
        }
        None => "***".to_string(),
    }
}

fn mask_tail(s: &str, keep: usize) -> String {
    let digits: Vec<char> = s.chars().filter(|c| !c.is_whitespace()).collect();
    if digits.len() <= keep { return "•".repeat(digits.len().max(1)); }
    let masked = "•".repeat(digits.len() - keep);
    let tail: String = digits[digits.len() - keep..].iter().collect();
    format!("{masked}{tail}")
}

/// Coarsen a request target: strip the query, then keep only the leading path
/// segment, so deep paths (ids, tokens, names) can't leak into the report.
fn coarse_path(s: &str) -> String {
    // Absolute URL (e.g. a Referer): drop scheme://host, keep just the path.
    let after_host = match s.find("://") {
        Some(i) => { let rest = &s[i + 3..]; rest.find('/').map(|j| &rest[j..]).unwrap_or("/") }
        None => s,
    };
    let path = after_host.split('?').next().unwrap_or(after_host);
    let body = path.trim_start_matches('/');
    match body.split('/').next() {
        Some(first) if !first.is_empty() => format!("/{}{}", trim(first, 40), if body.contains('/') { "/…" } else { "" }),
        _ => "/".to_string(),
    }
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

    #[test]
    fn decrypted_detail_is_masked() {
        let r = b"POST /login?q=hello HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer abc.def.ghi\r\n\r\nemail=jane%40example.com&phone=+14165550199&lat=43.6&lng=-79.3";
        let d = inspect_payload_host(r).0;
        let kinds: Vec<&str> = d.iter().map(|x| x.kind).collect();
        for k in ["email", "phone", "location", "auth", "search", "browsing"] {
            assert!(kinds.contains(&k), "missing {k}: {kinds:?}");
        }
        // email masked to first-char + domain
        assert_eq!(d.iter().find(|x| x.kind == "email").unwrap().detail.as_deref(), Some("j***@example.com"));
        // phone keeps only last 2 digits
        let phone = d.iter().find(|x| x.kind == "phone").unwrap().detail.as_deref().unwrap();
        assert!(phone.ends_with("99") && phone.contains('•'), "{phone}");
        // precise/sensitive kinds drop detail entirely
        assert!(d.iter().find(|x| x.kind == "location").unwrap().detail.is_none());
        assert!(d.iter().find(|x| x.kind == "search").unwrap().detail.is_none());
        assert!(d.iter().find(|x| x.kind == "auth").unwrap().detail.is_none());
        // browsing path keeps route but strips the query string
        assert_eq!(d.iter().find(|x| x.kind == "browsing").unwrap().detail.as_deref(), Some("/login"));
    }

    #[test]
    fn http2_request_detects_kinds() {
        // h2 preface + one HEADERS frame (RFC 7541 C.4.1 block = GET www.example.com /)
        let block = [0x82u8, 0x86, 0x84, 0x41, 0x8c, 0xf1, 0xe3, 0xc2, 0xe5, 0xf2, 0x3a, 0x6b, 0xa0, 0xab, 0x90, 0xf4, 0xff];
        let mut buf = Vec::new();
        buf.extend_from_slice(crate::http2::H2_PREFACE);
        let len = block.len();
        buf.extend_from_slice(&[(len >> 16) as u8, (len >> 8) as u8, len as u8, 0x01, 0x04, 0, 0, 0, 1]);
        buf.extend_from_slice(&block);
        let d = inspect_payload_host(&buf).0;
        assert!(d.iter().any(|x| x.kind == "browsing"), "{d:?}");
    }

    #[test]
    fn session_cookie_is_auth() {
        let r = b"GET / HTTP/1.1\r\nHost: x\r\nCookie: theme=dark; session=deadbeef\r\n\r\n";
        let kinds: Vec<&str> = inspect_payload_host(r).0.iter().map(|x| x.kind).collect();
        assert!(kinds.contains(&"auth"), "{kinds:?}");
        assert!(kinds.contains(&"cookies"));
        // a non-session cookie should NOT be flagged as auth
        let r2 = b"GET / HTTP/1.1\r\nHost: x\r\nCookie: theme=dark; lang=en\r\n\r\n";
        let kinds2: Vec<&str> = inspect_payload_host(r2).0.iter().map(|x| x.kind).collect();
        assert!(!kinds2.contains(&"auth"), "{kinds2:?}");
    }

    #[test]
    fn host_extracted_for_connection_matching() {
        // HTTP/1 Host: normalized to a bare lowercase hostname (port stripped).
        let (_items, h) = inspect_payload_host(b"GET /x HTTP/1.1\r\nHost: Example.COM:8443\r\n\r\n");
        assert_eq!(h.as_deref(), Some("example.com"));
        // HTTP/2 :authority (RFC 7541 C.4.1 block = www.example.com).
        let block = [0x82u8, 0x86, 0x84, 0x41, 0x8c, 0xf1, 0xe3, 0xc2, 0xe5, 0xf2, 0x3a, 0x6b, 0xa0, 0xab, 0x90, 0xf4, 0xff];
        let mut buf = Vec::new();
        buf.extend_from_slice(crate::http2::H2_PREFACE);
        let len = block.len();
        buf.extend_from_slice(&[(len >> 16) as u8, (len >> 8) as u8, len as u8, 0x01, 0x04, 0, 0, 0, 1]);
        buf.extend_from_slice(&block);
        assert_eq!(inspect_payload_host(&buf).1.as_deref(), Some("www.example.com"));
        // Non-HTTP plaintext (e.g. NSS writing a non-request buffer): no host, no kinds.
        let (items, host) = inspect_payload_host(b"\x16\x03\x01 some non-http bytes");
        assert!(items.is_empty() && host.is_none(), "{items:?} {host:?}");
    }
}
