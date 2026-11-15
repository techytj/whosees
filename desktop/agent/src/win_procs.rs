//! Windows: process id -> friendly app name (from the exe's version info) and exe path.
//! The UI turns the exe path into an icon (Electron's app.getFileIcon).

use serde::Serialize;
use std::collections::HashMap;
use std::os::windows::ffi::OsStringExt;
use windows_sys::Win32::Foundation::{CloseHandle, GetLastError, ERROR_INVALID_PARAMETER};
use windows_sys::Win32::Storage::FileSystem::{GetFileVersionInfoSizeW, GetFileVersionInfoW, QueryDosDeviceW, VerQueryValueW};
use windows_sys::Win32::System::Threading::{OpenProcess, QueryFullProcessImageNameW, PROCESS_QUERY_LIMITED_INFORMATION};

#[derive(Clone, Debug, Serialize)]
pub struct AppInfo {
    pub id: String,
    pub name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub icon: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub exe: Option<String>,
    pub system: bool,
}

pub struct Procs { by_pid: HashMap<u32, AppInfo>, names: HashMap<String, String> }

impl Procs {
    pub fn new() -> Procs { Procs { by_pid: HashMap::new(), names: HashMap::new() } }

    pub fn app_for_sock(&mut self, s: &crate::sock::Sock) -> AppInfo {
        if let Some(a) = self.by_pid.get(&s.pid) { return a.clone(); }
        let a = self.identify(s.pid);
        // Only remember real answers: a "program started" event can still arrive and name it.
        if a.exe.is_some() || a.id == "system" {
            if self.by_pid.len() > 4096 { self.by_pid.clear(); }
            self.by_pid.insert(s.pid, a.clone());
        }
        a
    }

    fn identify(&mut self, pid: u32) -> AppInfo {
        if pid == 0 || pid == 4 {
            return AppInfo { id: "system".into(), name: "Windows".into(), icon: None, exe: None, system: true };
        }
        let Some(exe) = exe_path(pid).or_else(|| remembered(pid)) else {
            // Still running but hidden from us: a protected Windows service (needs admin to see which).
            // Already gone: a program that ran for a moment (don't call it a Windows service).
            if gone(pid) {
                return AppInfo { id: format!("pid:{pid}"), name: "Short-lived program".into(), icon: None, exe: None, system: false };
            }
            return AppInfo { id: format!("pid:{pid}"), name: "Windows service".into(), icon: None, exe: None, system: true };
        };
        let lower = exe.to_lowercase();
        let system = lower.starts_with("c:\\windows\\");
        let name = match self.names.get(&lower) {
            Some(n) => n.clone(),
            None => {
                let n = describe(&exe).unwrap_or_else(|| {
                    let f = exe.rsplit('\\').next().unwrap_or(&exe);
                    f.trim_end_matches(".exe").trim_end_matches(".EXE").to_string()
                });
                self.names.insert(lower.clone(), n.clone());
                n
            }
        };
        let name = if lower.ends_with("\\svchost.exe") { "Windows service host".into() } else { name };
        AppInfo { id: format!("exe:{lower}"), name, icon: None, exe: Some(exe), system }
    }
}

/// pid -> exe path, captured by the ETW thread while the process is still alive
/// (short-lived programs like curl exit before the main loop gets to them).
static SEEN: std::sync::Mutex<Option<HashMap<u32, String>>> = std::sync::Mutex::new(None);

pub fn remember(pid: u32) {
    if pid <= 4 { return; }
    let Ok(mut g) = SEEN.lock() else { return };
    let m = g.get_or_insert_with(HashMap::new);
    if m.contains_key(&pid) { return; }
    if let Some(p) = exe_path(pid) {
        if m.len() > 8192 { m.clear(); }
        m.insert(pid, p);
    }
}

/// Exe path of a running (or recently seen) process.
pub fn exe_of(pid: u32) -> Option<String> { exe_path(pid).or_else(|| remembered(pid)) }

fn remembered(pid: u32) -> Option<String> { SEEN.lock().ok()?.as_ref()?.get(&pid).cloned() }

/// From the "program started" event (Deep mode): pid -> exe, even for programs that exit at once.
/// `image` is a kernel path like \Device\HarddiskVolume3\Windows\System32\curl.exe.
pub fn remember_start(pid: u32, image: &str) {
    if pid <= 4 || image.is_empty() { return; }
    let path = nt_to_dos(image);
    let Ok(mut g) = SEEN.lock() else { return };
    let m = g.get_or_insert_with(HashMap::new);
    if m.len() > 8192 { m.clear(); }
    m.insert(pid, path); // pids are reused: the newest start wins
}

/// \Device\HarddiskVolumeN\... -> C:\... using the drive letter mapping.
fn nt_to_dos(p: &str) -> String {
    static MAP: std::sync::OnceLock<Vec<(String, String)>> = std::sync::OnceLock::new();
    let map = MAP.get_or_init(|| {
        let mut v = Vec::new();
        for l in b'A'..=b'Z' {
            let drive = format!("{}:", l as char);
            let mut buf = [0u16; 512];
            let n = unsafe { QueryDosDeviceW(wide(&drive).as_ptr(), buf.as_mut_ptr(), buf.len() as u32) };
            if n == 0 { continue; }
            let end = buf.iter().position(|&c| c == 0).unwrap_or(0);
            v.push((String::from_utf16_lossy(&buf[..end]), drive));
        }
        v
    });
    for (dev, drive) in map {
        if p.len() > dev.len() && p[..dev.len()].eq_ignore_ascii_case(dev) && p.as_bytes()[dev.len()] == b'\\' {
            return format!("{drive}{}", &p[dev.len()..]);
        }
    }
    p.to_string()
}

/// True if the process has exited (OpenProcess says the pid doesn't exist, rather than "access denied").
fn gone(pid: u32) -> bool {
    unsafe {
        let h = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid);
        if !h.is_null() { CloseHandle(h); return false; }
        GetLastError() == ERROR_INVALID_PARAMETER
    }
}

fn wide(s: &str) -> Vec<u16> { s.encode_utf16().chain(std::iter::once(0)).collect() }

fn exe_path(pid: u32) -> Option<String> {
    unsafe {
        let h = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid);
        if h.is_null() { return None; }
        let mut buf = [0u16; 1024];
        let mut len = buf.len() as u32;
        let ok = QueryFullProcessImageNameW(h, 0, buf.as_mut_ptr(), &mut len);
        CloseHandle(h);
        if ok == 0 { return None; }
        Some(std::ffi::OsString::from_wide(&buf[..len as usize]).to_string_lossy().into_owned())
    }
}

/// FileDescription from the exe's version resource ("Google Chrome", "Microsoft Edge").
fn describe(exe: &str) -> Option<String> {
    unsafe {
        let w = wide(exe);
        let size = GetFileVersionInfoSizeW(w.as_ptr(), std::ptr::null_mut());
        if size == 0 { return None; }
        let mut data = vec![0u8; size as usize];
        if GetFileVersionInfoW(w.as_ptr(), 0, size, data.as_mut_ptr() as *mut _) == 0 { return None; }
        // first language/codepage pair
        let mut p: *mut core::ffi::c_void = std::ptr::null_mut();
        let mut l = 0u32;
        let t = wide("\\VarFileInfo\\Translation");
        if VerQueryValueW(data.as_ptr() as *const _, t.as_ptr(), &mut p, &mut l) == 0 || l < 4 { return None; }
        let lang = *(p as *const u16);
        let cp = *(p as *const u16).add(1);
        for key in ["FileDescription", "ProductName"] {
            let q = wide(&format!("\\StringFileInfo\\{lang:04x}{cp:04x}\\{key}"));
            let mut sp: *mut core::ffi::c_void = std::ptr::null_mut();
            let mut sl = 0u32;
            if VerQueryValueW(data.as_ptr() as *const _, q.as_ptr(), &mut sp, &mut sl) != 0 && sl > 1 {
                let s = std::slice::from_raw_parts(sp as *const u16, sl as usize - 1);
                let s = String::from_utf16_lossy(s).trim().to_string();
                if !s.is_empty() { return Some(s); }
            }
        }
        None
    }
}
