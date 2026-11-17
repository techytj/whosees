// WhoSees - Electron main process.
// Owns the window, the capture agent process, and read-only access to bundled data.
'use strict';

const { app, BrowserWindow, ipcMain, protocol, net, nativeTheme, shell, session, dialog } = require('electron');
const { spawn, execFile } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const readline = require('node:readline');
const { pathToFileURL } = require('node:url');

const DEV = !app.isPackaged;
const ROOT = __dirname;
const RES = DEV ? path.resolve(ROOT, '..', '..') : process.resourcesPath;
const SHARED = path.join(RES, 'shared');
const AGENT = DEV
  ? path.resolve(ROOT, '..', 'agent', 'target', 'release', process.platform === 'win32' ? 'whosees-agent.exe' : 'whosees-agent')
  : path.join(RES, 'agent', process.platform === 'win32' ? 'whosees-agent.exe' : 'whosees-agent');
const GEO = path.join(SHARED, 'geo', 'world.wtgeo');
const TILES = path.join(SHARED, 'map', 'world-z6.pmtiles');
const CATS = path.join(SHARED, 'categories', 'domains.json');
const THREATS = (DEV && process.env.WT_THREATS_DIR) || path.join(SHARED, 'threats'); // tests use their own lists

// Quieter Chromium on Linux/Wayland (harmless GPU/Vulkan warnings).
app.commandLine.appendSwitch('log-level', '3');
app.commandLine.appendSwitch('disable-features', 'Vulkan');

protocol.registerSchemesAsPrivileged([
  { scheme: 'wt', privileges: { standard: true, secure: true, supportFetchAPI: true, corsEnabled: true, stream: true } },
]);

// ---------- settings ----------
// The app was renamed (Wiretrace -> WhoSees): carry earlier settings over once.
function migrateSettings() {
  try {
    const now = path.join(app.getPath('userData'), 'settings.json');
    if (fs.existsSync(now)) return;
    for (const old of ['Wiretrace', 'Tattle']) {
      const f = path.join(app.getPath('appData'), old, 'settings.json');
      if (fs.existsSync(f)) { fs.mkdirSync(path.dirname(now), { recursive: true }); fs.copyFileSync(f, now); return; }
    }
  } catch {}
}
const settingsFile = () => path.join(app.getPath('userData'), 'settings.json');
function loadSettings() {
  try { return JSON.parse(fs.readFileSync(settingsFile(), 'utf8')); } catch { return {}; }
}
function saveSettings(s) {
  fs.mkdirSync(path.dirname(settingsFile()), { recursive: true });
  fs.writeFileSync(settingsFile(), JSON.stringify(s, null, 2));
}

// ---------- window ----------
const devSize = () => (DEV && /^\d+x\d+$/.test(process.env.WT_SIZE || '') ? process.env.WT_SIZE.split('x').map(Number) : [1400, 880]);
let win = null;
function createWindow() {
  const dark = nativeTheme.shouldUseDarkColors;
  win = new BrowserWindow({
    width: devSize()[0], height: devSize()[1], minWidth: 360, minHeight: 560,
    backgroundColor: dark ? '#0a0b0d' : '#eeece7',
    title: 'WhoSees',
    icon: path.join(ROOT, 'build', 'icon.png'),
    titleBarStyle: 'hidden',
    titleBarOverlay: { color: '#00000000', symbolColor: dark ? '#c9d2e3' : '#2a3242', height: 48 },
    show: false,
    webPreferences: {
      preload: path.join(ROOT, 'preload.js'),
      contextIsolation: true, sandbox: true, nodeIntegration: false, spellcheck: false,
    },
  });
  win.once('ready-to-show', () => win.show());
  // Renderer console -> log file (diagnostics)
  const logFile = path.join(app.getPath('userData'), 'wiretrace.log');
  try { fs.writeFileSync(logFile, `--- start ${new Date().toISOString()} scale=${require('electron').screen.getPrimaryDisplay().scaleFactor}\n`); } catch {}
  win.webContents.on('console-message', (e) => { try { fs.appendFileSync(logFile, `${e.message}\n`); } catch {} });
  // Dev-only: WT_SHOT=/path/prefix captures screenshots (used for automated visual checks).
  if (DEV && process.env.WT_SHOT) devScreenshots(win, process.env.WT_SHOT);
  win.loadURL('wt://app/renderer/index.html');
  // Links open in the real browser, never inside the app.
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https:\/\//.test(url)) shell.openExternal(url);
    return { action: 'deny' };
  });
  win.webContents.on('will-navigate', (e, url) => { if (!url.startsWith('wt://')) e.preventDefault(); });
  win.on('closed', () => { win = null; stopAgent(); });
}

ipcMain.handle('win:theme', (_e, mode) => {
  nativeTheme.themeSource = mode; // 'system' | 'dark' | 'light'
  const dark = nativeTheme.shouldUseDarkColors;
  try { win?.setTitleBarOverlay({ color: '#00000000', symbolColor: dark ? '#c9d2e3' : '#2a3242', height: 48 }); } catch {}
  return dark;
});

// ---------- static files: wt://app/... and wt://shared/... ----------
function resolveWt(url) {
  const u = new URL(url);
  const rel = decodeURIComponent(u.pathname).replace(/^\/+/, '');
  const base = u.host === 'shared' ? SHARED : u.host === 'app' ? ROOT : null;
  if (!base) return null;
  const p = path.resolve(base, rel);
  return p.startsWith(base + path.sep) ? p : null; // no escaping the root
}

const MIME = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8', '.json': 'application/json', '.map': 'application/json', '.svg': 'image/svg+xml',
  '.png': 'image/png', '.woff2': 'font/woff2', '.pbf': 'application/x-protobuf',
};

// ---------- capture agent ----------
let agent = null;
let queue = [];
let flushTimer = null;

function send(ch, data) { if (win && !win.isDestroyed()) win.webContents.send(ch, data); }

// The running agent, whatever transport it uses: { send(line), end(), kill() }.
// Linux/Standard: a child process with pipes. Windows Deep: an elevated process that connects
// back over a local socket (a UAC-elevated process can't inherit our pipes).
function startAgent(opts = {}) {
  if (agent) return { ok: true, already: true };
  if (!fs.existsSync(AGENT)) return { ok: false, error: `Capture agent not found at ${AGENT}` };
  // --self-exe: WhoSees's own traffic (an update check, if turned on) is shown as WhoSees and never flagged as a threat
  const args = ['--geo', GEO, '--categories', CATS, '--threats', THREATS, '--interval', String(opts.interval || 250), '--self-exe', process.execPath, '--blocking'];
  if (opts.lan) args.push('--lan');
  const deep = !!opts.deep && (process.platform === 'linux' || process.platform === 'win32');
  const direct = DEV && process.env.WT_DEEP_DIRECT === '1'; // dev/test: already privileged
  if (deep && process.platform === 'win32' && !direct) return startElevatedWindows(args, opts);

  // Deep mode on Linux: ask once via the system password prompt (polkit). The UI never runs as admin.
  let agentPath = AGENT;
  if (deep) {
    args.push('--deep', '--home', app.getPath('home'));
    // Opt-in payload reading (off by default): read the kinds of data apps send
    // over TLS. In memory only, kinds not bodies. Only ever with Deep mode.
    if (opts.readPayloads) args.push('--read-payloads');
    // An AppImage runs from a private FUSE mount that root can't read: stage the agent + data in ~/.cache.
    if (process.env.APPIMAGE) {
      const staged = stageForRoot();
      agentPath = staged.agent;
      for (const [flag, file] of [['--geo', staged.geo], ['--categories', staged.cats], ['--threats', staged.threats]]) args[args.indexOf(flag) + 1] = file;
    }
  }
  const child = deep && !direct
    ? spawn('pkexec', [agentPath, ...args], { stdio: ['pipe', 'pipe', 'pipe'] })
    : spawn(AGENT, args, { stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true });
  const link = {
    send: (l) => { try { child.stdin.write(l); } catch {} },
    end: () => { try { child.stdin.end(); } catch {} },
    kill: () => { try { child.kill(); } catch {} },
  };
  agent = link;
  const stderrTail = [];
  readline.createInterface({ input: child.stderr }).on('line', (l) => {
    console.error('[agent]', l);
    stderrTail.push(l); if (stderrTail.length > 5) stderrTail.shift();
  });
  const hello = wireEvents(child.stdout);
  child.on('exit', (code, sig) => {
    // pkexec: 126 = password window closed / password not accepted, 127 = not allowed or failed to run.
    agentEnded(link, deep && !hello.said, { code, sig, detail: stderrTail.join('\n') }, opts);
  });
  child.on('error', (err) => send('agent:events', [{ t: 'error', msg: String(err.message || err) }]));
  return { ok: true };
}

function wireEvents(stream) {
  const state = { said: false };
  readline.createInterface({ input: stream }).on('line', (line) => {
    let ev; try { ev = JSON.parse(line); } catch { return; }
    if (ev.t === 'hello') state.said = true;
    queue.push(ev);
    if (!flushTimer) flushTimer = setTimeout(() => { flushTimer = null; const q = queue; queue = []; send('agent:events', q); }, 60);
  });
  return state;
}

/** Agent went away. If Deep mode never got going, say why and carry on in Standard mode. */
function agentEnded(link, deepFailed, info, opts) {
  const mine = agent === link;
  if (mine) agent = null;
  if (deepFailed && mine) {
    send('agent:events', [{ t: 'deepfail', code: info.code, detail: String(info.detail || '').slice(-400) }]);
    const r = startAgent({ ...opts, deep: false });
    if (r.ok) return;
  }
  send('agent:exit', { code: info.code, sig: info.sig });
}

// Windows: start the agent elevated through the UAC prompt; it connects back to a socket on
// 127.0.0.1 and proves itself with a one-time token before we trust anything it says.
function startElevatedWindows(args, opts) {
  const net = require('node:net');
  const token = require('node:crypto').randomBytes(24).toString('hex');
  const server = net.createServer();
  const link = { sock: null, send: (l) => { try { link.sock?.write(l); } catch {} }, end: () => { try { link.sock?.end(); } catch {} }, kill: () => { try { link.sock?.destroy(); } catch {} try { server.close(); } catch {} }, pending: true };
  agent = link;
  let settled = false;
  const fail = (code, detail) => {
    if (settled) return; settled = true;
    try { server.close(); } catch {}
    agentEnded(link, true, { code, detail }, opts);
  };
  const timer = setTimeout(() => fail(127, 'The elevated agent did not connect in time.'), 90_000);
  server.on('connection', (sock) => {
    if (settled || link.sock) { sock.destroy(); return; }
    const rl = readline.createInterface({ input: sock });
    let authed = false;
    rl.once('line', (first) => {
      // wrong token, or the user pressed Stop while the permission prompt was open: turn it away
      // (the agent exits as soon as its connection closes)
      if (first.trim() !== token || agent !== link) { sock.destroy(); return; }
      authed = true; settled = true; link.sock = sock; link.pending = false;
      clearTimeout(timer); server.close();
      // remaining lines are events
      rl.on('line', (line) => {
        let ev; try { ev = JSON.parse(line); } catch { return; }
        queue.push(ev);
        if (!flushTimer) flushTimer = setTimeout(() => { flushTimer = null; const q = queue; queue = []; send('agent:events', q); }, 60);
      });
    });
    sock.on('error', () => {});
    sock.on('close', () => { if (authed) agentEnded(link, false, { code: 0 }, opts); });
  });
  server.listen(0, '127.0.0.1', () => {
    const port = server.address().port;
    const full = [...args, '--deep', '--connect', `127.0.0.1:${port}`, '--token', token];
    const quoted = full.map((a) => `"${String(a).replace(/"/g, '')}"`).join(' ');
    // Values go through the environment, so nothing needs escaping inside the PowerShell command.
    const ps = spawn('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command',
      'try { Start-Process -FilePath $env:WT_AGENT -ArgumentList $env:WT_ARGS -Verb RunAs -WindowStyle Hidden -ErrorAction Stop; exit 0 } catch { exit 126 }'],
      { windowsHide: true, env: { ...process.env, WT_AGENT: AGENT, WT_ARGS: quoted } });
    ps.on('exit', (code) => { if (code !== 0) { clearTimeout(timer); fail(126, 'The Windows permission prompt was declined.'); } });
    ps.on('error', (e) => { clearTimeout(timer); fail(127, String(e.message || e)); });
  });
  return { ok: true };
}

function stageForRoot() {
  const dir = path.join(app.getPath('home'), '.cache', 'whosees');
  fs.mkdirSync(dir, { recursive: true });
  const copy = (src, name, mode) => {
    const dst = path.join(dir, name);
    const a = fs.statSync(src);
    let same = false;
    try { const b = fs.statSync(dst); same = b.size === a.size && b.mtimeMs >= a.mtimeMs; } catch {}
    if (!same) { fs.copyFileSync(src, dst); if (mode) fs.chmodSync(dst, mode); }
    return dst;
  };
  const tdir = path.join(dir, 'threats'); fs.mkdirSync(tdir, { recursive: true });
  for (const f of ['domains.txt', 'ips.txt']) { try { const d = path.join(tdir, f); const a = fs.statSync(path.join(THREATS, f)); let same = false; try { const b = fs.statSync(d); same = b.size === a.size && b.mtimeMs >= a.mtimeMs; } catch {} if (!same) fs.copyFileSync(path.join(THREATS, f), d); } catch {} }
  return { agent: copy(AGENT, 'whosees-agent', 0o755), geo: copy(GEO, 'world.wtgeo'), cats: copy(CATS, 'domains.json'), threats: tdir };
}

function stopAgent() {
  const a = agent;
  if (!a) return;
  agent = null;
  a.send('{"cmd":"stop"}\n'); a.end();
  setTimeout(() => a.kill(), 1500).unref();
}

ipcMain.handle('agent:start', (_e, opts) => startAgent(opts));
ipcMain.handle('agent:stop', () => { stopAgent(); return { ok: true }; });
ipcMain.handle('agent:send', (_e, msg) => {
  if (!agent || !msg || typeof msg !== 'object') return false;
  agent.send(JSON.stringify(msg) + '\n'); return true;
});

ipcMain.handle('city:find', (_e, q) => new Promise((resolve) => {
  if (typeof q !== 'string' || !q.trim() || !fs.existsSync(AGENT)) return resolve([]);
  execFile(AGENT, ['--geo', GEO, '--find-city', q.slice(0, 80)], { timeout: 5000, windowsHide: true }, (err, out) => {
    if (err) return resolve([]);
    try { resolve(JSON.parse(out)); } catch { resolve([]); }
  });
}));

// ---------- map tiles (PMTiles byte ranges) ----------
let tilesFd = null;
ipcMain.handle('tiles:read', async (_e, offset, length) => {
  if (tilesFd === null) tilesFd = fs.openSync(TILES, 'r');
  const buf = Buffer.alloc(Math.max(0, Math.min(length, 16 * 1024 * 1024)));
  const bytesRead = await new Promise((res, rej) =>
    fs.read(tilesFd, buf, 0, buf.length, offset, (err, n) => (err ? rej(err) : res(n))));
  return new Uint8Array(buf.buffer, buf.byteOffset, bytesRead);
});

// ---------- app icons (only from icon folders, only images) ----------
const iconCache = new Map();
const ICON_DIRS = [
  '/usr/share/icons', '/usr/share/pixmaps', '/var/lib/flatpak/exports/share/icons',
  path.join(app.getPath('home'), '.local/share/icons'),
  path.join(app.getPath('home'), '.local/share/flatpak/exports/share/icons'),
];
ipcMain.handle('icon:get', async (_e, p) => {
  if (typeof p !== 'string') return null;
  if (iconCache.has(p)) return iconCache.get(p);
  let out = null;
  // Windows: the agent sends the program's .exe path; ask the OS for its icon.
  if (process.platform === 'win32' && /\.exe$/i.test(p)) {
    try { out = (await app.getFileIcon(p, { size: 'large' })).toDataURL(); } catch {}
    iconCache.set(p, out);
    return out;
  }
  try {
    const real = fs.realpathSync(p);
    const okDir = ICON_DIRS.some((d) => real.startsWith(d + path.sep));
    const ext = path.extname(real).toLowerCase();
    if (okDir && (ext === '.png' || ext === '.svg') && fs.statSync(real).size < 2 * 1024 * 1024) {
      const mime = ext === '.svg' ? 'image/svg+xml' : 'image/png';
      out = `data:${mime};base64,${fs.readFileSync(real).toString('base64')}`;
    }
  } catch {}
  iconCache.set(p, out);
  return out;
});

ipcMain.handle('settings:get', () => loadSettings());
ipcMain.handle('settings:set', (_e, patch) => { const s = { ...loadSettings(), ...patch }; saveSettings(s); return s; });
// Update check (off unless the user turns it on): fetch one small public file. No cookies, no ID, a bare
// user agent; nothing about the user or the session is sent. WT_UPDATE_URL is only for automated tests.
const UPDATE_URL = process.env.WT_UPDATE_URL || 'https://whosees.app/version.json';
ipcMain.handle('update:check', () => new Promise((resolve) => {
  const done = (r) => resolve(r);
  const parse = (txt) => { try { const j = JSON.parse(txt); return { ok: true, latest: String(j.latest || ''), released: j.released || '', notes: j.notes || '' }; } catch { return { ok: false, error: 'bad reply' }; } };
  if (UPDATE_URL.startsWith('file://')) { try { return done(parse(fs.readFileSync(new URL(UPDATE_URL), 'utf8'))); } catch (e) { return done({ ok: false, error: e.message }); } }
  const req = require('node:https').get(UPDATE_URL, { headers: { 'User-Agent': 'WhoSees', Accept: 'application/json' }, timeout: 8000 }, (res) => {
    if (res.statusCode !== 200) { res.resume(); return done({ ok: false, error: `HTTP ${res.statusCode}` }); }
    let b = ''; res.setEncoding('utf8'); res.on('data', (c) => { if (b.length < 65536) b += c; }); res.on('end', () => done(parse(b)));
  });
  req.on('timeout', () => { req.destroy(); done({ ok: false, error: 'timeout' }); });
  req.on('error', (e) => done({ ok: false, error: e.message }));
}));
ipcMain.handle('app:info', () => ({
  version: app.getVersion(), platform: process.platform, user: require('node:os').userInfo().username,
  exe: process.execPath, // so the UI can recognise WhoSees's own traffic (the same path the agent gets as --self-exe)
  agent: fs.existsSync(AGENT), geo: fs.existsSync(GEO), tiles: fs.existsSync(TILES),
}));

function devScreenshots(w, prefix) {
  const shots = (process.env.WT_SHOT_STEPS || 'idle:3000,live:14000').split(',').map((s) => s.split(':'));
  w.webContents.on('console-message', (e) => console.log('[renderer]', e.message));
  w.webContents.on('did-finish-load', async () => {
    let t = 0;
    for (const [name, at, js] of shots) {
      await new Promise((r) => setTimeout(r, +at - t)); t = +at;
      try {
        if (name === 'live') await w.webContents.executeJavaScript("document.getElementById('startBtn').click()");
        else if (js) await w.webContents.executeJavaScript(decodeURIComponent(js));
      } catch (err) { console.log(`CHECK step-${name}-runs FAIL ${JSON.stringify(String(err.message || err))}`); }
      await new Promise((r) => setTimeout(r, name === 'live' ? 6000 : 400));
      const img = await w.webContents.capturePage();
      fs.writeFileSync(`${prefix}-${name}.png`, img.toPNG());
      console.log('shot', name);
    }
    app.quit();
  });
}

// ---------- report (PDF), made on this computer ----------
// The page is printed in a hidden window with scripts off, in its own in-memory session that refuses
// every request: everything the report shows (fonts, map picture) is inside the document itself.
let lastReport = null;
ipcMain.handle('report:save', async (_e, { html, name } = {}) => {
  if (typeof html !== 'string' || html.length > 80e6) return { ok: false, error: 'The report is too large.' };
  let file = DEV && process.env.WT_REPORT_OUT; // automated tests: no dialog
  if (!file) {
    const safe = String(name || 'WhoSees report.pdf').replace(/[\\/:*?"<>|]/g, '-');
    const r = await dialog.showSaveDialog(win, { title: 'Save report', defaultPath: path.join(app.getPath('documents'), safe), filters: [{ name: 'PDF', extensions: ['pdf'] }] });
    if (r.canceled || !r.filePath) return { ok: false, cancelled: true };
    file = /\.pdf$/i.test(r.filePath) ? r.filePath : `${r.filePath}.pdf`;
  }
  const tmp = path.join(app.getPath('temp'), `whosees-report-${process.pid}-${Date.now()}.html`);
  let w = null;
  try {
    fs.writeFileSync(tmp, html, { mode: 0o600 });
    if (DEV && process.env.WT_REPORT_OUT) fs.writeFileSync(`${file}.html`, html); // tests: keep the page too
    const ses = session.fromPartition('whosees-report');
    noNetworkAtStartup(ses);
    ses.webRequest.onBeforeRequest((d, cb) => cb({ cancel: !/^(file|data):/.test(d.url) }));
    w = new BrowserWindow({ show: false, webPreferences: { session: ses, javascript: false, sandbox: true, contextIsolation: true, spellcheck: false } });
    await w.loadFile(tmp);
    const pdf = await w.webContents.printToPDF({ printBackground: true, preferCSSPageSize: true, generateDocumentOutline: true, generateTaggedPDF: true });
    fs.writeFileSync(file, pdf);
    lastReport = file;
    return { ok: true, path: file, bytes: pdf.length };
  } catch (e) {
    return { ok: false, error: String(e.message || e) };
  } finally {
    try { w?.destroy(); } catch {}
    try { fs.unlinkSync(tmp); } catch {}
  }
});
// Only the report just saved can be opened or shown from the page.
ipcMain.handle('report:open', (_e, p) => (p && p === lastReport ? shell.openPath(p) : 'not allowed'));
ipcMain.handle('report:show', (_e, p) => { if (p && p === lastReport) shell.showItemInFolder(p); });

// WhoSees sends nothing on its own. Chromium's spellchecker would otherwise download a dictionary
// from Google (redirector.gvt1.com) the first time the app opens, even with spellcheck off in the window.
function noNetworkAtStartup(ses) {
  try { ses.setSpellCheckerEnabled(false); } catch {}
  try { if (process.platform !== 'darwin') ses.setSpellCheckerLanguages([]); } catch {}
  try { ses.setSpellCheckerDictionaryDownloadURL('http://127.0.0.1:9/'); } catch {} // never reached: a local, closed port
}

// ---------- lifecycle ----------
app.whenReady().then(() => {
  noNetworkAtStartup(session.defaultSession);
  migrateSettings();
  protocol.handle('wt', async (req) => {
    const p = resolveWt(req.url);
    if (!p || !fs.existsSync(p) || !fs.statSync(p).isFile()) {
      if (DEV) console.log('[404]', req.url);
      return new Response('not found', { status: 404, headers: { 'content-type': 'text/plain' } });
    }
    const type = MIME[path.extname(p).toLowerCase()] || 'application/octet-stream';
    const body = await fs.promises.readFile(p);
    return new Response(body, { headers: { 'content-type': type, 'cache-control': 'no-cache' } });
  });
  createWindow();
  app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
});
app.on('window-all-closed', () => { stopAgent(); app.quit(); });
app.on('before-quit', stopAgent);
