//! WhoSees Android engine.
//!
//! Android's VpnService gives us a tun file descriptor carrying every packet apps send. A small
//! userspace TCP/IP stack (ipstack) turns those packets back into connections, which we forward
//! over real sockets (our own app is excluded from the VPN, so nothing loops). While forwarding we
//! read only what the desktop agent reads (addresses, DNS answers, the TLS/HTTP website name) and
//! emit the same JSON events, so the shared UI, threat checks and blocking all work unchanged.
//! Nothing leaves the phone except the apps' own traffic, exactly where it was going.

#[allow(dead_code)]
#[path = "../../../desktop/agent/src/sock.rs"] mod sock;
#[path = "../../../desktop/agent/src/geo.rs"] mod geo;
#[path = "../../../desktop/agent/src/hosts.rs"] mod hosts;
#[path = "../../../desktop/agent/src/classify.rs"] mod classify;
#[path = "../../../desktop/agent/src/threats.rs"] mod threats;
#[allow(dead_code)]
#[path = "../../../desktop/agent/src/datatypes.rs"] mod datatypes;
#[allow(dead_code)]
#[path = "../../../desktop/agent/src/sniff.rs"] mod sniff;
mod diag { pub use crate::sock::Proto; } // classify.rs refers to crate::diag::Proto

pub mod engine;
mod jni_glue;

pub use engine::{Config, Engine};
