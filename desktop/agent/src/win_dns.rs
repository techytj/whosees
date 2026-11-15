//! Windows: hostnames from the system DNS client cache (what `ipconfig /displaydns` shows).
//! No admin needed. Same interface as the Linux packet reader, so the main loop is shared.

use std::collections::HashMap;
use std::net::{IpAddr, Ipv4Addr, Ipv6Addr};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::Sender;
use std::sync::{Arc, Mutex};
use windows_sys::Win32::NetworkManagement::Dns::{DnsFree, DnsFreeFlat, DnsFreeRecordList, DnsQuery_W, DNS_RECORDA, DNS_TYPE_A, DNS_TYPE_AAAA};

pub type FlowKey = (IpAddr, u16, IpAddr, u16);

#[allow(dead_code)]
pub enum Obs {
    Dns { name: String, ips: Vec<IpAddr> },
    Host { tcp: bool, flow: FlowKey, host: String },
    Data { tcp: bool, flow: FlowKey, items: Vec<crate::datatypes::DataItem> },
}

#[derive(Default)]
pub struct UdpBytes { pub map: HashMap<FlowKey, (u64, u64)> }

#[repr(C)]
struct DnsCacheEntry { next: *mut DnsCacheEntry, name: *const u16, typ: u16, len: u16, flags: u32 }

#[link(name = "dnsapi")]
extern "system" {
    // Undocumented but long-stable export used by ipconfig /displaydns.
    fn DnsGetCacheDataTable(entry: *mut *mut DnsCacheEntry) -> i32;
}

pub fn start(tx: Sender<Obs>, _udp: Arc<Mutex<UdpBytes>>, running: Arc<AtomicBool>) -> std::io::Result<()> {
    std::thread::Builder::new().name("dnscache".into()).spawn(move || {
        let mut seen: HashMap<String, Vec<IpAddr>> = HashMap::new();
        let mut done = std::collections::HashSet::new();
        while running.load(Ordering::Relaxed) {
            for (name, ips) in snapshot(&mut done) {
                if seen.get(&name) != Some(&ips) {
                    let _ = tx.send(Obs::Dns { name: name.clone(), ips: ips.clone() });
                    seen.insert(name, ips);
                }
            }
            std::thread::sleep(std::time::Duration::from_millis(300));
        }
    })?;
    Ok(())
}

/// Diagnostics: `whosees-agent --dump-dns`
pub fn dump() {
    let mut head: *mut DnsCacheEntry = std::ptr::null_mut();
    let ok = unsafe { DnsGetCacheDataTable(&mut head) };
    let mut n = 0; let mut e = head; let mut sample = vec![];
    unsafe { while !e.is_null() { n += 1; if sample.len() < 5 && !(*e).name.is_null() {
        let mut l = 0; while *(*e).name.add(l) != 0 { l += 1; }
        sample.push(format!("{} type={}", String::from_utf16_lossy(std::slice::from_raw_parts((*e).name, l)), (*e).typ)); }
        e = (*e).next; } }
    println!("DnsGetCacheDataTable ok={ok} entries={n} sample={sample:?}");
    let snap = snapshot(&mut std::collections::HashSet::new());
    for (n, ips) in &snap { println!("  {n} -> {ips:?}"); }
    println!("resolved names={}", snap.len());
}

/// Windows 11 rejects cache-only (NO_WIRE) queries for most entries, so use a standard query.
/// Names come from the live cache table, so the answer is served from the cache; each name is
/// only asked about once per session (see `done`), so this doesn't generate extra DNS traffic.
const QUERY_FLAGS: u32 = 0; // DNS_QUERY_STANDARD

fn snapshot(done: &mut std::collections::HashSet<(String, u16)>) -> Vec<(String, Vec<IpAddr>)> {
    let mut out = Vec::new();
    unsafe {
        let mut head: *mut DnsCacheEntry = std::ptr::null_mut();
        if DnsGetCacheDataTable(&mut head) == 0 || head.is_null() { return out; }
        let mut names = Vec::new();
        let mut e = head;
        while !e.is_null() {
            let t = (*e).typ;
            if (t == DNS_TYPE_A || t == DNS_TYPE_AAAA) && !(*e).name.is_null() {
                let mut n = 0;
                while *(*e).name.add(n) != 0 { n += 1; }
                names.push((String::from_utf16_lossy(std::slice::from_raw_parts((*e).name, n)).to_lowercase(), t));
            }
            let next = (*e).next;
            if !(*e).name.is_null() { DnsFree((*e).name as *const _, DnsFreeFlat); }
            DnsFree(e as *const _, DnsFreeFlat);
            e = next;
        }
        names.sort(); names.dedup();
        names.retain(|n| done.insert(n.clone()));
        let mut by_name: HashMap<String, Vec<IpAddr>> = HashMap::new();
        for (name, t) in names {
            let w: Vec<u16> = name.encode_utf16().chain(std::iter::once(0)).collect();
            let mut rec: *mut DNS_RECORDA = std::ptr::null_mut();
            // NO_WIRE_QUERY: answer only from the local cache, never send a lookup.
            if DnsQuery_W(w.as_ptr(), t, QUERY_FLAGS, std::ptr::null_mut(), &mut rec, std::ptr::null_mut()) != 0 || rec.is_null() { continue; }
            let mut r = rec;
            while !r.is_null() {
                match (*r).wType {
                    DNS_TYPE_A => by_name.entry(name.clone()).or_default()
                        .push(IpAddr::V4(Ipv4Addr::from(u32::from_be((*r).Data.A.IpAddress)))),
                    DNS_TYPE_AAAA => by_name.entry(name.clone()).or_default()
                        .push(IpAddr::V6(Ipv6Addr::from((*r).Data.AAAA.Ip6Address.IP6Byte))),
                    _ => {}
                }
                r = (*r).pNext;
            }
            DnsFree(rec as *const _, DnsFreeRecordList);
        }
        out.extend(by_name);
    }
    out
}
