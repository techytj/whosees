//! Linux socket table via netlink sock_diag (what `ss` uses). Works without root
//! and includes per-socket byte counters for TCP (tcp_info).

use std::net::{IpAddr, Ipv4Addr, Ipv6Addr};

pub use crate::sock::{Proto, Sock, TCP_LISTEN};


const SOCK_DIAG_BY_FAMILY: u16 = 20;
const NETLINK_SOCK_DIAG: i32 = 4;
const NLMSG_DONE: u16 = 3;
const NLMSG_ERROR: u16 = 2;
const INET_DIAG_INFO: u16 = 2;

pub struct Diag { fd: i32, seq: u32, buf: Vec<u8> }

impl Diag {
    pub fn new() -> std::io::Result<Diag> {
        let fd = unsafe { libc::socket(libc::AF_NETLINK, libc::SOCK_DGRAM | libc::SOCK_CLOEXEC, NETLINK_SOCK_DIAG) };
        if fd < 0 { return Err(std::io::Error::last_os_error()); }
        Ok(Diag { fd, seq: 1, buf: vec![0u8; 1 << 16] })
    }

    /// Dump all sockets of all four kinds.
    pub fn dump(&mut self) -> std::io::Result<Vec<Sock>> {
        let mut out = Vec::with_capacity(512);
        for fam in [libc::AF_INET as u8, libc::AF_INET6 as u8] {
            for proto in [Proto::Tcp, Proto::Udp] {
                self.dump_one(fam, proto, &mut out)?;
            }
        }
        Ok(out)
    }

    fn dump_one(&mut self, family: u8, proto: Proto, out: &mut Vec<Sock>) -> std::io::Result<()> {
        // nlmsghdr (16) + inet_diag_req_v2 (56)
        let mut req = [0u8; 72];
        req[0..4].copy_from_slice(&72u32.to_ne_bytes());
        req[4..6].copy_from_slice(&SOCK_DIAG_BY_FAMILY.to_ne_bytes());
        req[6..8].copy_from_slice(&((libc::NLM_F_REQUEST | libc::NLM_F_DUMP) as u16).to_ne_bytes());
        self.seq = self.seq.wrapping_add(1);
        req[8..12].copy_from_slice(&self.seq.to_ne_bytes());
        req[16] = family;
        req[17] = if proto == Proto::Tcp { libc::IPPROTO_TCP as u8 } else { libc::IPPROTO_UDP as u8 };
        req[18] = 1 << (INET_DIAG_INFO - 1); // ask for tcp_info
        req[20..24].copy_from_slice(&u32::MAX.to_ne_bytes()); // all states

        let mut sa: libc::sockaddr_nl = unsafe { std::mem::zeroed() };
        sa.nl_family = libc::AF_NETLINK as u16;
        let r = unsafe {
            libc::sendto(self.fd, req.as_ptr() as *const _, req.len(), 0,
                         &sa as *const _ as *const libc::sockaddr, std::mem::size_of::<libc::sockaddr_nl>() as u32)
        };
        if r < 0 { return Err(std::io::Error::last_os_error()); }

        loop {
            let n = unsafe { libc::recv(self.fd, self.buf.as_mut_ptr() as *mut _, self.buf.len(), 0) };
            if n < 0 { return Err(std::io::Error::last_os_error()); }
            let n = n as usize;
            let mut o = 0;
            while o + 16 <= n {
                let b = &self.buf[o..n];
                let len = u32::from_ne_bytes(b[0..4].try_into().unwrap()) as usize;
                let typ = u16::from_ne_bytes(b[4..6].try_into().unwrap());
                if len < 16 || len > b.len() { return Ok(()); }
                match typ {
                    NLMSG_DONE => return Ok(()),
                    NLMSG_ERROR => return Ok(()), // e.g. family unsupported: treat as empty
                    SOCK_DIAG_BY_FAMILY => {
                        if let Some(s) = parse(&b[16..len], proto) { out.push(s); }
                    }
                    _ => {}
                }
                o += (len + 3) & !3;
            }
        }
    }
}

impl Drop for Diag {
    fn drop(&mut self) { unsafe { libc::close(self.fd); } }
}

fn parse(m: &[u8], proto: Proto) -> Option<Sock> {
    if m.len() < 72 { return None; }
    let family = m[0];
    let state = m[1];
    let id = &m[4..52];
    let lport = u16::from_be_bytes([id[0], id[1]]);
    let rport = u16::from_be_bytes([id[2], id[3]]);
    let addr = |a: &[u8]| -> IpAddr {
        if family == libc::AF_INET as u8 {
            IpAddr::V4(Ipv4Addr::new(a[0], a[1], a[2], a[3]))
        } else {
            let v6 = Ipv6Addr::from(<[u8; 16]>::try_from(&a[..16]).unwrap());
            match v6.to_ipv4_mapped() { Some(v4) => IpAddr::V4(v4), None => IpAddr::V6(v6) }
        }
    };
    let local = addr(&id[4..20]);
    let remote = addr(&id[20..36]);
    let uid = u32::from_ne_bytes(m[64..68].try_into().unwrap());
    let inode = u32::from_ne_bytes(m[68..72].try_into().unwrap()) as u64;

    let (mut sent, mut recv) = (0, 0);
    let mut o = 72;
    while o + 4 <= m.len() {
        let alen = u16::from_ne_bytes(m[o..o + 2].try_into().unwrap()) as usize;
        let atype = u16::from_ne_bytes(m[o + 2..o + 4].try_into().unwrap());
        if alen < 4 || o + alen > m.len() { break; }
        if atype == INET_DIAG_INFO && proto == Proto::Tcp {
            let p = &m[o + 4..o + alen];
            if p.len() >= 136 {
                sent = u64::from_ne_bytes(p[120..128].try_into().unwrap()); // tcpi_bytes_acked
                recv = u64::from_ne_bytes(p[128..136].try_into().unwrap()); // tcpi_bytes_received
            }
        }
        o += (alen + 3) & !3;
    }
    Some(Sock { proto, state, local, lport, remote, rport, uid, inode, pid: 0, bytes_sent: sent, bytes_recv: recv })
}
