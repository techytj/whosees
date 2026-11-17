//! Linux Deep-mode TLS payload capture (M1).
//!
//! Reads the plaintext an app hands to OpenSSL's `SSL_write` *before* it is
//! encrypted, via an eBPF uprobe, matches it to the connection the agent
//! already tracks, runs the `datatypes` matchers, and emits the existing
//! `Obs::Data` events so the report's "Seen" section lights up. Highest
//! sensitivity code in the project — guardrails are non-negotiable:
//!
//!   * OFF by default; only runs in Deep mode AND when `--read-payloads` is set.
//!   * Plaintext lives in memory only: matched, then dropped. Never written to
//!     disk, the report PDF, or logs. Only DataItem *kinds* (masked) leave here.
//!   * Torn down at Stop.
//!
//! Joining a write to a connection: the probe hands us the SSL* pointer (stable
//! per TLS connection) and, when the app called `SSL_set_fd`, the socket fd.
//! Modern curl never calls `SSL_set_fd` (it wraps the socket in its own BIO), so
//! the fd is often -1. In that case we take the pid's established TCP flows from
//! `/proc/<pid>/fd` intersected with the kernel socket table and confirm the one
//! whose SNI equals the request's Host / `:authority`. We never guess: an
//! ambiguous pid drops the write. The host is used only to pick the connection;
//! it never enters a DataItem or the report.

use crate::datatypes::DataItem;
use crate::http2::{is_h2_preface, Hpack};
use std::collections::HashMap;

// SslEvent + SNAP: the exact layout the eBPF program writes into the ring
// buffer. Shared via include! so the two sides can never drift.
include!("../bpf/event.rs");
unsafe impl aya::Pod for SslEvent {}

/// Resolve `(pid, fd)` to the socket inode the agent keys connections by.
/// Reads `/proc/<pid>/fd/<fd>` which is a symlink like `socket:[12345]`.
/// Returns None for non-socket fds or a vanished process (never guesses).
pub fn fd_to_inode(pid: u32, fd: i32) -> Option<u64> {
    if fd < 0 {
        return None;
    }
    let link = std::fs::read_link(format!("/proc/{pid}/fd/{fd}")).ok()?;
    socket_inode(&link)
}

/// Parse `socket:[12345]` (the target of a socket fd symlink) to its inode.
fn socket_inode(link: &std::path::Path) -> Option<u64> {
    link.to_str()?
        .strip_prefix("socket:[")?
        .strip_suffix(']')?
        .parse()
        .ok()
}

/// Every established TCP flow this process owns, as `(inode, flow)`. Walks the
/// pid's fd table and keeps only sockets present in the current kernel dump
/// (which is already filtered to connected TCP). Used when the write carried no
/// usable fd. Requires root in practice; returns empty for a vanished process.
fn pid_tcp_flows(pid: u32, inode_flow: &HashMap<u64, FlowKey>) -> Vec<(u64, FlowKey)> {
    let mut out: Vec<(u64, FlowKey)> = Vec::new();
    let Ok(rd) = std::fs::read_dir(format!("/proc/{pid}/fd")) else { return out };
    for e in rd.flatten() {
        if let Ok(link) = std::fs::read_link(e.path()) {
            if let Some(ino) = socket_inode(&link) {
                if let Some(&f) = inode_flow.get(&ino) {
                    if !out.iter().any(|(_, g)| *g == f) {
                        out.push((ino, f));
                    }
                }
            }
        }
    }
    out
}

/// Pick the connection a decrypted write belongs to from a pid's candidate
/// flows, confirming with the request host when we have one. Pure, so the
/// policy is unit-tested without root. Never guesses across hosts:
///   * host known: join iff exactly one candidate's SNI matches it; if none
///     match (SNI never seen, or it disagrees), refuse — don't guess.
///   * host unknown (non-HTTP write): join iff there is a single candidate.
/// Any ambiguity returns None and the write is dropped.
fn choose_flow<F: Fn(&FlowKey) -> Option<String>>(
    host: Option<&str>,
    cands: &[(u64, FlowKey)],
    sni: F,
) -> Option<(u64, FlowKey)> {
    if cands.is_empty() {
        return None;
    }
    if let Some(h) = host {
        let matched: Vec<(u64, FlowKey)> = cands
            .iter()
            .copied()
            .filter(|(_, f)| sni(f).map_or(false, |s| s.eq_ignore_ascii_case(h)))
            .collect();
        if matched.len() == 1 {
            return Some(matched[0]);
        }
        if matched.len() > 1 {
            return None; // two connections to the same host: can't tell apart
        }
        // Host matched no candidate's SNI (never observed, or it disagrees):
        // refuse rather than risk attaching the data to the wrong connection.
        return None;
    }
    // Host unknown: a single candidate is unambiguous; more than one is not.
    if cands.len() == 1 {
        Some(cands[0])
    } else {
        None
    }
}

/// Per-connection plaintext → DataItems, keyed by the SSL* pointer so HTTP/2
/// HPACK state (dynamic table) survives across writes on the same connection.
/// Pure and testable; the eBPF side feeds it captured buffers.
#[derive(Default)]
pub struct PayloadRouter {
    /// (tgid, ssl_ptr) -> HPACK decoder, created once a connection is HTTP/2.
    h2: HashMap<(u32, u64), Hpack>,
}

impl PayloadRouter {
    pub fn new() -> Self {
        Self::default()
    }

    /// Feed one captured egress plaintext buffer for a connection, keyed by its
    /// SSL* pointer. Returns the (masked) kinds observed plus the request host
    /// (for connection confirmation only; never retained, never reported). The
    /// buffer itself is NOT retained.
    pub fn observe(&mut self, tgid: u32, ssl: u64, data: &[u8]) -> (Vec<DataItem>, Option<String>) {
        // Bound memory: we get no reliable close signal, so cap decoder state.
        // Dropping it only resets HPACK dynamic tables (decoding self-heals).
        if self.h2.len() > 8192 {
            self.h2.clear();
        }
        let key = (tgid, ssl);
        // An HTTP/2 preface means a new connection. If this SSL* pointer was
        // reused (freed then reallocated), reset its decoder so a stale dynamic
        // table can't corrupt the new stream.
        if is_h2_preface(data) {
            self.h2.insert(key, Hpack::new());
        }
        if self.h2.contains_key(&key) {
            let dec = self.h2.entry(key).or_default();
            crate::datatypes::inspect_payload_h2_host(dec, data)
        } else {
            crate::datatypes::inspect_payload_host(data)
        }
    }

    /// Drop a connection's decoder state when it closes. (Reserved for when
    /// close events are wired through from the main loop; see the cap in `observe`.)
    #[allow(dead_code)]
    pub fn forget(&mut self, tgid: u32, ssl: u64) {
        self.h2.remove(&(tgid, ssl));
    }

    /// Drop all state (on Stop / teardown).
    pub fn clear(&mut self) {
        self.h2.clear();
    }

    #[cfg(test)]
    fn tracks_h2(&self, tgid: u32, ssl: u64) -> bool {
        self.h2.contains_key(&(tgid, ssl))
    }
}

// ---------------------------------------------------------------------------
// eBPF loader + ring reader (root, Deep mode only). Runs on its own thread and
// tears down when `running` goes false.
// ---------------------------------------------------------------------------

use crate::sniff::{FlowKey, Obs};
use std::os::fd::AsRawFd;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::Sender;
use std::sync::Arc;
use std::time::{Duration, Instant};

/// Resolve a candidate library list to real, existing, de-duplicated paths.
/// `canonicalize` both filters non-existent entries and collapses symlinks, so
/// on Fedora (where `/lib64` -> `/usr/lib64`) the same file is never attached
/// twice — a double attach would double every event and decode HTTP/2 headers
/// into the HPACK table twice.
fn canonical_existing(candidates: &[&str]) -> Vec<String> {
    let mut seen = std::collections::HashSet::new();
    let mut out = Vec::new();
    for p in candidates {
        let Ok(canon) = std::fs::canonicalize(p) else { continue };
        if seen.insert(canon.clone()) {
            out.push(canon.to_string_lossy().into_owned());
        }
    }
    out
}

/// OpenSSL shared objects to attach uprobes to (apps may use .3 or .4).
fn openssl_paths() -> Vec<String> {
    canonical_existing(&[
        "/lib64/libssl.so.4",
        "/lib64/libssl.so.3",
        "/usr/lib64/libssl.so.4",
        "/usr/lib64/libssl.so.3",
        "/usr/lib/x86_64-linux-gnu/libssl.so.3",
        "/lib/x86_64-linux-gnu/libssl.so.3",
        "/usr/lib/libssl.so.3",
    ])
}

/// NSS/NSPR shared object: Firefox and other NSS apps hand TLS plaintext to
/// `PR_Write` / `PR_Send` in libnspr4 (the SSL layer encrypts below it).
fn nss_paths() -> Vec<String> {
    canonical_existing(&[
        "/lib64/libnspr4.so",
        "/usr/lib64/libnspr4.so",
        "/usr/lib/x86_64-linux-gnu/libnspr4.so",
        "/lib/x86_64-linux-gnu/libnspr4.so",
    ])
}

/// True if process `tgid` still has `ino` open as a socket. Used to validate a
/// cached join on a hot path: when a connection closes (or its SSL* pointer is
/// reused for a new connection, as in `curl https://a https://b`), the old inode
/// leaves the fd table and the cache entry must not be trusted.
fn pid_owns_inode(tgid: u32, ino: u64) -> bool {
    let target = format!("socket:[{ino}]");
    let Ok(rd) = std::fs::read_dir(format!("/proc/{tgid}/fd")) else { return false };
    for e in rd.flatten() {
        if let Ok(link) = std::fs::read_link(e.path()) {
            if link.to_str() == Some(target.as_str()) {
                return true;
            }
        }
    }
    false
}

/// Load the prebuilt eBPF object, attach the OpenSSL (`SSL_write`) and NSS
/// (`PR_Write`/`PR_Send`) uprobes, and spawn the ring-reader thread. Returns
/// once attached (errors propagate so Deep mode can warn and carry on without
/// payload reading). Both libraries' writes join through the same /proc + SNI
/// path, so NSS needs no PRFileDesc offset walking.
pub fn start(tx: Sender<Obs>, running: Arc<AtomicBool>) -> Result<(), Box<dyn std::error::Error>> {
    use aya::programs::{uprobe::UProbeScope, UProbe};

    // eBPF maps need locked memory on older kernels; harmless elsewhere.
    let rlim = libc::rlimit { rlim_cur: libc::RLIM_INFINITY, rlim_max: libc::RLIM_INFINITY };
    unsafe { libc::setrlimit(libc::RLIMIT_MEMLOCK, &rlim) };

    let mut ebpf = aya::Ebpf::load(aya::include_bytes_aligned!(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/src/sslcap.bpf.o"
    )))?;

    let openssl = openssl_paths();
    let nss = nss_paths();
    if openssl.is_empty() && nss.is_empty() {
        return Err("no system libssl or libnspr4 found to attach to".into());
    }
    let mut attached = false; // at least one egress-plaintext probe must land

    if !openssl.is_empty() {
        // SSL_set_fd -> builds the (pid,ssl)->fd map used for correlation.
        {
            let p: &mut UProbe = ebpf.program_mut("ssl_set_fd").ok_or("missing ssl_set_fd")?.try_into()?;
            p.load()?;
            for lib in &openssl {
                let _ = p.attach("SSL_set_fd", lib, UProbeScope::AllProcesses);
            }
        }
        // SSL_write -> captures OpenSSL egress plaintext.
        let p: &mut UProbe = ebpf.program_mut("ssl_write").ok_or("missing ssl_write")?.try_into()?;
        p.load()?;
        for lib in &openssl {
            if p.attach("SSL_write", lib, UProbeScope::AllProcesses).is_ok() {
                attached = true;
            }
        }
    }

    if !nss.is_empty() {
        // PR_Write / PR_Send -> NSS (Firefox) egress plaintext. No fd here, so
        // the write is joined in userspace via /proc + SNI.
        let p: &mut UProbe = ebpf.program_mut("pr_write").ok_or("missing pr_write")?.try_into()?;
        p.load()?;
        for lib in &nss {
            for sym in ["PR_Write", "PR_Send"] {
                if p.attach(sym, lib, UProbeScope::AllProcesses).is_ok() {
                    attached = true;
                }
            }
        }
    }

    if !attached {
        return Err("could not attach any TLS write probe (SSL_write / PR_Write)".into());
    }

    let ring = aya::maps::RingBuf::try_from(ebpf.take_map("EVENTS").ok_or("missing EVENTS map")?)?;

    std::thread::Builder::new()
        .name("sslcap".into())
        .spawn(move || reader_loop(ebpf, ring, tx, running))?;
    Ok(())
}

/// Rebuild the inode -> flow map from the kernel socket table, keeping only
/// established TCP flows (a remote port, not listening). UDP resolver sockets
/// and listeners must not become join candidates.
fn refresh_flows(diag: &mut Option<crate::diag::Diag>, out: &mut HashMap<u64, FlowKey>) {
    if let Some(d) = diag.as_mut() {
        if let Ok(socks) = d.dump() {
            out.clear();
            for s in socks {
                if s.proto == crate::diag::Proto::Tcp
                    && s.rport != 0
                    && s.state != crate::diag::TCP_LISTEN
                {
                    out.insert(s.inode, (s.local, s.lport, s.remote, s.rport));
                }
            }
        }
    }
}

/// Count-only diagnostics for the one root run. No plaintext, just where
/// captured writes went, printed once at teardown so a live test can tell
/// "probe never fired" from "fired but couldn't be joined".
#[derive(Default)]
struct Drops {
    events: u64,       // ring events read
    fd_neg: u64,       // events whose fd was -1 (app never called SSL_set_fd)
    empty: u64,        // nothing matched and no host -> nothing to attribute
    by_fd: u64,        // joined via the SSL_set_fd socket fd
    by_cache: u64,     // joined via the cached (tgid,ssl) -> flow
    by_candidate: u64, // joined via /proc candidate (single or host-confirmed)
    unjoined: u64,     // had kinds but no connection could be resolved -> dropped
    sent: u64,         // Obs::Data events emitted
}

/// Resolve a write to its connection the hard way (no cache): direct fd first,
/// then the pid's candidate flows confirmed by host. Inserts the winner into the
/// cache with its inode. The caller handles the cache-hit fast path, so this is
/// only reached on a miss — against a freshly refreshed socket table.
fn resolve_fresh(
    tgid: u32,
    ssl: u64,
    fd: i32,
    host: Option<&str>,
    cache: &mut HashMap<(u32, u64), (u64, FlowKey)>,
    inode_flow: &HashMap<u64, FlowKey>,
    counters: &mut Drops,
) -> Option<FlowKey> {
    if fd >= 0 {
        if let Some(ino) = fd_to_inode(tgid, fd) {
            if let Some(&f) = inode_flow.get(&ino) {
                cache_insert(cache, (tgid, ssl), (ino, f));
                counters.by_fd += 1;
                return Some(f);
            }
        }
    }
    let cands = pid_tcp_flows(tgid, inode_flow);
    if let Some((ino, f)) = choose_flow(host, &cands, |fl| crate::sniff::host_for_flow(fl)) {
        cache_insert(cache, (tgid, ssl), (ino, f));
        counters.by_candidate += 1;
        return Some(f);
    }
    None
}

/// Insert a resolved join, bounding the cache (we get no reliable close signal).
fn cache_insert(cache: &mut HashMap<(u32, u64), (u64, FlowKey)>, k: (u32, u64), v: (u64, FlowKey)) {
    if cache.len() > 8192 {
        cache.clear(); // entries only cache a lookup; re-resolution self-heals
    }
    cache.insert(k, v);
}

fn reader_loop(
    _ebpf: aya::Ebpf, // kept alive so the uprobes stay attached; dropped => detached
    mut ring: aya::maps::RingBuf<aya::maps::MapData>,
    tx: Sender<Obs>,
    running: Arc<AtomicBool>,
) {
    let fd = ring.as_raw_fd();
    let mut router = PayloadRouter::new();
    let mut diag = crate::diag::Diag::new().ok();
    let mut inode_flow: HashMap<u64, FlowKey> = HashMap::new();
    let mut flow_cache: HashMap<(u32, u64), (u64, FlowKey)> = HashMap::new();
    let mut last_dump = Instant::now() - Duration::from_secs(1);
    let mut counters = Drops::default();
    // main() exits right after `running` flips, without joining us, so print the
    // counters on change (throttled) — the teardown print alone would race exit.
    let mut last_report = Instant::now() - Duration::from_secs(2);
    let mut reported = (0u64, 0u64);

    while running.load(Ordering::Relaxed) {
        if last_dump.elapsed() > Duration::from_millis(500) {
            refresh_flows(&mut diag, &mut inode_flow);
            last_dump = Instant::now();
        }

        let mut pfd = libc::pollfd { fd, events: libc::POLLIN, revents: 0 };
        let r = unsafe { libc::poll(&mut pfd, 1, 250) };
        if r <= 0 {
            report_counters(&counters, &mut reported, &mut last_report, false);
            continue; // timeout / EINTR — re-check running
        }

        while let Some(item) = ring.next() {
            if item.len() < std::mem::size_of::<SslEvent>() {
                continue;
            }
            let ev = unsafe { std::ptr::read_unaligned(item.as_ptr() as *const SslEvent) };
            let cap = (ev.cap_len as usize).min(SNAP);
            let data = &ev.data[..cap];
            counters.events += 1;
            if ev.fd < 0 {
                counters.fd_neg += 1;
            }

            // A fresh preface means a (possibly reused) SSL* starting a new
            // connection: drop any cached flow so we re-resolve it.
            if is_h2_preface(data) {
                flow_cache.remove(&(ev.pid, ev.ssl));
            }

            let (items, host) = router.observe(ev.pid, ev.ssl, data);
            if items.is_empty() {
                if host.is_none() {
                    counters.empty += 1;
                }
                continue; // nothing to attribute (e.g. HTTP/2 SETTINGS write)
            }

            // Cache-hit fast path: trust a cached join only while the process
            // still owns that socket inode AND it still maps to the same flow.
            let key = (ev.pid, ev.ssl);
            let mut flow = None;
            if let Some(&(ino, f)) = flow_cache.get(&key) {
                if inode_flow.get(&ino) == Some(&f) && pid_owns_inode(ev.pid, ino) {
                    counters.by_cache += 1;
                    flow = Some(f);
                } else {
                    flow_cache.remove(&key); // closed or SSL* reused
                }
            }
            // Miss: resolve against a fresh socket table (a brand-new connection
            // may post-date the last 500 ms dump; a stale table could otherwise
            // pin the write to the wrong flow).
            if flow.is_none() {
                if last_dump.elapsed() > Duration::from_millis(50) {
                    refresh_flows(&mut diag, &mut inode_flow);
                    last_dump = Instant::now();
                }
                flow = resolve_fresh(ev.pid, ev.ssl, ev.fd, host.as_deref(), &mut flow_cache, &inode_flow, &mut counters);
            }

            let Some(flow) = flow else {
                counters.unjoined += 1;
                continue; // never guess a connection
            };
            counters.sent += 1;
            // channel closed => UI gone; stop.
            if tx.send(Obs::Data { tcp: true, flow, items }).is_err() {
                router.clear();
                return;
            }
        }
        report_counters(&counters, &mut reported, &mut last_report, false);
    }
    router.clear(); // drop all plaintext-derived state on teardown
    report_counters(&counters, &mut reported, &mut last_report, true);
}

/// Emit the count-only diagnostic line (no plaintext) when the totals moved and
/// at least a second passed, or unconditionally at teardown (`force`).
fn report_counters(c: &Drops, reported: &mut (u64, u64), last: &mut Instant, force: bool) {
    let now = (c.events, c.sent);
    if !force && (now == *reported || last.elapsed() < Duration::from_secs(1)) {
        return;
    }
    *reported = now;
    *last = Instant::now();
    eprintln!(
        "sslcap: events={} sent={} by_fd={} by_cache={} by_candidate={} unjoined={} fd_neg={} empty={}",
        c.events, c.sent, c.by_fd, c.by_cache, c.by_candidate, c.unjoined, c.fd_neg, c.empty
    );
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::{IpAddr, Ipv4Addr};
    use std::os::fd::AsRawFd;

    fn flow(rport: u16) -> FlowKey {
        (
            IpAddr::V4(Ipv4Addr::new(10, 0, 0, 2)),
            40000 + rport,
            IpAddr::V4(Ipv4Addr::new(93, 184, 216, 34)),
            rport,
        )
    }

    #[test]
    fn fd_to_inode_resolves_a_real_socket() {
        let sock = std::net::UdpSocket::bind("127.0.0.1:0").unwrap();
        let fd = sock.as_raw_fd();
        let inode = fd_to_inode(std::process::id(), fd);
        assert!(inode.is_some(), "expected a socket inode");
        // a non-socket fd (a regular file) resolves to None
        let f = std::fs::File::open("/proc/self/stat").unwrap();
        assert_eq!(fd_to_inode(std::process::id(), f.as_raw_fd()), None);
        // negative / bogus fd
        assert_eq!(fd_to_inode(std::process::id(), -1), None);
    }

    #[test]
    fn choose_single_candidate_without_host() {
        let c = [(100u64, flow(443))];
        // No host, one candidate -> join it.
        assert_eq!(choose_flow(None, &c, |_| None), Some(c[0]));
        // No host, two candidates -> ambiguous, drop.
        let two = [(100u64, flow(443)), (101u64, flow(8443))];
        assert_eq!(choose_flow(None, &two, |_| None), None);
    }

    #[test]
    fn choose_disambiguates_by_sni() {
        let a = (100u64, flow(443));
        let b = (101u64, flow(8443));
        let cands = [a, b];
        let sni = |f: &FlowKey| {
            if *f == a.1 { Some("example.com".to_string()) }
            else if *f == b.1 { Some("tracker.net".to_string()) }
            else { None }
        };
        // Host matches exactly one candidate's SNI -> that one.
        assert_eq!(choose_flow(Some("example.com"), &cands, sni), Some(a));
        assert_eq!(choose_flow(Some("tracker.net"), &cands, sni), Some(b));
        // Case-insensitive.
        assert_eq!(choose_flow(Some("EXAMPLE.COM"), &cands, sni), Some(a));
        // Host matches none of the known SNIs, multiple candidates -> drop.
        assert_eq!(choose_flow(Some("other.org"), &cands, sni), None);
    }

    #[test]
    fn choose_two_connections_same_host_is_ambiguous() {
        let a = (100u64, flow(443));
        let b = (101u64, flow(8443));
        let cands = [a, b];
        // Both candidates are the same host -> cannot tell apart -> drop.
        assert_eq!(choose_flow(Some("example.com"), &cands, |_| Some("example.com".to_string())), None);
    }

    #[test]
    fn choose_lone_unknown_sni_with_known_host_is_dropped() {
        let a = (100u64, flow(443));
        let cands = [a];
        // Host known but the one candidate's SNI was never observed -> refuse to
        // attribute: we won't guess the write belongs to it.
        assert_eq!(choose_flow(Some("example.com"), &cands, |_| None), None);
        // A lone candidate whose SNI we DID see and that disagrees -> drop.
        assert_eq!(choose_flow(Some("example.com"), &cands, |_| Some("elsewhere.com".to_string())), None);
    }

    #[test]
    fn router_keeps_h2_state_per_connection() {
        let mut r = PayloadRouter::new();
        // First write carries the preface -> connection becomes HTTP/2.
        let block = [0x82u8, 0x86, 0x84, 0x41, 0x8c, 0xf1, 0xe3, 0xc2, 0xe5, 0xf2, 0x3a, 0x6b, 0xa0, 0xab, 0x90, 0xf4, 0xff];
        let mut buf = Vec::new();
        buf.extend_from_slice(crate::http2::H2_PREFACE);
        let len = block.len();
        buf.extend_from_slice(&[(len >> 16) as u8, (len >> 8) as u8, len as u8, 0x01, 0x04, 0, 0, 0, 1]);
        buf.extend_from_slice(&block);
        let ssl_a = 0xdead_beef_u64;
        let (items, host) = r.observe(4242, ssl_a, &buf);
        assert!(items.iter().any(|x| x.kind == "browsing"), "{items:?}");
        assert_eq!(host.as_deref(), Some("www.example.com"));
        assert!(r.tracks_h2(4242, ssl_a));
        // An HTTP/1 connection (different SSL*) stays on the h1 path.
        let h1 = b"GET /p?q=hi HTTP/1.1\r\nHost: x.example\r\n\r\n";
        let ssl_b = 0xfeed_face_u64;
        let (items2, host2) = r.observe(4242, ssl_b, h1);
        assert!(items2.iter().any(|x| x.kind == "browsing"));
        assert_eq!(host2.as_deref(), Some("x.example"));
        assert!(!r.tracks_h2(4242, ssl_b));
        r.forget(4242, ssl_a);
        assert!(!r.tracks_h2(4242, ssl_a));
    }

    #[test]
    fn pid_tcp_flows_finds_nothing_for_untracked_inodes() {
        // A real socket exists, but our (empty) table knows no flows, so there
        // are no candidates. Proves we never invent a flow.
        let sock = std::net::UdpSocket::bind("127.0.0.1:0").unwrap();
        let _ = sock.as_raw_fd();
        let empty: HashMap<u64, FlowKey> = HashMap::new();
        assert!(pid_tcp_flows(std::process::id(), &empty).is_empty());
    }
}
