#![no_std]
#![no_main]

//! WhoSees Deep-mode TLS payload uprobe (OpenSSL). Egress only.
//!
//! - `SSL_set_fd(ssl, fd)` populates a (tgid, ssl_ptr) -> fd map so we can tie a
//!   later write to its socket WITHOUT walking SSL internals or calling
//!   SSL_get_fd (which returns -1 behind a custom BIO).
//! - `SSL_write(ssl, buf, num)` copies the plaintext into a ring buffer along
//!   with (pid, fd). Userspace does the matching and drops the bytes.
//!
//! Guardrails live in userspace (consent, in-memory, kinds-not-bodies); this
//! side just moves bounded plaintext snapshots up. GPL license section is
//! required for the bpf_probe_read_user helper.

use aya_ebpf::{
    helpers::bpf_probe_read_user_buf,
    macros::{map, uprobe},
    maps::{HashMap, RingBuf},
    programs::ProbeContext,
    EbpfContext,
};

// event.rs defines `SNAP` and `SslEvent`, shared with userspace.
include!("../../event.rs");

#[repr(C)]
#[derive(Clone, Copy)]
struct FdKey {
    tgid: u32,
    _pad: u32,
    ssl: u64,
}

#[map]
static EVENTS: RingBuf = RingBuf::with_byte_size(1 << 20, 0); // 1 MiB

#[map]
static FDS: HashMap<FdKey, i32> = HashMap::with_max_entries(8192, 0);

/// SSL_set_fd(SSL *ssl, int fd): remember the socket fd for this SSL*.
#[uprobe]
pub fn ssl_set_fd(ctx: ProbeContext) -> u32 {
    let _ = try_set_fd(&ctx);
    0
}

fn try_set_fd(ctx: &ProbeContext) -> Result<(), i32> {
    let ssl: u64 = ctx.arg(0).ok_or(-1i32)?;
    // `fd` is a C int: take the low 32 bits of the register (upper bits of an
    // int arg are not guaranteed zero by the SysV ABI).
    let fd_raw: usize = ctx.arg(1).ok_or(-1i32)?;
    let fd = (fd_raw as u32) as i32;
    // tgid() is the process id (what /proc is keyed by); pid() is the thread id,
    // so set_fd on one thread and write on another would never correlate.
    let tgid = ctx.tgid();
    let key = FdKey { tgid, _pad: 0, ssl };
    let _ = FDS.insert(&key, &fd, 0);
    Ok(())
}

/// SSL_write(SSL *ssl, const void *buf, int num): capture the plaintext.
#[uprobe]
pub fn ssl_write(ctx: ProbeContext) -> u32 {
    let _ = try_write(&ctx);
    0
}

fn try_write(ctx: &ProbeContext) -> Result<(), i32> {
    let ssl: u64 = ctx.arg(0).ok_or(-1i32)?;
    let buf: usize = ctx.arg(1).ok_or(-1i32)?;
    let num_raw: usize = ctx.arg(2).ok_or(-1i32)?;
    let tgid = ctx.tgid();
    let key = FdKey { tgid, _pad: 0, ssl };
    let fd = unsafe { FDS.get(&key) }.copied().unwrap_or(-1);
    capture(tgid, fd, ssl, buf, num_raw)
}

/// PR_Write / PR_Send (PRFileDesc *fd, const void *buf, PRInt32 amount): NSS /
/// Firefox plaintext. The SSL layer encrypts in its own `write` method and
/// calls the lower layer's method pointer directly, so the PR_Write *symbol*
/// only ever sees the top-layer plaintext. No socket fd is available here, so
/// we pass fd = -1 and let userspace join via /proc + SNI. The PRFileDesc
/// pointer is the stable per-connection key (the role SSL* plays for OpenSSL).
#[uprobe]
pub fn pr_write(ctx: ProbeContext) -> u32 {
    let _ = try_pr_write(&ctx);
    0
}

fn try_pr_write(ctx: &ProbeContext) -> Result<(), i32> {
    let prfd: u64 = ctx.arg(0).ok_or(-1i32)?;
    let buf: usize = ctx.arg(1).ok_or(-1i32)?;
    let amount_raw: usize = ctx.arg(2).ok_or(-1i32)?;
    let tgid = ctx.tgid();
    capture(tgid, -1, prfd, buf, amount_raw)
}

/// Copy a bounded plaintext snapshot into the ring buffer. `num_raw` is a C int
/// (OpenSSL) or PRInt32 (NSS): take the low 32 bits only, so a garbage upper
/// half can never inflate the copy length and over-read the app's memory.
fn capture(tgid: u32, fd: i32, ssl: u64, buf: usize, num_raw: usize) -> Result<(), i32> {
    let num = (num_raw as u32) as usize;
    if num == 0 {
        return Ok(());
    }
    let mut n = num;
    if n > SNAP {
        n = SNAP;
    }

    let Some(mut entry) = EVENTS.reserve::<SslEvent>(0) else {
        return Err(-1);
    };
    let ev = entry.as_mut_ptr();
    unsafe {
        (*ev).pid = tgid;
        (*ev).fd = fd;
        (*ev).ssl = ssl;
        (*ev).req_len = num as u32;
        (*ev).cap_len = n as u32;
    }
    // Userspace reads only cap_len bytes, so the tail need not be zeroed.
    let dst = unsafe { core::slice::from_raw_parts_mut((*ev).data.as_mut_ptr(), n) };
    match unsafe { bpf_probe_read_user_buf(buf as *const u8, dst) } {
        Ok(()) => {
            entry.submit(0);
            Ok(())
        }
        Err(e) => {
            entry.discard(0);
            Err(e)
        }
    }
}

#[cfg(not(test))]
#[panic_handler]
fn panic(_info: &core::panic::PanicInfo) -> ! {
    loop {}
}

#[unsafe(link_section = "license")]
#[unsafe(no_mangle)]
static LICENSE: [u8; 13] = *b"Dual MIT/GPL\0";
