//! Socket types shared by the Linux and Windows backends.

use std::net::IpAddr;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Proto { Tcp, Udp }

#[derive(Clone, Debug)]
#[allow(dead_code)] // some fields are only used by one platform's backend
pub struct Sock {
    pub proto: Proto,
    pub state: u8,
    pub local: IpAddr,
    pub lport: u16,
    pub remote: IpAddr,
    pub rport: u16,
    pub uid: u32,
    pub inode: u64,
    /// owning process (Windows reports it directly; Linux resolves it from the inode)
    #[allow(dead_code)] // read by the Windows backend
    pub pid: u32,
    pub bytes_sent: u64,
    pub bytes_recv: u64,
}

/// Linux numbering; the Windows backend maps its states onto these.
pub const TCP_LISTEN: u8 = 10;
pub const TCP_TIME_WAIT: u8 = 6;
pub const TCP_CLOSE: u8 = 7;
