//! Map sockets to processes and processes to friendly app names + icons (Linux).

use serde::Serialize;
use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

#[derive(Clone, Debug, Serialize)]
pub struct AppInfo {
    /// Stable key used by the UI to group connections ("org.mozilla.firefox", "exe:/usr/bin/curl", "uid:0").
    pub id: String,
    pub name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub icon: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub exe: Option<String>,
    pub system: bool,
}

#[derive(Clone)]
struct Desktop { id: String, name: String, icon: Option<String> }

pub struct Procs {
    inode_pid: HashMap<u64, u32>,
    last_scan: Instant,
    apps: HashMap<u32, AppInfo>,        // pid -> app
    by_exec: HashMap<String, Desktop>,  // exe basename / desktop id / wmclass (lowercase) -> desktop entry
    users: HashMap<u32, String>,
    icon_cache: HashMap<String, Option<String>>,
}

impl Procs {
    pub fn new() -> Procs {
        let mut p = Procs {
            inode_pid: HashMap::new(),
            last_scan: Instant::now() - Duration::from_secs(10),
            apps: HashMap::new(),
            by_exec: HashMap::new(),
            users: read_passwd(),
            icon_cache: HashMap::new(),
        };
        p.index_desktop_files();
        p
    }

    /// Resolve the app owning socket `inode`. Rescans /proc at most every 400 ms.
    pub fn app_for_sock(&mut self, s: &crate::sock::Sock) -> AppInfo { self.app_for(s.inode, s.uid) }

    pub fn app_for(&mut self, inode: u64, uid: u32) -> AppInfo {
        if inode != 0 && !self.inode_pid.contains_key(&inode) && self.last_scan.elapsed() > Duration::from_millis(400) {
            self.scan_fds();
        }
        if let Some(&pid) = self.inode_pid.get(&inode) {
            if let Some(a) = self.apps.get(&pid) { return a.clone(); }
            let a = self.identify(pid, uid);
            self.apps.insert(pid, a.clone());
            return a;
        }
        self.system_app(uid)
    }

    fn system_app(&self, uid: u32) -> AppInfo {
        let user = self.users.get(&uid).cloned().unwrap_or_else(|| uid.to_string());
        // Socket with no visible owner: a root/system service, or a program that already exited.
        if uid >= 1000 && uid != 65534 {
            return AppInfo { id: format!("uid:{uid}"), name: "Short-lived program".into(), icon: None, exe: None, system: false };
        }
        let name = if uid == 0 { "System".to_string() } else { format!("System service ({user})") };
        AppInfo { id: format!("uid:{uid}"), name, icon: None, exe: None, system: true }
    }

    fn scan_fds(&mut self) {
        self.last_scan = Instant::now();
        self.inode_pid.clear();
        let Ok(rd) = fs::read_dir("/proc") else { return };
        for e in rd.flatten() {
            let Some(pid) = e.file_name().to_str().and_then(|s| s.parse::<u32>().ok()) else { continue };
            let Ok(fds) = fs::read_dir(format!("/proc/{pid}/fd")) else { continue };
            for fd in fds.flatten() {
                if let Ok(t) = fs::read_link(fd.path()) {
                    let t = t.to_string_lossy();
                    if let Some(n) = t.strip_prefix("socket:[").and_then(|s| s.strip_suffix(']')) {
                        if let Ok(n) = n.parse() { self.inode_pid.entry(n).or_insert(pid); }
                    }
                }
            }
        }
        // forget pids that are gone
        self.apps.retain(|pid, _| Path::new(&format!("/proc/{pid}")).exists());
    }

    fn identify(&mut self, pid: u32, uid: u32) -> AppInfo {
        let exe = fs::read_link(format!("/proc/{pid}/exe")).ok().map(|p| p.to_string_lossy().into_owned());
        let comm = fs::read_to_string(format!("/proc/{pid}/comm")).unwrap_or_default().trim().to_string();

        // 1. Flatpak: everything inside the sandbox belongs to the app.
        if let Some((id, flatpak)) = cgroup_app_id(pid) {
            if flatpak {
                if let Some(d) = self.lookup(&id) { return self.from_desktop(d, exe); }
            }
        }
        // 2. The process itself, then parents that live in the same install folder
        //    (browser helpers, renderers). A CLI tool started from a terminal keeps its own name.
        let exe_dir = exe.as_ref().and_then(|e| Path::new(e).parent().map(|p| p.to_path_buf()));
        let mut cur = pid;
        for depth in 0..8 {
            let e = fs::read_link(format!("/proc/{cur}/exe")).ok();
            if depth > 0 && e.as_ref().and_then(|p| p.parent()) != exe_dir.as_deref() { break; }
            let c = fs::read_to_string(format!("/proc/{cur}/comm")).unwrap_or_default();
            let keys = [
                e.as_ref().and_then(|p| p.file_name()).map(|s| s.to_string_lossy().into_owned()),
                Some(c.trim().to_string()),
            ];
            for k in keys.into_iter().flatten() {
                if let Some(d) = self.lookup(&k) { return self.from_desktop(d, exe); }
            }
            if let Some(dir) = e.as_ref().and_then(|p| p.parent()) {
                let mut d = dir.to_path_buf();
                for _ in 0..3 { // also try parent folders: /opt/app/bin/x -> /opt/app
                    if let Some(hit) = self.by_exec.get(&format!("dir:{}", d.to_string_lossy()).to_lowercase()).cloned() {
                        return self.from_desktop(hit, exe);
                    }
                    if !d.pop() || d.as_os_str().len() <= 5 { break; }
                }
            }
            match parent(cur) { Some(p) if p > 1 => cur = p, _ => break }
        }
        // 3. Plain process.
        let user = self.users.get(&uid).cloned();
        let system = uid == 0 || uid < 1000;
        let name = pretty(&argv0(pid).unwrap_or_else(|| comm.clone()));
        let id = exe.as_ref().map(|e| format!("exe:{e}")).unwrap_or_else(|| format!("comm:{comm}"));
        let name = if system && uid != 0 { format!("{name} ({})", user.unwrap_or_default()) } else { name };
        AppInfo { id, name, icon: None, exe, system }
    }

    fn from_desktop(&mut self, d: Desktop, exe: Option<String>) -> AppInfo {
        let icon = d.icon.as_ref().and_then(|i| self.resolve_icon(i));
        AppInfo { id: d.id, name: d.name, icon, exe, system: false }
    }

    fn lookup(&self, key: &str) -> Option<Desktop> {
        let k = key.to_lowercase();
        self.by_exec.get(&k).cloned()
            .or_else(|| k.rsplit('.').next().and_then(|tail| self.by_exec.get(tail).cloned()))
    }

    fn index_desktop_files(&mut self) {
        let home = crate::home();
        let mut dirs: Vec<PathBuf> = vec![
            format!("{home}/.local/share/flatpak/exports/share/applications").into(),
            "/var/lib/flatpak/exports/share/applications".into(),
            "/usr/local/share/applications".into(),
            "/usr/share/applications".into(),
            format!("{home}/.local/share/applications").into(), // last = highest priority
        ];
        if let Ok(x) = std::env::var("XDG_DATA_DIRS") {
            for d in x.split(':').rev() { dirs.insert(0, Path::new(d).join("applications")); }
        }
        for dir in dirs {
            let Ok(rd) = fs::read_dir(&dir) else { continue };
            for e in rd.flatten() {
                let p = e.path();
                if p.extension().and_then(|s| s.to_str()) != Some("desktop") { continue; }
                let Ok(text) = fs::read_to_string(&p) else { continue };
                let id = p.file_stem().unwrap().to_string_lossy().into_owned();
                if let Some((d, keys)) = parse_desktop(&id, &text) {
                    for k in keys { self.by_exec.insert(k.to_lowercase(), d.clone()); }
                    self.by_exec.insert(id.to_lowercase(), d);
                }
            }
        }
    }

    fn resolve_icon(&mut self, name: &str) -> Option<String> {
        if let Some(c) = self.icon_cache.get(name) { return c.clone(); }
        let r = find_icon(name);
        self.icon_cache.insert(name.to_string(), r.clone());
        r
    }
}

fn parse_desktop(id: &str, text: &str) -> Option<(Desktop, Vec<String>)> {
    let mut in_entry = false;
    let (mut name, mut icon, mut exec, mut wm, mut nodisplay, mut typ) = (None, None, None, None, false, None);
    for line in text.lines() {
        let line = line.trim();
        if line.starts_with('[') { in_entry = line == "[Desktop Entry]"; continue; }
        if !in_entry { continue; }
        let Some((k, v)) = line.split_once('=') else { continue };
        match k.trim() {
            "Name" => name = Some(v.trim().to_string()),
            "Icon" => icon = Some(v.trim().to_string()),
            "Exec" => exec = Some(v.trim().to_string()),
            "StartupWMClass" => wm = Some(v.trim().to_string()),
            "NoDisplay" => nodisplay = v.trim() == "true",
            "Type" => typ = Some(v.trim().to_string()),
            _ => {}
        }
    }
    if typ.as_deref() != Some("Application") { return None; }
    let name = name?;
    let mut keys = Vec::new();
    if let Some(e) = exec {
        let toks: Vec<&str> = e.split_whitespace().filter(|t| !t.contains('=') && *t != "env").collect();
        if let Some(first) = toks.first() {
            let base = first.rsplit('/').next().unwrap_or(first).trim_matches('"');
            if base == "flatpak" {
                if let Some(app) = toks.iter().rev().find(|t| t.contains('.') && !t.starts_with('-') && !t.starts_with('@')) {
                    keys.push(app.to_string());
                }
            } else if !nodisplay {
                keys.push(base.to_string());
                // Also key on the real install folder: /usr/bin/brave-browser-stable -> /opt/brave.com/brave
                if let Some(dir) = install_dir(first.trim_matches('"')) { keys.push(format!("dir:{dir}")); }
            }
        }
    }
    if let Some(w) = wm { if !nodisplay { keys.push(w); } }
    Some((Desktop { id: id.to_string(), name, icon }, keys))
}

/// Resolve an Exec program to the folder it is really installed in, skipping generic bin folders.
fn install_dir(prog: &str) -> Option<String> {
    let path = if prog.contains('/') { PathBuf::from(prog) } else {
        std::env::var("PATH").ok()?.split(':').map(|d| Path::new(d).join(prog)).find(|p| p.exists())?
    };
    let real = fs::canonicalize(&path).ok()?;
    let mut dir = real.parent()?.to_path_buf();
    // Wrapper shell script? Look for an absolute path inside it that points elsewhere.
    if let Ok(text) = fs::read_to_string(&real) {
        if text.starts_with("#!") && text.len() < 64 * 1024 {
            if let Some(tok) = text.split(|c: char| c.is_whitespace() || c == '"' || c == '\'' || c == '=')
                .find(|t| t.starts_with("/opt/") || t.starts_with("/usr/lib/") || t.starts_with("/usr/lib64/") || t.starts_with("/usr/share/")) {
                if let Some(p) = Path::new(tok).parent() { dir = p.to_path_buf(); }
            }
        }
    }
    let d = dir.to_string_lossy().into_owned();
    const GENERIC: &[&str] = &["/usr/bin", "/bin", "/usr/sbin", "/sbin", "/usr/local/bin", "/usr/libexec", "/usr/lib", "/usr/lib64"];
    if GENERIC.contains(&d.as_str()) { None } else { Some(d) }
}

fn find_icon(name: &str) -> Option<String> {
    if name.starts_with('/') { return Path::new(name).exists().then(|| name.to_string()); }
    let home = crate::home();
    let bases = [
        format!("{home}/.local/share/icons"),
        format!("{home}/.local/share/flatpak/exports/share/icons"),
        "/var/lib/flatpak/exports/share/icons".to_string(),
        "/usr/share/icons".to_string(),
    ];
    let themes = ["hicolor", "breeze", "Adwaita"];
    let sizes = ["256x256", "128x128", "scalable", "512x512", "96x96", "64x64", "48x48"];
    for b in &bases {
        for t in themes {
            for s in sizes {
                for ext in ["png", "svg"] {
                    let p = format!("{b}/{t}/{s}/apps/{name}.{ext}");
                    if Path::new(&p).exists() { return Some(p); }
                }
            }
        }
    }
    for ext in ["png", "svg", "xpm"] {
        let p = format!("/usr/share/pixmaps/{name}.{ext}");
        if Path::new(&p).exists() { return Some(p); }
    }
    None
}

/// (app id, is_flatpak) from the systemd scope in /proc/PID/cgroup.
fn cgroup_app_id(pid: u32) -> Option<(String, bool)> {
    let cg = fs::read_to_string(format!("/proc/{pid}/cgroup")).ok()?;
    for seg in cg.lines().flat_map(|l| l.rsplit(':').next()).flat_map(|p| p.split('/')).rev() {
        let s = seg.replace("\\x2d", "-");
        let Some(rest) = s.strip_prefix("app-") else { continue };
        let rest = rest.trim_end_matches(".scope").trim_end_matches(".service");
        let rest = rest.split('@').next().unwrap_or(rest);
        let flatpak = rest.starts_with("flatpak-");
        let rest = rest.strip_prefix("flatpak-").or_else(|| rest.strip_prefix("gnome-"))
            .or_else(|| rest.strip_prefix("kde-")).unwrap_or(rest);
        // strip trailing -<number>
        let id = match rest.rsplit_once('-') {
            Some((a, n)) if n.chars().all(|c| c.is_ascii_digit()) => a,
            _ => rest,
        };
        if !id.is_empty() { return Some((id.to_string(), flatpak)); }
    }
    None
}

/// Program name as launched (argv[0] basename) - comm is truncated and can be a version number.
fn argv0(pid: u32) -> Option<String> {
    let c = fs::read(format!("/proc/{pid}/cmdline")).ok()?;
    let a0 = String::from_utf8_lossy(c.split(|&b| b == 0).next()?).into_owned();
    let a0 = a0.split_whitespace().next()?.to_string();
    // Skip version-number / generic path parts: ~/.local/share/claude/versions/2.1.3 -> "claude"
    let generic = |p: &str| p.is_empty() || p == "bin" || p == "versions" || p == "current"
        || p.chars().all(|c| c.is_ascii_digit() || c == '.' || c == '-');
    let base = a0.rsplit('/').find(|p| !generic(p))?.trim_start_matches('-').to_string();
    (!base.is_empty()).then_some(base)
}

fn parent(pid: u32) -> Option<u32> {
    let s = fs::read_to_string(format!("/proc/{pid}/stat")).ok()?;
    let after = &s[s.rfind(')')? + 2..];
    after.split_whitespace().nth(1)?.parse().ok()
}

fn read_passwd() -> HashMap<u32, String> {
    fs::read_to_string("/etc/passwd").unwrap_or_default().lines().filter_map(|l| {
        let f: Vec<&str> = l.split(':').collect();
        Some((f.get(2)?.parse().ok()?, f[0].to_string()))
    }).collect()
}

fn pretty(comm: &str) -> String {
    let mut c = comm.chars();
    match c.next() { Some(f) => f.to_uppercase().collect::<String>() + c.as_str(), None => "Unknown".into() }
}
