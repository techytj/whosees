// Shared event layout between the eBPF program and the userspace agent.
// `include!`d by BOTH bpf/sslcap-ebpf/src/main.rs and desktop/agent/src/sslcap.rs
// so the two sides can never drift. Plain repr(C), no std, no deps.

/// Max plaintext bytes captured per SSL_write. Enough for request headers +
/// the start of a body; the userspace parser only ever reads `cap_len` bytes.
pub const SNAP: usize = 4096;

#[repr(C)]
#[derive(Clone, Copy)]
pub struct SslEvent {
    pub pid: u32,     // thread-group id (process); userspace keys /proc by this
    pub fd: i32,      // socket fd for this SSL*, or -1 if the app never set one
    pub ssl: u64,     // SSL* pointer: stable per TLS connection, the join key
    pub req_len: u32, // bytes the app asked SSL_write to send
    pub cap_len: u32, // bytes actually copied into `data` (<= SNAP)
    pub data: [u8; SNAP],
}
