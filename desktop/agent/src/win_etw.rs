//! Windows Deep mode: Event Tracing for Windows (ETW), Microsoft-Windows-Kernel-Network.
//! Built into Windows (no driver). Needs admin. Reports every TCP/UDP send/receive with the
//! process id, both addresses and the size, so it catches short connections and QUIC/UDP
//! that the socket table misses, and gives real byte counts. Contents are never read.

use crate::sock::Proto;
use ferrisetw::parser::Parser;
use ferrisetw::provider::Provider;
use ferrisetw::schema_locator::SchemaLocator;
use ferrisetw::trace::UserTrace;
use ferrisetw::EventRecord;
use std::collections::HashMap;
use std::net::IpAddr;
use std::sync::{Arc, Mutex};
use std::time::Instant;

const KERNEL_NETWORK: &str = "7dd42a49-5329-4832-8dfd-43d979153a88";
const DNS_CLIENT: &str = "1c95126e-7eea-49a9-a3fe-a378b03ddb4d";
const SESSION: &str = "WhoSees-Network";

#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug)]
pub struct EtwKey { pub proto: Proto, pub local: IpAddr, pub lport: u16, pub remote: IpAddr, pub rport: u16 }

#[derive(Clone, Debug)]
pub struct EtwFlow { pub pid: u32, pub sent: u64, pub recv: u64, pub last: Instant, pub closed: bool }

pub type Flows = Arc<Mutex<HashMap<EtwKey, EtwFlow>>>;

pub struct Etw { _trace: UserTrace }

pub fn start(flows: Flows, dns_tx: std::sync::mpsc::Sender<crate::sniff::Obs>) -> Result<Etw, String> {
    // A session left behind by a crashed run would block ours: stop it first.
    let _ = std::process::Command::new("logman").args(["stop", SESSION, "-ets"])
        .stdout(std::process::Stdio::null()).stderr(std::process::Stdio::null()).status();
    let f = flows.clone();
    let cb = move |record: &EventRecord, locator: &SchemaLocator| {
        let id = record.event_id();
        // 10/26 TCP send, 11/27 TCP recv, 12/28 connect, 13/29 disconnect, 42/58 UDP send, 43/59 UDP recv (v4/v6)
        let (proto, dir) = match id {
            10 | 26 => (Proto::Tcp, 1), 11 | 27 => (Proto::Tcp, 2), 12 | 28 | 15 | 31 => (Proto::Tcp, 0), 13 | 29 => (Proto::Tcp, 3),
            42 | 58 => (Proto::Udp, 1), 43 | 59 => (Proto::Udp, 2),
            _ => return,
        };
        let Ok(schema) = locator.event_schema(record) else { return };
        let p = Parser::create(record, &schema);
        let (Ok(pid), Ok(daddr), Ok(saddr), Ok(dport), Ok(sport)) = (
            p.try_parse::<u32>("PID"), p.try_parse::<IpAddr>("daddr"), p.try_parse::<IpAddr>("saddr"),
            p.try_parse::<u16>("dport"), p.try_parse::<u16>("sport"),
        ) else { return };
        let size = p.try_parse::<u32>("size").unwrap_or(0) as u64;
        // Ports are in network byte order. daddr/dport is always the remote end in this provider.
        let key = EtwKey { proto, local: unmap(saddr), lport: u16::from_be(sport), remote: unmap(daddr), rport: u16::from_be(dport) };
        // Receives are often reported in another process's context: trust the pid of
        // connects and sends only.
        let trusted = dir <= 1;
        if trusted { crate::procs::remember(pid); }
        if let Ok(mut m) = f.lock() {
            let e = m.entry(key).or_insert(EtwFlow { pid, sent: 0, recv: 0, last: Instant::now(), closed: false });
            if trusted { e.pid = pid; }
            e.last = Instant::now();
            match dir { 1 => e.sent += size, 2 => e.recv += size, 3 => e.closed = true, _ => e.closed = false }
        }
    };
    let provider = Provider::by_guid(KERNEL_NETWORK).add_callback(cb).build();

    // DNS client: event 3008 = query completed, with the answers. Gives names the instant
    // they're looked up, so even very short connections get their website name.
    let tx = std::sync::Mutex::new(dns_tx);
    let dns_cb = move |record: &EventRecord, locator: &SchemaLocator| {
        if record.event_id() != 3008 { return; }
        let Ok(schema) = locator.event_schema(record) else { return };
        let p = Parser::create(record, &schema);
        let (Ok(name), Ok(results)) = (p.try_parse::<String>("QueryName"), p.try_parse::<String>("QueryResults")) else { return };
        let ips: Vec<IpAddr> = results.split(';').filter_map(|x| x.trim().parse::<IpAddr>().ok()).map(unmap).collect();
        if ips.is_empty() || name.is_empty() { return; }
        if let Ok(t) = tx.lock() { let _ = t.send(crate::sniff::Obs::Dns { name: name.to_lowercase(), ips }); }
    };
    let dns_provider = Provider::by_guid(DNS_CLIENT).add_callback(dns_cb).build();

    let trace = UserTrace::new().named(SESSION.to_string()).enable(provider).enable(dns_provider).start_and_process()
        .map_err(|e| format!("{e:?}"))?;
    Ok(Etw { _trace: trace })
}

fn unmap(a: IpAddr) -> IpAddr {
    match a { IpAddr::V6(v) => v.to_ipv4_mapped().map(IpAddr::V4).unwrap_or(a), x => x }
}
