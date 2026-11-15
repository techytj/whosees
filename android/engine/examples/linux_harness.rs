//! Test harness: run the Android engine on Linux against a tun device (inside tests/sandbox/net.sh).
//! Usage: linux_harness TUN_NAME CONFIG_JSON   - prints engine events (JSON) on stdout, reads commands on stdin.
use std::io::{BufRead, Write};
use std::sync::Arc;

fn open_tun(name: &str) -> i32 {
    const TUNSETIFF: libc::c_ulong = 0x400454ca;
    let fd = unsafe { libc::open(b"/dev/net/tun\0".as_ptr() as *const _, libc::O_RDWR) };
    assert!(fd >= 0, "open /dev/net/tun");
    let mut ifr = [0u8; 40];
    ifr[..name.len()].copy_from_slice(name.as_bytes());
    let flags: i16 = 0x0001 | 0x1000; // IFF_TUN | IFF_NO_PI
    ifr[16..18].copy_from_slice(&flags.to_ne_bytes());
    assert!(unsafe { libc::ioctl(fd, TUNSETIFF as _, ifr.as_mut_ptr()) } >= 0, "TUNSETIFF");
    fd
}

fn main() {
    let a: Vec<String> = std::env::args().collect();
    let fd = open_tun(&a[1]);
    println!("{{\"t\":\"harness\",\"tun\":\"ready\"}}"); std::io::stdout().flush().unwrap();
    let cfg: wtengine::Config = serde_json::from_str(&a[2]).unwrap();
    let owner: wtengine::engine::Owner = Arc::new(|_, _, _| wtengine::engine::AppInfo { id: "uid:10123".into(), name: "Test App".into(), icon: None, system: false, uid: 10123, perms: vec!["location".into()] });
    let e = Arc::new(wtengine::Engine::start(fd, cfg, owner).unwrap());
    let e2 = e.clone();
    std::thread::spawn(move || { for l in std::io::stdin().lock().lines().map_while(Result::ok) { e2.command(&l); } std::process::exit(0); });
    loop {
        let s = e.poll();
        if s != "[]" { for v in serde_json::from_str::<Vec<serde_json::Value>>(&s).unwrap() { println!("{v}"); } std::io::stdout().flush().unwrap(); }
        std::thread::sleep(std::time::Duration::from_millis(100));
    }
}
