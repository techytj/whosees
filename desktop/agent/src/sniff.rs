//! Deep mode (Linux, needs root / CAP_NET_RAW): read packet *headers* to learn
//!  - hostnames from DNS answers (ip -> name)
//!  - the website a TLS connection asks for (SNI in the ClientHello)
//!  - the Host of plain HTTP requests
//!  - byte counts for UDP flows (QUIC, calls), which the socket table doesn't report
//! Payload contents are never stored or reported.

use std::collections::HashMap;
use std::net::{IpAddr, Ipv4Addr, Ipv6Addr};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::Sender;
use std::sync::{Arc, Mutex};

pub type FlowKey = (IpAddr, u16, IpAddr, u16); // local, lport, remote, rport

pub enum Obs {
    Dns { name: String, ips: Vec<IpAddr> },
    Host { tcp: bool, flow: FlowKey, host: String },
    /// Data types read from unencrypted traffic on this flow
    Data { tcp: bool, flow: FlowKey, items: Vec<crate::datatypes::DataItem> },
}

#[derive(Default)]
pub struct UdpBytes { pub map: HashMap<FlowKey, (u64, u64)> }

const ETH_P_ALL: u16 = 0x0003;
const PACKET_OUTGOING: u8 = 4;

pub fn start(tx: Sender<Obs>, udp: Arc<Mutex<UdpBytes>>, running: Arc<AtomicBool>) -> std::io::Result<()> {
    let fd = unsafe { libc::socket(libc::AF_PACKET, libc::SOCK_DGRAM | libc::SOCK_CLOEXEC, (ETH_P_ALL).to_be() as i32) };
    if fd < 0 { return Err(std::io::Error::last_os_error()); }
    // wake up periodically so we notice shutdown
    let tv = libc::timeval { tv_sec: 0, tv_usec: 250_000 };
    unsafe {
        libc::setsockopt(fd, libc::SOL_SOCKET, libc::SO_RCVTIMEO, &tv as *const _ as *const _, std::mem::size_of::<libc::timeval>() as u32);
        let sz: i32 = 8 << 20;
        libc::setsockopt(fd, libc::SOL_SOCKET, libc::SO_RCVBUF, &sz as *const _ as *const _, 4);
    }
    let lo = unsafe { libc::if_nametoindex(b"lo\0".as_ptr() as *const _) } as i32;
    std::thread::Builder::new().name("sniff".into()).spawn(move || {
        let mut buf = vec![0u8; 4096];
        while running.load(Ordering::Relaxed) {
            let mut sll: libc::sockaddr_ll = unsafe { std::mem::zeroed() };
            let mut sl = std::mem::size_of::<libc::sockaddr_ll>() as u32;
            let n = unsafe { libc::recvfrom(fd, buf.as_mut_ptr() as *mut _, buf.len(), 0, &mut sll as *mut _ as *mut libc::sockaddr, &mut sl) };
            if n <= 0 { continue; }
            if sll.sll_ifindex == lo { continue; }
            let out = sll.sll_pkttype == PACKET_OUTGOING;
            handle(&buf[..n as usize], u16::from_be(sll.sll_protocol), out, &tx, &udp);
        }
        unsafe { libc::close(fd); }
    })?;
    Ok(())
}

fn handle(p: &[u8], ethertype: u16, out: bool, tx: &Sender<Obs>, udp: &Arc<Mutex<UdpBytes>>) {
    let Some((src, dst, proto, l4, total)) = (match ethertype { 0x0800 => ipv4(p), 0x86DD => ipv6(p), _ => None }) else { return };
    match proto {
        17 if l4.len() >= 8 => {
            let sp = u16::from_be_bytes([l4[0], l4[1]]);
            let dp = u16::from_be_bytes([l4[2], l4[3]]);
            let payload = &l4[8..];
            if out && dp == 53 {
                if let Some(q) = dns_question(payload) {
                    let _ = tx.send(Obs::Data { tcp: false, flow: (src, sp, dst, dp), items: vec![crate::datatypes::seen_dns(&q)] });
                }
            }
            if sp == 53 || sp == 5353 {
                if let Some((name, ips)) = dns_answer(payload) { let _ = tx.send(Obs::Dns { name, ips }); }
            }
            let key = if out { (src, sp, dst, dp) } else { (dst, dp, src, sp) };
            if let Ok(mut u) = udp.lock() {
                let e = u.map.entry(key).or_insert((0, 0));
                if out { e.0 += total as u64 } else { e.1 += total as u64 }
            }
            if out && dp == 443 {
                if let Some(h) = quic_hint(payload) { let _ = tx.send(Obs::Host { tcp: false, flow: key, host: h }); }
            }
        }
        6 if out && l4.len() >= 20 => {
            let sp = u16::from_be_bytes([l4[0], l4[1]]);
            let dp = u16::from_be_bytes([l4[2], l4[3]]);
            let off = ((l4[12] >> 4) as usize) * 4;
            if off < 20 || off > l4.len() { return; }
            let payload = &l4[off..];
            if payload.len() < 6 { return; }
            let host = if payload[0] == 0x16 && payload[1] == 0x03 { tls_sni(payload) }
                       else if payload.starts_with(b"GET ") || payload.starts_with(b"POST ") || payload.starts_with(b"HEAD ")
                            || payload.starts_with(b"PUT ") || payload.starts_with(b"OPTIONS ") { http_host(payload) }
                       else { None };
            if let Some(h) = host { let _ = tx.send(Obs::Host { tcp: true, flow: (src, sp, dst, dp), host: h }); }
            if payload[0] != 0x16 {
                let items = crate::datatypes::inspect_http(payload);
                if !items.is_empty() { let _ = tx.send(Obs::Data { tcp: true, flow: (src, sp, dst, dp), items }); }
            }
        }
        _ => {}
    }
}

fn ipv4(p: &[u8]) -> Option<(IpAddr, IpAddr, u8, &[u8], usize)> {
    if p.len() < 20 || p[0] >> 4 != 4 { return None; }
    let ihl = ((p[0] & 15) as usize) * 4;
    let total = u16::from_be_bytes([p[2], p[3]]) as usize;
    let frag = u16::from_be_bytes([p[6], p[7]]) & 0x1fff;
    if ihl < 20 || p.len() < ihl || frag != 0 { return None; }
    let src = IpAddr::V4(Ipv4Addr::new(p[12], p[13], p[14], p[15]));
    let dst = IpAddr::V4(Ipv4Addr::new(p[16], p[17], p[18], p[19]));
    Some((src, dst, p[9], &p[ihl..p.len().min(total.max(ihl))], total))
}

fn ipv6(p: &[u8]) -> Option<(IpAddr, IpAddr, u8, &[u8], usize)> {
    if p.len() < 40 || p[0] >> 4 != 6 { return None; }
    let plen = u16::from_be_bytes([p[4], p[5]]) as usize;
    let src = IpAddr::V6(Ipv6Addr::from(<[u8; 16]>::try_from(&p[8..24]).ok()?));
    let dst = IpAddr::V6(Ipv6Addr::from(<[u8; 16]>::try_from(&p[24..40]).ok()?));
    let mut next = p[6];
    let mut o = 40;
    for _ in 0..6 {
        match next {
            0 | 43 | 60 => { if o + 8 > p.len() { return None; } next = p[o]; o += (p[o + 1] as usize + 1) * 8; }
            44 => return None, // fragments: not worth reassembling
            _ => break,
        }
    }
    if o > p.len() { return None; }
    let unmap = |a: IpAddr| match a { IpAddr::V6(v) => v.to_ipv4_mapped().map(IpAddr::V4).unwrap_or(a), x => x };
    Some((unmap(src), unmap(dst), next, &p[o..], plen + 40))
}

// ---------- DNS ----------

fn dns_name(m: &[u8], mut o: usize) -> Option<(String, usize)> {
    let mut name = String::new();
    let mut end = None;
    for _ in 0..64 {
        let l = *m.get(o)? as usize;
        if l == 0 { o += 1; break; }
        if l & 0xC0 == 0xC0 {
            let ptr = ((l & 0x3F) << 8) | *m.get(o + 1)? as usize;
            if end.is_none() { end = Some(o + 2); }
            if ptr >= o { return None; } // only backwards pointers
            o = ptr;
            continue;
        }
        let label = m.get(o + 1..o + 1 + l)?;
        if !name.is_empty() { name.push('.'); }
        name.push_str(&String::from_utf8_lossy(label));
        o += 1 + l;
    }
    Some((name.to_ascii_lowercase(), end.unwrap_or(o)))
}

/// The name asked for in an outgoing DNS query.
pub fn dns_question(m: &[u8]) -> Option<String> {
    if m.len() < 12 || m[2] & 0x80 != 0 { return None; } // queries only
    if u16::from_be_bytes([m[4], m[5]]) != 1 { return None; }
    let (n, _) = dns_name(m, 12)?;
    (!n.is_empty() && n.contains('.')).then_some(n)
}

/// Parse a DNS response: (question name, all A/AAAA addresses in the answer).
pub fn dns_answer(m: &[u8]) -> Option<(String, Vec<IpAddr>)> {
    if m.len() < 12 || m[2] & 0x80 == 0 { return None; } // must be a response
    let qd = u16::from_be_bytes([m[4], m[5]]) as usize;
    let an = u16::from_be_bytes([m[6], m[7]]) as usize;
    if qd != 1 || an == 0 { return None; }
    let (qname, mut o) = dns_name(m, 12)?;
    o += 4;
    let mut ips = Vec::new();
    for _ in 0..an.min(64) {
        let (_, after) = dns_name(m, o)?;
        o = after;
        let h = m.get(o..o + 10)?;
        let typ = u16::from_be_bytes([h[0], h[1]]);
        let len = u16::from_be_bytes([h[8], h[9]]) as usize;
        let d = m.get(o + 10..o + 10 + len)?;
        match (typ, len) {
            (1, 4) => ips.push(IpAddr::V4(Ipv4Addr::new(d[0], d[1], d[2], d[3]))),
            (28, 16) => ips.push(IpAddr::V6(Ipv6Addr::from(<[u8; 16]>::try_from(d).ok()?))),
            _ => {}
        }
        o += 10 + len;
    }
    if ips.is_empty() || qname.is_empty() { None } else { Some((qname, ips)) }
}

// ---------- TLS ClientHello SNI ----------

pub fn tls_sni(r: &[u8]) -> Option<String> {
    // record header (5) + handshake header (4)
    if r.len() < 9 || r[0] != 0x16 || r[5] != 0x01 { return None; }
    let h = &r[9..];
    let mut o = 2 + 32; // version + random
    let sid = *h.get(o)? as usize; o += 1 + sid;
    let cs = u16::from_be_bytes([*h.get(o)?, *h.get(o + 1)?]) as usize; o += 2 + cs;
    let cm = *h.get(o)? as usize; o += 1 + cm;
    let ext_len = u16::from_be_bytes([*h.get(o)?, *h.get(o + 1)?]) as usize; o += 2;
    let end = (o + ext_len).min(h.len());
    while o + 4 <= end {
        let typ = u16::from_be_bytes([h[o], h[o + 1]]);
        let len = u16::from_be_bytes([h[o + 2], h[o + 3]]) as usize;
        let d = h.get(o + 4..o + 4 + len)?;
        if typ == 0 && d.len() >= 5 && d[2] == 0 {
            let nl = u16::from_be_bytes([d[3], d[4]]) as usize;
            let name = d.get(5..5 + nl)?;
            let s = String::from_utf8_lossy(name).to_ascii_lowercase();
            return valid_host(&s).then_some(s);
        }
        o += 4 + len;
    }
    None
}

fn http_host(p: &[u8]) -> Option<String> {
    let text = std::str::from_utf8(&p[..p.len().min(2048)]).ok()?;
    for line in text.split("\r\n").skip(1) {
        if line.is_empty() { break; }
        if let Some((k, v)) = line.split_once(':') {
            if k.eq_ignore_ascii_case("host") {
                let h = v.trim().split(':').next()?.to_ascii_lowercase();
                return valid_host(&h).then_some(h);
            }
        }
    }
    None
}

/// QUIC Initial packets are encrypted with keys derived from public values; decoding them
/// is future work. For now QUIC flows get their name from the DNS cache instead.
fn quic_hint(_p: &[u8]) -> Option<String> { None }

fn valid_host(s: &str) -> bool {
    !s.is_empty() && s.len() < 254 && s.contains('.')
        && s.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'.' || b == b'-' || b == b'_')
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_dns_response() {
        // response for example.com A 93.184.215.14, answer name is a compression pointer
        let mut m = vec![0x12, 0x34, 0x81, 0x80, 0, 1, 0, 1, 0, 0, 0, 0];
        m.extend_from_slice(b"\x07example\x03com\x00\x00\x01\x00\x01");
        m.extend_from_slice(&[0xC0, 0x0C, 0, 1, 0, 1, 0, 0, 0, 60, 0, 4, 93, 184, 215, 14]);
        let (n, ips) = dns_answer(&m).unwrap();
        assert_eq!(n, "example.com");
        assert_eq!(ips, vec![IpAddr::V4(Ipv4Addr::new(93, 184, 215, 14))]);
    }

    #[test]
    fn ignores_dns_queries() {
        let mut m = vec![0x12, 0x34, 0x01, 0x00, 0, 1, 0, 0, 0, 0, 0, 0];
        m.extend_from_slice(b"\x07example\x03com\x00\x00\x01\x00\x01");
        assert!(dns_answer(&m).is_none());
    }

    #[test]
    fn parses_sni_from_real_client_hello() {
        // Generated by Python's ssl module for server_hostname="tracker.example.org"
        let hex = include_str!("../tests/clienthello.hex");
        let bytes: Vec<u8> = (0..hex.trim().len()).step_by(2).map(|i| u8::from_str_radix(&hex.trim()[i..i + 2], 16).unwrap()).collect();
        assert_eq!(tls_sni(&bytes).as_deref(), Some("tracker.example.org"));
    }

    #[test]
    fn parses_http_host() {
        let req = b"GET / HTTP/1.1\r\nUser-Agent: x\r\nHost: Example.COM:8080\r\n\r\n";
        assert_eq!(http_host(req).as_deref(), Some("example.com"));
    }
}
