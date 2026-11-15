//! Windows socket table via the IP Helper API (what `netstat -ano` uses). No admin needed.
//! TCP rows carry the owning process id. UDP rows have no remote address on Windows,
//! so UDP (QUIC, DNS) only becomes visible with Deep mode (ETW, future work).

pub use crate::sock::{Proto, Sock, TCP_LISTEN};
use std::net::{IpAddr, Ipv4Addr, Ipv6Addr};
use windows_sys::Win32::NetworkManagement::IpHelper::{GetExtendedTcpTable, TCP_TABLE_OWNER_PID_ALL};
use windows_sys::Win32::Networking::WinSock::{AF_INET, AF_INET6};

const ERROR_INSUFFICIENT_BUFFER: u32 = 122;

pub struct Diag { buf: Vec<u8> }

impl Diag {
    pub fn new() -> std::io::Result<Diag> { Ok(Diag { buf: vec![0u8; 64 * 1024] }) }

    pub fn dump(&mut self) -> std::io::Result<Vec<Sock>> {
        let mut out = Vec::with_capacity(256);
        self.tcp(AF_INET as u32, &mut out)?;
        self.tcp(AF_INET6 as u32, &mut out)?;
        Ok(out)
    }

    fn tcp(&mut self, family: u32, out: &mut Vec<Sock>) -> std::io::Result<()> {
        loop {
            let mut size = self.buf.len() as u32;
            let r = unsafe {
                GetExtendedTcpTable(self.buf.as_mut_ptr() as *mut _, &mut size, 0, family, TCP_TABLE_OWNER_PID_ALL, 0)
            };
            if r == ERROR_INSUFFICIENT_BUFFER { self.buf.resize(size as usize + 4096, 0); continue; }
            if r != 0 { return Err(std::io::Error::from_raw_os_error(r as i32)); }
            break;
        }
        let b = &self.buf;
        let n = u32::from_le_bytes(b[0..4].try_into().unwrap()) as usize;
        let port = |v: u32| u16::from_be((v & 0xffff) as u16);
        if family == AF_INET as u32 {
            // MIB_TCPROW_OWNER_PID: state, laddr, lport, raddr, rport, pid (6 x u32)
            for i in 0..n {
                let o = 4 + i * 24;
                let Some(r) = b.get(o..o + 24) else { break };
                let f = |k: usize| u32::from_le_bytes(r[k * 4..k * 4 + 4].try_into().unwrap());
                out.push(Sock {
                    proto: Proto::Tcp, state: state(f(0)),
                    local: IpAddr::V4(Ipv4Addr::from(u32::from_be(f(1)))), lport: port(f(2)),
                    remote: IpAddr::V4(Ipv4Addr::from(u32::from_be(f(3)))), rport: port(f(4)),
                    uid: 0, inode: 0, pid: f(5), bytes_sent: 0, bytes_recv: 0,
                });
            }
        } else {
            // MIB_TCP6ROW_OWNER_PID: laddr[16], lscope, lport, raddr[16], rscope, rport, state, pid = 56 bytes
            for i in 0..n {
                let o = 4 + i * 56;
                let Some(r) = b.get(o..o + 56) else { break };
                let u = |k: usize| u32::from_le_bytes(r[k..k + 4].try_into().unwrap());
                let a6 = |k: usize| {
                    let v = Ipv6Addr::from(<[u8; 16]>::try_from(&r[k..k + 16]).unwrap());
                    v.to_ipv4_mapped().map(IpAddr::V4).unwrap_or(IpAddr::V6(v))
                };
                out.push(Sock {
                    proto: Proto::Tcp, state: state(u(48)),
                    local: a6(0), lport: port(u(20)), remote: a6(24), rport: port(u(44)),
                    uid: 0, inode: 0, pid: u(52), bytes_sent: 0, bytes_recv: 0,
                });
            }
        }
        Ok(())
    }
}

/// MIB_TCP_STATE -> Linux numbering used by the rest of the agent.
fn state(s: u32) -> u8 {
    match s {
        1 => 7,   // CLOSED
        2 => 10,  // LISTEN
        3 => 2,   // SYN_SENT
        4 => 3,   // SYN_RCVD
        5 => 1,   // ESTABLISHED
        6 => 4,   // FIN_WAIT1
        7 => 5,   // FIN_WAIT2
        8 => 8,   // CLOSE_WAIT
        9 => 11,  // CLOSING
        10 => 9,  // LAST_ACK
        11 => 6,  // TIME_WAIT
        _ => 0,
    }
}
