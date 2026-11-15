import { createMap, Flows, maplibregl, mapStyle } from './map.js';
import { buildReport, snapshotMap, fontCss, reportFileName, paperFor } from './report.js';
import { Session, CATEGORIES, TRACKING, bytes, rate, ago, placeName, countryName } from './model.js';

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const wt = window.wt;
const DEVICE = wt.platform === 'android' ? 'phone' : 'computer'; // wording
// Blocking works only while a live view runs (Deep mode on a computer, always on Android). Blocks end when the
// person presses Stop, unless they mark them "Keep".
const FEATURES = { blocking: true };
const TRACKING_RULE = { kind: 'category', value: 'tracking', label: 'All trackers and ads' };
// WhoSees is free, all of it. Support is voluntary: a one-off tip through PayPal.Me (set your PayPal.Me link here).
const SUPPORT_URL = 'https://www.paypal.com/paypalme/techytj';
const SUPPORT_AMOUNTS = [5, 10, 15];

const state = {
  settings: {}, mode: 'simple', tab: 'apps', running: false, view: null /* {type:'app'|'place', id} */,
  query: '', fresh: new Set(), timer: null,
};
const session = new Session();
let map, flows;
window.__wt = { session, get map() { return map; }, get flows() { return flows; },
  reloadSettings: async () => { state.settings = await wt.getSettings(); render(true); if (state.view) renderDetail(); },
  saveReport: (o) => saveReport(o), openReport: () => openReport() }; // for automated UI checks

// ---------- boot ----------
(async function boot() {
  state.settings = await wt.getSettings();
  document.body.classList.toggle('android', wt.platform === 'android');
  if (DEVICE !== 'computer') $('#hero p').innerHTML = $('#hero p').innerHTML.replace(/computer/g, DEVICE);
  state.mode = state.settings.mode || 'simple';
  applyTheme(state.settings.theme || 'system');
  syncModeSeg();

  map = await createMap('map', document.documentElement.dataset.theme, state.settings.home ? [state.settings.home.lon, state.settings.home.lat] : undefined);
  flows = new Flows(map, $('#flows'), session);

  if (!state.settings.home) await guessHome();
  setHome(state.settings.home, false);

  const info = await wt.info();
  state.user = info.user; state.version = info.version || '0.0.0';
  if (!info.agent) toast('Capture agent missing — build it with cargo build --release');

  await endSessionBlocks(); // left over if WhoSees was closed during a live view
  bindUi();
  $('#reportBtn').onclick = openReport; $('#heroReport').onclick = openReport;
  syncDeepChip();
  if (!FEATURES.blocking) document.querySelector('[data-tab=blocked]')?.remove();
  renderTabs();
  renderAlertBadge();
  flows.isBlocked = isBlockedPlace;
  flows.hasAlert = (p) => (p.alerts || 0) > 0 && session.alerts.some((a) => a.placeKey === p.key && a.status === 'new' && !isTrusted(a));
  fitPadding(); addEventListener('resize', fitPadding);
  document.body.classList.add('idle');
  setTimeout(updatesAtLaunch, 1200);
  session.on(onSessionEvent);
  wt.onEvents((evs) => session.ingest(evs));
  wt.onExit(async () => { if (state.running) { setRunning(false); await endSessionBlocks(); toast('Live view stopped'); } });
  setInterval(render, 500);
  render(true);
})();

async function guessHome() {
  // Timezone city ("America/Toronto" -> Toronto): a good offline first guess, user can change it.
  try {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || '';
    const city = tz.split('/').pop().replace(/_/g, ' ');
    const hits = city ? await wt.findCity(city) : [];
    if (hits[0]) state.settings = await wt.setSettings({ home: hits[0], homeGuessed: true });
  } catch {}
}

function setHome(h, fly = true) {
  if (!h) { $('#homeBtn').textContent = 'set location'; return; }
  flows.setHome([h.lon, h.lat], h.city);
  $('#homeBtn').textContent = `${h.city}, ${countryName(h.country)}`;
  if (fly) map.flyTo({ center: [h.lon, h.lat], duration: 1200 });
}

// Keep the map's visual centre clear of the side panel / bottom sheet.
function fitPadding() {
  const narrow = matchMedia('(max-width: 900px)').matches;
  map.setPadding(narrow ? { top: 110, bottom: innerHeight * 0.44 + 50, left: 0, right: 0 } : { top: 60, bottom: 40, left: 0, right: 430 });
}

// ---------- theme / mode ----------
function applyTheme(pref) {
  const dark = pref === 'dark' || (pref === 'system' && matchMedia('(prefers-color-scheme: dark)').matches);
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
  wt.setTheme(pref);
  if (map) { map.setTheme(dark ? 'dark' : 'light'); flows.readColors(); }
}
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
  if ((state.settings.theme || 'system') === 'system') applyTheme('system');
});
function syncModeSeg() {
  for (const b of document.querySelectorAll('#modeSeg button')) b.classList.toggle('on', b.dataset.mode === state.mode);
}

// ---------- blocking rules ----------
const rules = () => state.settings.rules || [];
function baseDomain(h) {
  const p = h.split('.');
  if (p.length <= 2) return h;
  const sld = p[p.length - 2];
  return (p[p.length - 1].length === 2 && ['co', 'com', 'net', 'org', 'gov', 'ac', 'edu'].includes(sld)) ? p.slice(-3).join('.') : p.slice(-2).join('.');
}
function ruleMatches(r, p) {
  switch (r.kind) {
    case 'company': return [...p.owners.keys()].some((o) => o.toLowerCase() === r.value.toLowerCase());
    case 'host': return [...p.hosts].some((h) => h === r.value || h.endsWith('.' + r.value));
    case 'country': return p.geo?.country === r.value;
    case 'ip': return !!p.stops?.has(r.value) || [...p.conns].some((id) => session.conns.get(id)?.remote === r.value);
    // like the agents: judged by website names, never by a guess from the address owner
    case 'category': return [...p.conns].map((id) => session.conns.get(id)).concat([...(p.stops?.values() || [])])
      .some((c) => !!c?.host && (c.category === r.value || (r.value === 'tracking' && TRACKING.has(c.category))));
  }
  return false;
}
const placeRules = (p) => rules().filter((r) => ruleMatches(r, p));
// "Blocked" is only ever shown when blocking was really on for this live view (Standard mode can't block)
const isBlockedPlace = (p) => p.scope === 'internet' && session.blocking && placeRules(p).length > 0;
const fullCapture = () => session.mode === 'deep' || session.mode === 'vpn'; // Android's VPN sees everything
const blockingLive = () => state.running && fullCapture() && session.blocking;

function pushRules() {
  if (!state.running || !fullCapture()) return;
  wt.send({ cmd: 'rules', rules: rules().map(({ kind, value }) => ({ kind, value })) });
}
const needsDeep = () => wt.platform !== 'android' && !state.settings.deep;
async function addRule(kind, value, label, { keep = false } = {}) {
  if (rules().some((r) => r.kind === kind && r.value === value)) return;
  state.settings = await wt.setSettings({ rules: [...rules(), { kind, value, label, keep, added: Date.now() }] });
  pushRules();
  render(true); renderTabs();
  if (needsDeep()) return askForDeep(label, kind, value);
  toast(blockingLive() ? `Blocked ${label}${keep ? '. WhoSees will keep blocking it in future live views.' : ' until you press Stop'}`
    : `${label} will be blocked while your next live view runs`, 4500);
}
// The firewall needs administrator rights, which only Deep mode asks for.
function askForDeep(label, kind, value) {
  const d = $('#dlg');
  d.innerHTML = `<div class="dlg"><div class="dlg-icon"><svg viewBox="0 0 24 24" width="26" height="26"><circle cx="12" cy="12" r="9"/><path d="m5.7 5.7 12.6 12.6"/></svg></div>
    <h3>Blocking needs Deep mode</h3>
    <p class="sub">To stop apps reaching <b>${esc(label)}</b>, WhoSees adds a temporary rule to this computer's firewall. That needs ${wt.platform === 'win32' ? 'administrator permission' : 'your password'}, which Deep mode asks for when a live view starts. The rule is removed when you press Stop.</p>
    <div class="foot"><button class="ghost" id="deepLater">Not now</button><button class="primary" id="deepOn">Turn on Deep mode${state.running ? ' and restart' : ''}</button></div></div>`;
  if (!d.open) d.showModal();
  // without Deep mode nothing can be blocked: don't leave a block on the list that isn't doing anything
  d.querySelector('#deepLater').onclick = async () => { d.close(); await removeRules((r) => r.kind === kind && r.value === value); refreshAlertCards(); toast(`Not blocked. Turn on Deep mode in Settings to block ${label}.`, 4500); };
  d.querySelector('#deepOn').onclick = async () => {
    d.close();
    state.settings = await wt.setSettings({ deep: true }); syncDeepChip();
    if (state.running) { await wt.stop(); setRunning(false); start(); }
    else toast('Deep mode is on. Press Start to begin blocking.');
  };
}
// Blocks not marked "Keep" end with the live view (also after a crash or closing the window mid-view).
async function endSessionBlocks() {
  const gone = rules().filter((r) => !r.keep);
  if (!gone.length) return 0;
  state.settings = await wt.setSettings({ rules: rules().filter((r) => r.keep) });
  renderTabs();
  return gone.length;
}
async function removeRules(match) {
  state.settings = await wt.setSettings({ rules: rules().filter((r) => !match(r)) });
  pushRules();
  render(true); renderTabs();
}
function renderTabs() {
  const n = rules().length;
  const b = document.querySelector('[data-tab=blocked]');
  if (b) b.innerHTML = `Blocked${n ? ` <span class="count">${n}</span>` : ''}`;
}

// ---------- threat alerts ----------
const trusted = () => state.settings.trusted || [];
function isTrusted(a) { return trusted().includes(a.key); }
function alertCount() { return session.alerts.filter((a) => a.status === 'new' && !isTrusted(a)).length; }

function showAlert(a) {
  if (isTrusted(a) || state.settings.alerts === false) { a.status = 'trusted'; return; }
  renderAlertBadge();
  if (state.tab === 'alerts' && !state.view) renderList();
  const box = $('#alertStack');
  // one card per thing to block: the lookup and the connection to the same bad site share a card
  const target = a.block ? `${a.block.kind}|${a.block.value}` : a.key;
  const twin = session.alerts.find((x) => x !== a && x.block && `${x.block.kind}|${x.block.value}` === target);
  if (twin && twin.status !== 'new') { a.status = twin.status; renderAlertBadge(); return; }
  if (twin && box.querySelector(`[data-alert="${twin.id}"]`)) return;
  const card = document.createElement('div');
  card.className = `alert-card ${a.severity}`;
  card.dataset.alert = a.id;
  card.innerHTML = alertCardHtml(a);
  box.prepend(card);
  while (box.children.length > 2) box.lastChild.remove();
  if (a.severity === 'medium') setTimeout(() => card.isConnected && a.status === 'new' && card.classList.add('fade'), 45000);
  if (document.hidden || !document.hasFocus()) {
    try {
      const n = new Notification(a.severity === 'high' ? `⚠ ${a.title}` : a.title, { body: a.detail, silent: a.severity !== 'high' });
      n.onclick = () => { window.focus(); openAlerts(); };
    } catch {}
  }
}

function alertCardHtml(a) {
  const icon = a.severity === 'high'
    ? '<svg viewBox="0 0 24 24"><path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/></svg>'
    : '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 8v4M12 16h.01"/></svg>';
  const done = a.status === 'blocked' ? '<span class="alert-done">Blocked</span>' : a.status === 'trusted' ? `<span class="alert-done">${FEATURES.blocking ? 'Trusted' : 'Noted'}</span>` : '';
  return `<div class="alert-ic">${icon}</div>
    <div class="alert-body"><div class="alert-sev">${a.severity === 'high' ? 'Dangerous' : 'Suspicious'} · ${esc(ago(a.ts))}</div>
      <b>${esc(a.title)}</b><p>${esc(a.detail)}</p>
      <div class="alert-actions">${done || (FEATURES.blocking ? `<button class="primary sm danger" data-alert-block="${a.id}" title="Block ${esc(a.block?.label || '')}">Block now</button>
        <button class="ghost sm" data-alert-trust="${a.id}">Trust</button>` : `<button class="ghost sm" data-alert-trust="${a.id}">Got it</button>`)}
        ${a.placeKey ? `<button class="ghost sm" data-alert-details="${a.id}">Details</button>` : ''}</div></div>
    <button class="alert-x" data-alert-dismiss="${a.id}" aria-label="Dismiss">×</button>`;
}

function refreshAlertCards() {
  for (const c of document.querySelectorAll('#alertStack .alert-card')) {
    const a = session.alerts.find((x) => x.id === +c.dataset.alert);
    if (a) c.innerHTML = alertCardHtml(a);
  }
  renderAlertBadge();
  if (state.tab === 'alerts' && !state.view) renderList();
}

async function alertAction(kind, id) {
  const a = session.alerts.find((x) => x.id === +id);
  if (!a) return;
  if (kind === 'block') {
    for (const x of session.alerts) if (x.block && a.block && x.block.kind === a.block.kind && x.block.value === a.block.value) x.status = 'blocked';
    if (a.block) await addRule(a.block.kind, a.block.value, a.block.label, { keep: true }); // a dangerous site stays blocked
    if (!blockingLive()) for (const x of session.alerts) if (x.status === 'blocked' && x.block && a.block && x.block.kind === a.block.kind && x.block.value === a.block.value) x.status = 'new';
  } else if (kind === 'trust') {
    const same = session.alerts.filter((x) => x === a || (x.block && a.block && x.block.kind === a.block.kind && x.block.value === a.block.value));
    state.settings = await wt.setSettings({ trusted: [...new Set([...trusted(), ...same.map((x) => x.key)])] });
    for (const x of same) x.status = 'trusted';
    document.querySelector(`#alertStack [data-alert="${a.id}"]`)?.remove();
  } else if (kind === 'dismiss') {
    document.querySelector(`#alertStack [data-alert="${a.id}"]`)?.remove();
    if (a.status === 'new') a.status = 'seen';
  } else if (kind === 'details') {
    document.querySelector(`#alertStack [data-alert="${a.id}"]`)?.remove();
    if (a.placeKey) openDetail({ type: 'place', id: a.placeKey });
  }
  refreshAlertCards();
}

function renderAlertBadge() {
  const n = alertCount();
  const b = $('#alertBadge');
  b.hidden = n === 0;
  b.querySelector('span').textContent = `${n} ${n === 1 ? 'alert' : 'alerts'}`;
  b.classList.toggle('high', session.alerts.some((a) => a.status === 'new' && a.severity === 'high' && !isTrusted(a)));
  const t = document.querySelector('[data-tab=alerts]');
  if (t) t.innerHTML = `Alerts${n ? ` <span class="count warn">${n}</span>` : ''}`;
}

function openAlerts() {
  if (state.view) closeDetail();
  state.tab = 'alerts';
  for (const x of document.querySelectorAll('.tabs button')) x.classList.toggle('on', x.dataset.tab === 'alerts');
  renderList();
}

// ---------- start / stop ----------
async function start() {
  if (!state.settings.home) { openLocation(); return; }
  session.reset(); session.on(onSessionEvent);
  flows.births.clear(); flows.pulses = []; flows.ripples = []; flows.focus = null;
  state.view = null; state.fresh.clear(); state.userMoved = false;
  $('#alertStack').innerHTML = ''; renderAlertBadge();
  const deep = !!state.settings.deep && (wt.platform === 'linux' || wt.platform === 'win32');
  if (wt.platform === 'android' && !state.settings.vpnExplained) {
    const go = await explainVpn();
    if (go !== 'go') return;
  }
  // Android Private DNS (hostname mode) encrypts lookups, so website names can't be seen. Say so, once, plainly.
  let privateDns = null;
  if (wt.privateDns) {
    privateDns = (await wt.privateDns().catch(() => ({}))).server || null;
    if (privateDns) {
      state.settings = await wt.setSettings({ privateDnsWas: privateDns });
      if (!state.settings.privateDnsNoted && (await explainPrivateDns(privateDns)) !== 'go') return;
    }
  }
  if (deep && !state.settings.deepExplained) {
    const go = await explainPassword();
    if (go === 'cancel') return;
    if (go === 'standard') { state.settings = await wt.setSettings({ deep: false }); syncDeepChip(); return start(); }
  }
  const r = await wt.start({ lan: !!state.settings.lan, deep });
  if (!r.ok) { toast(r.error || 'Could not start'); return; }
  setRunning(true);
  if (privateDns) toast('Private DNS is on, so some website names may be missing', 6000);
}
async function stop() {
  await wt.stop(); setRunning(false);
  const ended = await endSessionBlocks();
  if (ended) toast(`${ended} ${ended === 1 ? 'block' : 'blocks'} ended with this live view. Choose Keep in Blocked to keep one.`, 5000);
  // they turned Private DNS off for WhoSees: remind them, once, to turn it back on
  if (wt.privateDns && state.settings.privateDnsWas && !(await wt.privateDns().catch(() => ({}))).server) {
    toast('Private DNS is still off. To turn it back on: Settings, then search "Private DNS".', 9000);
    state.settings = await wt.setSettings({ privateDnsWas: null });
  }
}

function setRunning(on) {
  state.running = on;
  document.body.classList.toggle('idle', !on);
  $('#hero').classList.toggle('gone', on);
  $('#stopBtn').hidden = !on;
  $('#status').classList.toggle('live', on);
  clearInterval(state.timer);
  if (on) {
    const t0 = Date.now();
    const tick = () => {
      const s = Math.floor((Date.now() - t0) / 1000);
      $('#statusText').textContent = `Live${session.mode === 'deep' ? ' · Deep' : ''} · ${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
    };
    tick(); state.timer = setInterval(tick, 1000);
  } else {
    $('#statusText').textContent = session.started ? 'Stopped' : 'Ready';
    if (session.started) {
      session.ended ??= Date.now();
      $('#heroReport').hidden = false;
      const sm = session.summary();
      $('#hero').querySelector('h1').textContent = 'Live view stopped';
      $('#hero').querySelector('p').textContent =
        `This session your ${DEVICE} sent ${bytes(session.totals.sent)} to ${sm.places} places in ${sm.countries} countries` +
        (sm.tracking ? `, including ${sm.tracking} tracking or advertising destinations.` : '.') + ' Nothing is running now.';
      $('#startBtn').lastChild.textContent = 'Start a new live view';
      setTimeout(() => $('#hero').classList.remove('gone'), 50);
    }
  }
}

// ---------- session events -> animation ----------
function onSessionEvent(type, d) {
  if (type === 'open') {
    flows.born(d.place.key);
    if (d.fresh) {
      state.fresh.add('c' + d.conn.id); state.fresh.add('a' + d.app.id); state.fresh.add('p' + d.place.key);
      flows.flow(d.place, 2000);
    } else flows.flow(d.place, 400);
    scheduleFit();
  } else if (type === 'stopped') { // blocked before it ever connected: on the map with its red ring, no flow
    flows.born(d.place.key); state.fresh.add('p' + d.place.key);
    scheduleFit();
  } else if (type === 'flow') {
    flows.flow(d.place, d.sent, d.recv);
  } else if (type === 'hello') {
    if (d.mode === 'deep' || d.mode === 'vpn') pushRules();
  } else if (type === 'rules') {
    if (!d.ok && rules().length) toast(`Blocking unavailable: ${d.error || 'unknown error'}`);
  } else if (type === 'data') {
    session.dirty = true;
  } else if (type === 'alert') {
    showAlert(d);
  } else if (type === 'deepfail') {
    deepFailed(d);
  } else if (type === 'error' || type === 'warn') toast(d);
}

// Frame home + all destinations, until the user moves the map themselves.
let fitT = null;
function scheduleFit() {
  if (state.userMoved || fitT) return;
  fitT = setTimeout(() => {
    fitT = null;
    const b = flows.bounds();
    if (!b || state.userMoved || state.view) return;
    map.fitBounds(b, { padding: 70, maxZoom: 4, duration: 1400, linear: false });
  }, 1200);
}

// ---------- rendering ----------
function render(force) {
  if (!session.dirty && !force) { refreshAges(); return; }
  session.dirty = false;
  renderStats();
  renderLegend();
  if (state.view) renderDetail(); else renderList();
  state.fresh.clear();
}

function renderStats() {
  const sm = session.summary();
  $('#sRate').textContent = rate(session.totals.rateSent || 0);
  $('#sSent').textContent = bytes(session.totals.sent || 0);
  $('#sPlaces').textContent = sm.places;
  $('#sCountries').textContent = `${sm.countries} ${sm.countries === 1 ? 'country' : 'countries'}`;
  $('#sTrack').textContent = sm.tracking;
  $('#reportBtn').hidden = !session.started;
  drawSpark();
}

function drawSpark() {
  const c = $('#spark'), ctx = c.getContext('2d');
  const dpr = devicePixelRatio || 1;
  if (c.width !== 120 * dpr) { c.width = 120 * dpr; c.height = 28 * dpr; }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, 120, 28);
  const h = session.history.slice(-60);
  if (h.length < 2) return;
  const max = Math.max(1024, ...h);
  const accent = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim();
  const pts = h.map((v, i) => [(i / (h.length - 1)) * 120, 26 - (v / max) * 24]);
  const g = ctx.createLinearGradient(0, 0, 0, 28);
  g.addColorStop(0, accent + '55'); g.addColorStop(1, accent + '00');
  ctx.beginPath(); ctx.moveTo(0, 28); pts.forEach(([x, y]) => ctx.lineTo(x, y)); ctx.lineTo(120, 28); ctx.fillStyle = g; ctx.fill();
  ctx.beginPath(); pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
  ctx.strokeStyle = accent; ctx.lineWidth = 1.5; ctx.stroke();
}

function renderLegend() {
  const present = new Map();
  for (const p of session.places.values()) if (p.scope === 'internet') {
    const c = session.topCat(p.cats); present.set(c, (present.get(c) || 0) + 1);
  }
  const el = $('#legend');
  el.hidden = present.size === 0;
  el.innerHTML = [...present.entries()].sort((a, b) => b[1] - a[1]).map(([c, n]) =>
    `<span class="chip ${flows.hidden.has(c) ? 'off' : ''}" data-cat="${c}" style="--cc:var(--c-${c})">${CATEGORIES[c]?.label || c} ${n}</span>`).join('');
}

const matches = (...fields) => !state.query || fields.some((f) => String(f || '').toLowerCase().includes(state.query));

function iconHtml(a, cls = '') {
  const letter = esc((a.name || '?').trim()[0]?.toUpperCase() || '?');
  if (!a.icon && wt.platform === 'win32' && a.exe) a = { ...a, icon: a.exe };
  if (!a.icon) return `<div class="ic ${cls}">${a.system ? sysIcon() : letter}</div>`;
  const key = 'i' + btoa(unescape(encodeURIComponent(a.icon))).replace(/[^a-z0-9]/gi, '').slice(-24);
  loadIcon(a.icon, key);
  const src = iconCache.get(a.icon);
  return `<div class="ic ${cls}" data-icon="${key}">${src ? `<img src="${src}" alt="">` : letter}</div>`;
}
const sysIcon = () => '<svg viewBox="0 0 24 24" width="18" height="18"><rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/></svg>';
const iconCache = new Map();
function loadIcon(path, key) {
  if (iconCache.has(path)) return;
  iconCache.set(path, null);
  wt.icon(path).then((src) => {
    iconCache.set(path, src);
    if (src) for (const el of document.querySelectorAll(`[data-icon="${key}"]`)) el.innerHTML = `<img src="${src}" alt="">`;
  });
}
const catChip = (c) => `<span class="chip" style="--cc:var(--c-${c})">${CATEGORIES[c]?.label || c}</span>`;
const lockSvg = '<svg class="lock" viewBox="0 0 24 24"><rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg>';

function emptyState() {
  if (!state.running && !session.started) return `<div class="empty"><b>Nothing yet</b>Press <i>Start live view</i> to see what this ${DEVICE} is sending.</div>`;
  if (state.query) return `<div class="empty"><b>No matches</b>Try a different search.</div>`;
  return `<div class="empty"><b>Listening…</b>New connections will appear here as apps send data.</div>`;
}

function renderList() {
  const el = $('#list');
  const top = el.scrollTop;
  let html = '';
  if (state.tab === 'apps') {
    const apps = [...session.apps.values()].filter((a) => matches(a.name, a.exe, ...a.owners.keys(), ...a.sites.keys(), ...[...a.countries].map(countryName)))
      .sort((a, b) => (b.sent - a.sent) || (b.conns.size - a.conns.size));
    const max = Math.max(1, ...apps.map((a) => a.sent));
    html = apps.map((a) => {
      const live = [...a.conns].some((id) => session.conns.get(id)?.open);
      const nPlaces = [...a.places].filter((k) => !k.startsWith('lan:')).length;
      const sub = state.mode === 'simple'
        ? `${nPlaces} ${nPlaces === 1 ? 'place' : 'places'} in ${a.countries.size} ${a.countries.size === 1 ? 'country' : 'countries'}${a.owners.size ? ' · ' + esc(session.topOwner(a.owners)) : ''}`
        : `<span class="mono">${a.conns.size} conns · ${esc(a.exe || a.id)}</span>`;
      const tracking = [...a.cats.keys()].some((c) => TRACKING.has(c));
      return `<div class="row ${state.fresh.has('a' + a.id) ? 'fresh' : ''}" data-app="${esc(a.id)}">
        ${live ? '<span class="live-dot"></span>' : ''}${iconHtml(a)}
        <div class="main"><div class="t">${esc(a.name)}</div><div class="s">${sub}</div>
          ${tracking || (session.blocking && isBlockedApp(a)) ? `<div class="chips">${tracking ? catChip('tracker') : ''}${session.blocking && isBlockedApp(a) ? '<span class="chip" style="--cc:var(--danger)">Blocked</span>' : ''}</div>` : ''}
          <div class="bar"><i style="width:${(a.sent / max) * 100}%"></i></div></div>
        <div class="r"><b>${bytes(a.sent)}</b><small data-ago="${a.last}">${ago(a.last)}</small></div></div>`;
    }).join('');
  } else if (state.tab === 'feed') {
    html = session.feed.filter((c) => matches(c.app.name, c.owner, c.remote, c.host, c.site, c.geo?.city, countryName(c.geo?.country), c.service))
      .slice(0, 250).map((c) => {
        const t = state.mode === 'simple'
          ? `${esc(c.app.name)} <span style="color:var(--text-3)">→</span> ${esc(c.site || c.owner || (c.scope === 'internet' ? 'Unknown company' : 'Local device'))}`
          : `<span class="mono">${esc(c.proto)} ${esc(c.host || c.remote)}:${c.rport}</span>`;
        const s = state.mode === 'simple'
          ? `${c.encrypted ? lockSvg : ''}${esc(c.what)} · ${esc(placeName(c.geo))}`
          : `<span class="mono">${esc(c.service)} · ${esc(c.app.name)} · ${c.host ? esc(c.remote) + ' · ' : ''}${c.geo?.asn ? 'AS' + c.geo.asn : ''} ${esc(c.geo?.country || '')}</span>`;
        const seenD = (c.data || []).filter((d) => d.basis === 'seen');
        const chip = TRACKING.has(c.category) || seenD.length ? `<div class="chips">${TRACKING.has(c.category) ? catChip(c.category) : ''}${seenD.slice(0, 2).map((d) => `<span class="chip" style="--cc:var(--warn)">${esc(d.label)}</span>`).join('')}</div>` : '';
        return `<div class="row ${state.fresh.has('c' + c.id) ? 'fresh' : ''}" data-place="${esc(c.key)}" style="${c.open ? '' : 'opacity:.55'}">
          ${iconHtml(c.app, 'sm')}
          <div class="main"><div class="t">${t}</div><div class="s">${s}</div>${chip}</div>
          <div class="r"><b>${bytes(c.sent)}</b><small data-ago="${c.ts}">${ago(c.ts)}</small></div></div>`;
      }).join('');
  } else if (state.tab === 'alerts') {
    const list = session.alerts.filter((a) => !isTrusted(a) || a.status === 'trusted').filter((a) => matches(a.title, a.detail, a.host, a.remote));
    const lists = session.threatLists ? `Checked against ${session.threatLists[0].toLocaleString()} dangerous websites and ${session.threatLists[1].toLocaleString()} malicious servers, plus behaviour checks.` : 'Threat checks run while a live view is on.';
    html = `<div class="note">${lists} Everything is checked on this ${DEVICE}.</div>` + (list.map((a) => `<div class="alert-card inline ${a.severity}" data-alert="${a.id}">${alertCardHtml(a)}</div>`).join('')
      || '<div class="empty"><b>No alerts</b>Nothing suspicious so far.</div>');
  } else if (state.tab === 'blocked') {
    const KIND = { company: 'Company', host: 'Website', country: 'Country', ip: 'Address', app: 'Whole app', uid: 'Whole app', category: 'Kind of company' };
    const note = blockingLive() ? '<div class="note ok">Blocking is on. Blocks end when you press Stop, except the ones you keep.</div>'
      : needsDeep() ? '<div class="note">Blocking works during a Deep mode live view (Settings → Deep mode). Blocks end when you press Stop, except the ones you keep.</div>'
      : '<div class="note">Your blocks apply while a live view runs. They end when you press Stop, except the ones you keep.</div>';
    const trackOn = rules().some((r) => r.kind === 'category' && r.value === 'tracking');
    const all = `<div class="row track-all"><div class="main"><div class="t">Block all trackers and ads</div><div class="s">Stops every app reaching known tracking, advertising and analytics companies</div></div>
      <button class="switch ${trackOn ? 'on' : ''}" id="blockTracking" aria-label="Block all trackers and ads" aria-pressed="${trackOn}"></button></div>`;
    html = note + all + (rules().map((r, i) => [r, i]).filter(([r]) => !(r.kind === 'category' && r.value === 'tracking') && matches(r.label, r.value)).map(([r, i]) => `<div class="row" data-rule="${i}">
        <div class="ic sm cc" style="color:var(--danger)">${r.kind === 'country' ? esc(r.value) : '<svg viewBox="0 0 24 24" width="16" height="16"><circle cx="12" cy="12" r="9"/><path d="m5.7 5.7 12.6 12.6"/></svg>'}</div>
        <div class="main"><div class="t">${esc(r.label)}</div><div class="s">${KIND[r.kind] || r.kind}${r.kind !== 'country' && r.label !== r.value ? ` · <span class="mono">${esc(r.value)}</span>` : ''}${r.keep ? ' · kept' : ' · until Stop'}</div></div>
        <button class="ghost sm keep${r.keep ? ' on' : ''}" data-keep="${i}" aria-pressed="${!!r.keep}" title="${r.keep ? 'Kept for future live views' : 'Keep blocking it in future live views'}">${r.keep ? 'Kept' : 'Keep'}</button>
        <button class="ghost sm" data-unblock="${i}">Unblock</button></div>`).join('')
      || '<div class="empty"><b>Nothing else blocked</b>Open an app or a place on the map and choose Block.</div>');
  } else {
    const places = [...session.places.values()].filter((p) => p.scope === 'internet')
      .filter((p) => matches(...p.owners.keys(), ...p.sites.keys(), p.geo?.city, countryName(p.geo?.country)))
      .sort((a, b) => b.sent - a.sent);
    html = places.map((p) => {
      const cat = session.topCat(p.cats);
      const sub = state.mode === 'simple'
        ? `${esc(placeName(p.geo))} · ${p.sites.size ? esc(session.topSites(p.sites, 2).join(', ')) : `${p.apps.size} ${p.apps.size === 1 ? 'app' : 'apps'}`}`
        : `<span class="mono">${p.geo?.lat?.toFixed(2)}, ${p.geo?.lon?.toFixed(2)} · AS${p.geo?.asn ?? '?'} · ${p.conns.size} conns</span>`;
      return `<div class="row ${state.fresh.has('p' + p.key) ? 'fresh' : ''}" data-place="${esc(p.key)}">
        ${p.live ? '<span class="live-dot"></span>' : ''}<div class="ic cc" style="color:var(--c-${cat})">${esc(p.geo?.country || '??')}</div>
        <div class="main"><div class="t">${esc(session.topOwner(p.owners) || 'Unknown company')}</div><div class="s">${sub}</div><div class="chips">${catChip(cat)}${isBlockedPlace(p) ? '<span class="chip" style="--cc:var(--danger)">Blocked</span>' : ''}</div></div>
        <div class="r"><b>${bytes(p.sent)}</b><small data-ago="${p.last}">${ago(p.last)}</small></div></div>`;
    }).join('');
  }
  el.innerHTML = html || emptyState();
  el.scrollTop = top;
}

function refreshAges() { for (const e of document.querySelectorAll('[data-ago]')) e.textContent = ago(+e.dataset.ago); }

function backBtn() { return `<button class="back" data-back><svg viewBox="0 0 24 24"><path d="m15 18-6-6 6-6"/></svg>Back</button>`; }

function renderDetail() {
  const el = $('#detail');
  const v = state.view;
  if (v.type === 'app') {
    const a = session.apps.get(v.id);
    if (!a) return closeDetail();
    const places = [...a.places].map((k) => session.places.get(k)).filter((p) => p && p.scope === 'internet').sort((x, y) => y.sent - x.sent);
    const topP = places[0];
    const tracking = places.filter((p) => TRACKING.has(session.topCat(p.cats))).length;
    const sentence = `${esc(a.name)} sent <b>${bytes(a.sent)}</b> to ${places.length} ${places.length === 1 ? 'place' : 'places'} in ${a.countries.size} ${a.countries.size === 1 ? 'country' : 'countries'} this session.` +
      (topP ? ` Most went to ${esc(session.topOwner(topP.owners) || 'an unknown company')}${session.topCat(topP.cats) === 'other' ? '' : ', ' + CATEGORIES[session.topCat(topP.cats)].plain + ','} in ${esc(placeName(topP.geo))}.` : '') +
      (tracking ? ` <b style="color:var(--c-tracker)">${tracking} of these are tracking or advertising.</b>` : '');
    el.innerHTML = `${backBtn()}
      <div class="dhead">${iconHtml(a)}<div><h2>${esc(a.name)}</h2><p>${a.system ? 'System process' : 'App'}${state.mode === 'expert' && a.exe ? ` · <span class="mono">${esc(a.exe)}</span>` : ''}</p></div></div>
      <div class="sentence">${sentence}</div>
      ${appBlockBox(a)}
      ${dataSection([...a.conns], 'What this app sent')}
      ${privacyReport(a, places)}
      <div class="kpis"><div class="kpi"><label>Sent</label><b>${bytes(a.sent)}</b></div><div class="kpi"><label>Received</label><b>${bytes(a.recv)}</b></div><div class="kpi"><label>Places</label><b>${places.length}</b></div></div>
      <div class="sec">Where it sent data</div>
      ${places.map((p) => `<div class="row" data-place="${esc(p.key)}"><div class="ic cc sm" style="color:var(--c-${session.topCat(p.cats)})">${esc(p.geo?.country || '??')}</div>
        <div class="main"><div class="t">${esc(session.topOwner(p.owners) || 'Unknown company')}</div><div class="s">${esc(placeName(p.geo))}${p.sites.size ? ' · ' + esc(session.topSites(p.sites, 2).join(', ')) : ''}</div></div>
        <div class="r"><b>${bytes(p.sent)}</b>${catChip(session.topCat(p.cats))}</div></div>`).join('') || '<div class="empty">No internet destinations yet.</div>'}`;
    flows.focus = new Set(a.places);
  } else {
    const p = session.places.get(v.id);
    if (!p) return closeDetail();
    const cat = session.topCat(p.cats);
    const owner = session.topOwner(p.owners) || 'Unknown company';
    const apps = [...p.apps].map((id) => session.apps.get(id)).filter(Boolean);
    const conns = [...p.conns].map((id) => session.conns.get(id)).filter(Boolean);
    const enc = conns.every((c) => c.encrypted);
    // no apps: the firewall stopped every attempt before a connection showed up, so who tried isn't known
    const appNames = !apps.length ? 'An app' : apps.length === 1 ? esc(apps[0].name) : `${esc(apps[0].name)} and ${apps.length - 1} other ${apps.length === 2 ? 'app' : 'apps'}`;
    el.innerHTML = `${backBtn()}
      <div class="dhead"><div class="ic cc" style="color:var(--c-${cat})">${esc(p.geo?.country || '??')}</div><div><h2>${esc(owner)}</h2><p>${esc(placeName(p.geo))}${p.geo?.region ? ' · ' + esc(p.geo.region) : ''}</p></div></div>
      <div class="sentence">${!conns.length ? `${appNames} tried to reach ${esc(owner)}${cat === 'other' ? '' : ', ' + CATEGORIES[cat].plain + ','} in ${esc(placeName(p.geo))}. <b>WhoSees stopped it before it could connect</b>, so nothing was sent.`
        : isBlockedPlace(p) && p.sent === 0 ? `${appNames} tried to reach ${esc(owner)}${cat === 'other' ? '' : ', ' + CATEGORIES[cat].plain + ','} in ${esc(placeName(p.geo))}. <b>WhoSees blocked it</b>, so nothing was sent.` : `${appNames} sent <b>${bytes(p.sent)}</b> to ${esc(owner)}${cat === 'other' ? '' : ', ' + CATEGORIES[cat].plain + ','} in ${esc(placeName(p.geo))}. ${enc ? 'The traffic was encrypted, so its contents are private between the app and the server.' : 'Some of this traffic was <b>not encrypted</b>.'}`}</div>
      ${dataSection([...p.conns], 'What was sent here')}
      <div class="kpis"><div class="kpi"><label>Sent</label><b>${bytes(p.sent)}</b></div><div class="kpi"><label>Received</label><b>${bytes(p.recv)}</b></div>${conns.length ? `<div class="kpi"><label>Connections</label><b>${conns.length}</b></div>` : `<div class="kpi"><label>Attempts stopped</label><b>${session.stoppedAt(p)}</b></div>`}</div>
      ${p.sites.size ? `<div class="sec">${state.mode === 'expert' ? 'Hostnames' : 'Websites and services'}</div>
      <div class="sites">${(state.mode === 'expert' ? [...p.hosts] : session.topSites(p.sites, 20)).map((x) => `<span class="${state.mode === 'expert' ? 'mono' : ''}">${esc(x)}</span>`).join('')}</div>` : ''}
      ${apps.length ? '<div class="sec">Apps talking to it</div>' : ''}
      ${apps.map((a) => `<div class="row" data-app="${esc(a.id)}">${iconHtml(a, 'sm')}<div class="main"><div class="t">${esc(a.name)}</div></div></div>`).join('')}
      ${blockSection(p, owner)}
      <div class="sec">Details</div>
      <dl class="kv"><dt>Category</dt><dd>${catChip(cat)}</dd><dt>Owner</dt><dd>${esc(p.geo?.org || owner)}</dd>
        <dt>Location</dt><dd>${esc([p.geo?.city, p.geo?.region, countryName(p.geo?.country)].filter(Boolean).join(', '))}</dd>
        ${state.mode === 'expert' ? `<dt>Network</dt><dd class="mono">AS${p.geo?.asn ?? '?'}</dd>
        <dt>Addresses</dt><dd class="mono">${[...new Set([...conns.map((c) => `${c.remote} :${c.rport} ${c.service}`), ...[...(p.stops?.keys() || [])].map((ip) => `${ip} (stopped)`)])].map(esc).join('<br>')}</dd>`
        : conns.length ? `<dt>Type</dt><dd>${[...new Set(conns.map((c) => c.what))].map(esc).join(', ')}</dd>` : ''}
      </dl>`;
    flows.focus = new Set([p.key]);
  }
}

// Whole-app blocking: Windows (by program path) and Android (by app user id).
const appRule = (a) => wt.platform === 'win32' && a.exe ? { kind: 'app', value: a.exe } : wt.platform === 'android' && a.uid >= 10000 ? { kind: 'uid', value: String(a.uid) } : null;
const isBlockedApp = (a) => { const r = appRule(a); return !!r && rules().some((x) => x.kind === r.kind && x.value.toLowerCase() === r.value.toLowerCase()); };
function appBlockBox(a) {
  if (!FEATURES.blocking) return '';
  const r = appRule(a);
  if (!r || a.system) return '';
  if (isBlockedApp(a)) return `<div class="blockbox on"><div><b>${session.blocking ? 'Blocked from the internet' : 'On your block list'}</b><small>${blockingLive() ? 'WhoSees is stopping this app' : session.blocking ? 'Blocked during this live view' : state.running || session.started ? 'Not blocked in this live view: blocking needs Deep mode' : wt.platform === 'android' ? 'applies while a live view is on' : 'applies during a Deep mode live view'}</small></div>
    <button class="ghost sm" data-unblock-app="${esc(r.value)}">Unblock</button></div>`;
  return `<div class="blockbtns" style="padding:0 6px 12px"><button class="ghost sm danger" data-block-kind="${r.kind}" data-block-value="${esc(r.value)}" data-block-label="${esc(a.name)}">Block ${esc(a.name)} from the internet</button></div>`;
}

function blockSection(p, owner) {
  if (!FEATURES.blocking) return '';
  const active = placeRules(p);
  const stopped = session.stoppedAt(p);
  if (active.length) {
    return `<div class="blockbox on"><div><b>${session.blocking ? 'Blocked' : 'On your block list'}</b><small>${esc(active.map((r) => r.label).join(', '))}${stopped ? ` · ${stopped} ${stopped === 1 ? 'attempt' : 'attempts'} stopped` : ''}${session.blocking ? '' : ' · Not blocked in this live view: blocking needs Deep mode'}</small></div>
      <button class="ghost sm" data-unblock-place="${esc(p.key)}">Unblock</button></div>`;
  }
  const hosts = [...new Set([...p.hosts].map(baseDomain))].slice(0, 4);
  const btn = (kind, value, label, text, cls = '') => `<button class="ghost sm ${cls}" data-block-kind="${kind}" data-block-value="${esc(value)}" data-block-label="${esc(label)}">${text}</button>`;
  return `<div class="sec">Block</div><div class="blockbtns">
    ${owner && owner !== 'Unknown company' ? btn('company', owner, owner, `Block ${esc(owner)}`, 'danger') : ''}
    ${hosts.map((h) => btn('host', h, h, `Block ${esc(h)}`)).join('')}
    ${p.geo?.country ? btn('country', p.geo.country, countryName(p.geo.country), `Block all of ${esc(countryName(p.geo.country))}`) : ''}
    ${TRACKING.has(session.topCat(p.cats)) ? btn('category', 'tracking', 'All trackers and ads', 'Block all trackers and ads') : ''}
    ${state.mode === 'expert' ? [...new Set([...p.conns].map((id) => session.conns.get(id)?.remote).filter(Boolean))].slice(0, 4).map((ip) => btn('ip', ip, ip, `Block <span class="mono">${esc(ip)}</span>`)).join('') : ''}
  </div>${!state.settings.deep && wt.platform !== 'android' ? '<p class="hint">Blocking needs Deep mode (Settings).</p>' : ''}`;
}

function openDetail(view) {
  state.view = view;
  $('#list').hidden = true; $('#detail').hidden = false;
  document.querySelector('.search').hidden = true;
  $('#detail').scrollTop = 0;
  renderDetail();
  if (view.type === 'place') {
    const p = session.places.get(view.id);
    if (p?.lat != null) map.easeTo({ center: [p.lon, p.lat], duration: 900, zoom: Math.max(map.getZoom(), 2.2) });
  }
}
function closeDetail() {
  state.view = null; flows.focus = null;
  $('#list').hidden = false; $('#detail').hidden = true;
  document.querySelector('.search').hidden = false;
  renderList();
}

// Hover card: city first, then every app sending there and how much.
function tipHtml(p) {
  const g = p.geo || {};
  const city = g.city ? g.city.split(' (')[0] : null;
  const where = [g.region && g.region !== city ? g.region : null, countryName(g.country)].filter(Boolean).join(', ');
  const perApp = new Map();
  for (const id of p.conns) {
    const c = session.conns.get(id); if (!c) continue;
    const x = perApp.get(c.app.id) || { app: session.apps.get(c.app.id) || c.app, sent: 0, live: false };
    x.sent += c.sent || 0; x.live ||= c.open;
    perApp.set(c.app.id, x);
  }
  const rows = [...perApp.values()].sort((a, b) => b.sent - a.sent);
  const cat = session.topCat(p.cats);
  const owner = session.topOwner(p.owners) || 'Unknown company';
  return `<div class="tip-city">${esc(city || countryName(g.country) || 'Unknown location')}</div>
    <div class="tip-where">${esc(city ? where : '')}</div>
    <div class="tip-owner">${esc(owner)} ${catChip(cat)}</div>
    ${p.sites.size ? `<div class="tip-where" style="margin-top:4px">${esc(session.topSites(p.sites, 3).join(' · '))}${p.sites.size > 3 ? ` +${p.sites.size - 3}` : ''}</div>` : ''}
    ${(p.alerts || 0) > 0 ? `<div class="tip-blocked">⚠ ${p.alerts} ${p.alerts === 1 ? 'alert' : 'alerts'}</div>` : ''}
    ${isBlockedPlace(p) ? `<div class="tip-blocked">Blocked${session.stoppedAt(p) ? ` · ${session.stoppedAt(p)} ${session.stoppedAt(p) === 1 ? 'attempt' : 'attempts'} stopped` : ''}</div>` : ''}
    ${tipData(p)}
    ${rows.length ? '<div class="tip-label">Sending here</div>' : ''}
    ${rows.slice(0, 5).map((r) => `<div class="tip-app">${iconHtml(r.app, 'xs')}<span class="n">${esc(r.app.name)}</span>${r.live ? '<span class="on"></span>' : ''}<b>${bytes(r.sent)}</b></div>`).join('')}
    ${rows.length > 5 ? `<div class="tip-more">+${rows.length - 5} more apps</div>` : ''}`;
}

// ---------- ui wiring ----------
function bindUi() {
  $('#startBtn').onclick = start;
  $('#stopBtn').onclick = stop;
  $('#homeBtn').onclick = openLocation;
  $('#deepChip').onclick = async () => {
    state.settings = await wt.setSettings({ deep: !state.settings.deep });
    syncDeepChip();
  };
  $('#settingsBtn').onclick = openSettings;

  $('#modeSeg').onclick = async (e) => {
    const b = e.target.closest('button'); if (!b) return;
    state.mode = b.dataset.mode; syncModeSeg();
    state.settings = await wt.setSettings({ mode: state.mode });
    render(true);
  };
  document.querySelector('.tabs').onclick = (e) => {
    const b = e.target.closest('button'); if (!b) return;
    state.tab = b.dataset.tab;
    for (const x of document.querySelectorAll('.tabs button')) x.classList.toggle('on', x === b);
    if (state.view) closeDetail(); else renderList();
  };
  $('#search').oninput = (e) => { state.query = e.target.value.trim().toLowerCase(); renderList(); };

  const onRowClick = (e) => {
    if (e.target.closest('[data-back]')) return closeDetail();
    const al = e.target.closest('[data-alert-block],[data-alert-trust],[data-alert-details],[data-alert-dismiss]');
    if (al) { const k = ['block', 'trust', 'details', 'dismiss'].find((x) => al.dataset['alert' + x[0].toUpperCase() + x.slice(1)]); return alertAction(k, al.dataset['alert' + k[0].toUpperCase() + k.slice(1)]); }
    const b = e.target.closest('[data-block-kind]');
    if (b) return addRule(b.dataset.blockKind, b.dataset.blockValue, b.dataset.blockLabel);
    const ua = e.target.closest('[data-unblock-app]');
    if (ua) return removeRules((r) => (r.kind === 'app' || r.kind === 'uid') && r.value === ua.dataset.unblockApp);
    const ub = e.target.closest('[data-unblock-place]');
    if (ub) { const p = session.places.get(ub.dataset.unblockPlace); return p && removeRules((r) => ruleMatches(r, p)); }
    if (e.target.closest('#blockTracking')) {
      return rules().some((r) => r.kind === 'category' && r.value === 'tracking')
        ? removeRules((r) => r.kind === 'category' && r.value === 'tracking') : addRule(TRACKING_RULE.kind, TRACKING_RULE.value, TRACKING_RULE.label);
    }
    const kp = e.target.closest('[data-keep]');
    if (kp) {
      const list = rules().map((r, i) => (i === +kp.dataset.keep ? { ...r, keep: !r.keep } : r));
      return wt.setSettings({ rules: list }).then((s) => { state.settings = s; render(true); });
    }
    const ur = e.target.closest('[data-unblock]');
    if (ur) { const r = rules()[+ur.dataset.unblock]; return r && removeRules((x) => x === r || (x.kind === r.kind && x.value === r.value)); }
    const r = e.target.closest('.row'); if (!r) return;
    if (r.dataset.app) openDetail({ type: 'app', id: r.dataset.app });
    else if (r.dataset.place && !r.dataset.place.startsWith('lan:')) openDetail({ type: 'place', id: r.dataset.place });
  };
  $('#list').onclick = onRowClick;
  $('#detail').onclick = onRowClick;

  $('#alertStack').onclick = (e) => {
    const al = e.target.closest('[data-alert-block],[data-alert-trust],[data-alert-details],[data-alert-dismiss]');
    if (!al) return;
    const k = ['block', 'trust', 'details', 'dismiss'].find((x) => al.dataset['alert' + x[0].toUpperCase() + x.slice(1)]);
    alertAction(k, al.dataset['alert' + k[0].toUpperCase() + k.slice(1)]);
  };
  $('#alertBadge').onclick = openAlerts;
  document.addEventListener('click', (e) => { if (e.target.closest('[data-notices]')) { e.preventDefault(); openNotices(); } });
  document.addEventListener('click', (e) => { if (e.target.closest('[data-support]')) { e.preventDefault(); openSupport(); } });
  $('#legend').onclick = (e) => {
    const c = e.target.closest('[data-cat]'); if (!c) return;
    const k = c.dataset.cat;
    flows.hidden.has(k) ? flows.hidden.delete(k) : flows.hidden.add(k);
    renderLegend();
  };

  // map hover + click
  const tip = $('#tip');
  map.getCanvas().addEventListener('mousemove', (e) => {
    const p = flows.hitTest(e.clientX, e.clientY);
    flows.hover = p;
    map.getCanvas().style.cursor = p ? 'pointer' : '';
    if (!p) { tip.hidden = true; return; }
    tip.innerHTML = tipHtml(p);
    tip.style.left = e.clientX + 'px'; tip.style.top = e.clientY + 'px';
    const r = tip.getBoundingClientRect();
    if (r.right > innerWidth - 8) tip.style.left = (e.clientX - r.width - 28) + 'px';
    if (r.bottom > innerHeight - 8) tip.style.top = (e.clientY - r.height - 28) + 'px';
    tip.hidden = false;
  });
  map.getCanvas().addEventListener('mouseleave', () => { tip.hidden = true; flows.hover = null; });
  map.on('click', (e) => {
    const p = flows.hitTest(e.point.x, e.point.y);
    if (p) openDetail({ type: 'place', id: p.key });
    else if (state.view) closeDetail();
  });

  for (const ev of ['dragstart', 'zoomstart']) map.on(ev, (e) => { if (e.originalEvent) state.userMoved = true; });

  // bottom sheet on small screens
  $('#grip').onclick = () => {
    const p = $('#panel');
    if (p.classList.contains('min')) p.classList.remove('min');
    else if (p.classList.contains('max')) { p.classList.remove('max'); p.classList.add('min'); }
    else p.classList.add('max');
  };

  addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && state.view) closeDetail();
    if ((e.ctrlKey || e.metaKey) && e.key === 'f') { e.preventDefault(); $('#search').focus(); }
  });
}

function syncDeepChip() {
  const el = $('#deepChip');
  if (!el) return;
  el.hidden = !['linux', 'win32'].includes(wt.platform);
  el.classList.toggle('on', !!state.settings.deep);
  el.querySelector('span').textContent = state.settings.deep ? 'Deep mode on · website names and trackers' : 'Deep mode off · turn on to see website names and trackers';
}

// ---------- what's being sent ----------
function dataChips(list, cls) {
  return list.map((d) => `<span class="dchip ${cls}" title="${esc([...d.details].slice(0, 3).join(' · '))}">${esc(d.label)}${state.mode === 'expert' && d.details.size ? `<em>${esc([...d.details][0])}</em>` : ''}</span>`).join('');
}
function dataSection(ids, title) {
  const d = session.dataFor(ids);
  const n = d.seen.length + d.likely.length + d.could.length;
  if (!n) return '';
  return `<div class="sec">${esc(title)}</div><div class="dataset">
    ${d.seen.length ? `<div class="drow"><label>Seen</label><div>${dataChips(d.seen, 'seen')}</div></div>` : ''}
    ${d.could.length ? `<div class="drow"><label>Could include</label><div>${dataChips(d.could, 'could')}</div></div>` : ''}
    ${d.likely.length ? `<div class="drow"><label>Likely</label><div>${dataChips(d.likely, 'likely')}</div></div>` : ''}
    <p class="dnote"><b>Seen</b>: read in unencrypted traffic. <b>Likely</b>: what this kind of company usually receives (the traffic is encrypted, so the contents can't be read).${d.could.length ? ' <b>Could include</b>: the app is allowed to read this and talks to ad or tracking companies.' : ''}</p></div>`;
}
function tipData(p) {
  const d = session.dataFor([...p.conns]);
  const n = d.seen.length + d.likely.length;
  if (!n) return '';
  const s = d.seen.length ? `<span style="color:var(--warn)">Seen: ${esc(d.seen.slice(0, 2).map((x) => x.label).join(', '))}</span>` : '';
  const l = d.likely.length ? `Likely: ${esc(d.likely.slice(0, 2).map((x) => x.label).join(', '))}` : '';
  return `<div class="tip-where" style="margin-top:4px">${[s, l].filter(Boolean).join(' · ')}</div>`;
}
function privacyReport(a, places) {
  const d = session.dataFor([...a.conns]);
  const tracking = places.filter((p) => TRACKING.has(session.topCat(p.cats)));
  const owners = new Set(places.flatMap((p) => [...p.owners.keys()]));
  const unenc = [...a.conns].map((id) => session.conns.get(id)).filter((c) => c && !c.encrypted && c.scope === 'internet').length;
  const grade = d.seen.some((x) => ['location', 'email', 'phone', 'advertising-id', 'password'].includes(x.kind)) || tracking.length >= 3 ? ['Poor', 'danger']
    : tracking.length || unenc ? ['Fair', 'warn'] : ['Good', 'accent'];
  return `<div class="sec">Privacy report</div><div class="report">
    <div class="grade" style="--g:var(--${grade[1]})">${grade[0]}</div>
    <ul><li>Talked to <b>${owners.size}</b> ${owners.size === 1 ? 'company' : 'companies'} in <b>${a.countries.size}</b> ${a.countries.size === 1 ? 'country' : 'countries'}</li>
      <li><b>${tracking.length}</b> tracking or advertising ${tracking.length === 1 ? 'destination' : 'destinations'}${tracking.length ? ': ' + esc([...new Set(tracking.map((p) => session.topOwner(p.owners)))].slice(0, 4).join(', ')) : ''}</li>
      <li>${d.seen.length ? `<b>${d.seen.length}</b> kinds of data seen in readable traffic` : 'Nothing readable was seen leaving'}</li>
      <li>${unenc ? `<b>${unenc}</b> unencrypted ${unenc === 1 ? 'connection' : 'connections'}` : 'All connections encrypted'}</li></ul></div>`;
}
// ---------- report (PDF): made on this device, never uploaded ----------
const REPORT_ICON = '<svg viewBox="0 0 24 24" width="26" height="26"><path d="M14 3H6.5A1.5 1.5 0 0 0 5 4.5v15A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5V8l-5-5Z"/><path d="M14 3v5h5M8.5 13h7M8.5 16.5h7M8.5 9.5h2.5"/></svg>';
function openReport() {
  if (!session.started) { toast('Start a live view first: the report covers what it finds.'); return; }
  const d = $('#dlg'), s = state.settings;
  const theme = s.reportTheme || 'dark', paper = s.reportPaper || paperFor();
  d.innerHTML = `<div class="dlg"><div class="dlg-icon">${REPORT_ICON}</div>
    <h3>Save a report</h3>
    <p class="sub">A PDF of everything this live view found: the apps, the companies and countries that received data, trackers, threats and every connection. It's made on this ${DEVICE} and isn't uploaded anywhere.</p>
    <div class="opt"><div><b>Style</b><small>Light uses less ink if you print it</small></div>
      <div class="seg" id="repTheme">${['dark', 'light'].map((t) => `<button data-v="${t}" class="${t === theme ? 'on' : ''}">${t[0].toUpperCase() + t.slice(1)}</button>`).join('')}</div></div>
    <div class="opt"><div><b>Paper size</b><small>Letter in North America, A4 almost everywhere else</small></div>
      <div class="seg" id="repPaper">${[['letter', 'Letter'], ['a4', 'A4']].map(([v, l]) => `<button data-v="${v}" class="${v === paper ? 'on' : ''}">${l}</button>`).join('')}</div></div>
    ${wt.platform === 'android' ? '<p class="fine-print">Next, Android opens its print screen. Choose <b>Save as PDF</b> at the top, then tap the round PDF button.</p>' : ''}
    <div class="foot"><button class="ghost" id="repCancel">Cancel</button><button class="primary" id="repGo">Save PDF</button></div></div>`;
  if (!d.open) d.showModal();
  const seg = (id, key) => { d.querySelector(id).onclick = async (e) => {
    const b = e.target.closest('button'); if (!b) return;
    for (const x of d.querySelectorAll(`${id} button`)) x.classList.toggle('on', x === b);
    state.settings = await wt.setSettings({ [key]: b.dataset.v });
  }; };
  seg('#repTheme', 'reportTheme'); seg('#repPaper', 'reportPaper');
  d.querySelector('#repCancel').onclick = () => d.close();
  d.querySelector('#repGo').onclick = async (e) => {
    e.currentTarget.disabled = true; e.currentTarget.textContent = 'Making the report…';
    const r = await saveReport({ theme: state.settings.reportTheme || 'dark', paper: state.settings.reportPaper || paperFor() });
    d.close();
    if (r.ok && r.path) reportSaved(r.path);
    else if (!r.ok && !r.cancelled) toast(`Couldn't save the report: ${r.error || 'unknown error'}`, 6000);
  };
}
async function saveReport({ theme = 'dark', paper = paperFor() } = {}) {
  try {
    const home = state.settings.home;
    const places = [...session.places.values()].filter((p) => p.scope === 'internet' && p.lat != null)
      .map((p) => ({ lon: p.lon, lat: p.lat, sent: p.sent, cat: session.topCat(p.cats), label: p.geo?.city ? p.geo.city.split(' (')[0] : countryName(p.geo?.country) }));
    const [mapImage, fonts] = await Promise.all([snapshotMap(maplibregl, mapStyle('dark'), places, home), fontCss()]);
    const html = buildReport(session, { platform: wt.platform, version: state.version, theme, paper, fonts, mapImage, home, rules: FEATURES.blocking ? rules() : [] });
    return await wt.saveReport({ html, name: reportFileName(session.ended || Date.now()), paper });
  } catch (e) {
    return { ok: false, error: String(e?.message || e) };
  }
}
function reportSaved(p) {
  const d = $('#dlg');
  d.innerHTML = `<div class="dlg"><div class="dlg-icon">${REPORT_ICON}</div><h3>Report saved</h3><p class="sub" style="word-break:break-all">${esc(p)}</p>
    <div class="foot"><button class="ghost" id="repShow">Show in folder</button><button class="primary" id="repOpen">Open</button></div></div>`;
  if (!d.open) d.showModal();
  d.querySelector('#repOpen').onclick = () => { wt.openReport(p); d.close(); };
  d.querySelector('#repShow').onclick = () => { wt.showReport(p); d.close(); };
}

// "Buy me a coffee": optional tips, opened in the person's own browser. Nothing is unlocked or tracked.
function openSupport() {
  const d = $('#dlg');
  d.innerHTML = `<div class="dlg support"><div class="dlg-icon"><svg viewBox="0 0 24 24" width="26" height="26"><path d="M4 9h13v5a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5V9Z"/><path d="M17 10h1.5a2.5 2.5 0 0 1 0 5H17M8 3v3M12 3v3"/></svg></div>
    <h3>Like WhoSees? Buy me a coffee.</h3>
    <p class="sub">WhoSees is free, with every feature included, and it stays that way. If it's been useful, a small tip helps cover the website, the AI tools used to build it, and keeping it up to date.</p>
    <div class="tips">${SUPPORT_AMOUNTS.map((a) => `<a class="tip-amt" href="${SUPPORT_URL}/${a}USD" target="_blank" rel="noopener" data-amount="${a}"><b>$${a}</b><small>${a === 5 ? 'a coffee' : a === 10 ? 'coffee and a snack' : 'lunch'}</small></a>`).join('')}</div>
    <p class="fine-print">Amounts in US dollars. Opens PayPal in your browser. WhoSees never sees your payment details, and tipping doesn't change anything in the app.</p>
    <div class="foot"><button class="ghost" id="supClose">Maybe later</button></div></div>`;
  if (!d.open) d.showModal();
  d.querySelector('#supClose').onclick = () => d.close();
}

// ---------- dialogs ----------
// Android: explain the system's VPN permission prompt before it appears.
function explainVpn() {
  return new Promise((resolve) => {
    const d = $('#dlg');
    d.innerHTML = `<div class="dlg"><div class="dlg-icon"><svg viewBox="0 0 24 24" width="26" height="26"><path d="M12 3 4 6v6c0 5 3.4 8.3 8 9 4.6-.7 8-4 8-9V6l-8-3Z"/></svg></div>
      <h3>Android will ask to allow a VPN</h3>
      <p class="sub">Next, Android asks <i>"WhoSees wants to set up a VPN connection"</i>. Tap <b>OK</b>.</p>
      <ul class="why">
        <li><b>Why:</b> a VPN is the only way Android lets an app see where other apps send data.</li>
        <li><b>It stays on your phone.</b> WhoSees isn't a VPN service: nothing goes to a VPN server, and your data goes exactly where it was going.</li>
        <li>It runs only while a live view is on, and stops when you press Stop or close WhoSees. You'll see a key icon while it runs.</li>
      </ul>
      <div class="foot"><button class="ghost" id="vpnNo">Not now</button><button class="primary" id="vpnGo">Continue</button></div></div>`;
    d.showModal();
    d.querySelector('#vpnGo').onclick = async () => { state.settings = await wt.setSettings({ vpnExplained: true }); d.close(); resolve('go'); };
    d.querySelector('#vpnNo').onclick = () => { d.close(); resolve('no'); };
    d.oncancel = () => resolve('no');
  });
}

// ---------- update checks (off unless the user turns them on) ----------
const UPDATE_PAGE = { android: 'https://whosees.app/android/', win32: 'https://whosees.app/windows/', linux: 'https://whosees.app/linux/' };
const newer = (a, b) => { const x = String(a).split('.').map(Number), y = String(b).split('.').map(Number);
  for (let i = 0; i < 3; i++) { if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) > (y[i] || 0); } return false; };
const UPDATE_WHAT = `If you turn this on, once a day when you open WhoSees it asks <b>whosees.app</b> for one small file that lists the newest version. Like visiting any website, that request shows your <b>internet address</b>. Nothing else is sent: no ID, no list of your apps, nothing about what WhoSees shows you.`;
async function updatesAtLaunch() {
  if (!state.settings.updatePromptSeen) { if (!$('#dlg').open) askAboutUpdates(); return; }
  if (state.settings.updateCheck && Date.now() - (state.settings.updateLast || 0) > 20 * 3600e3) checkForUpdates(false);
}
function askAboutUpdates() {
  const d = $('#dlg');
  d.innerHTML = `<div class="dlg"><div class="dlg-icon"><svg viewBox="0 0 24 24" width="26" height="26"><path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/></svg></div>
    <h3>Check for updates?</h3>
    <p class="sub">WhoSees can let you know when a newer version is available. It's <b>off</b> unless you turn it on.</p>
    <ul class="why"><li><b>What's sent:</b> ${UPDATE_WHAT}</li>
      <li><b>What happens:</b> if there's a newer version, WhoSees shows a short note with a link to the download page. It never downloads or installs anything by itself.</li>
      <li>You can change this any time in <b>Settings</b>.</li></ul>
    <div class="foot"><button class="ghost" id="updNo">No thanks</button><button class="primary" id="updYes">Turn on update checks</button></div></div>`;
  if (!d.open) d.showModal();
  const choose = async (on) => { state.settings = await wt.setSettings({ updatePromptSeen: true, updateCheck: on }); d.close(); if (on) checkForUpdates(false); };
  d.querySelector('#updYes').onclick = () => choose(true);
  d.querySelector('#updNo').onclick = () => choose(false);
  d.oncancel = () => { choose(false); };
}
async function checkForUpdates(manual) {
  if (!wt.checkUpdate) return;
  const r = await wt.checkUpdate().catch(() => ({ ok: false }));
  if (r.ok) state.settings = await wt.setSettings({ updateLast: Date.now() });
  if (r.ok && newer(r.latest, state.version)) showUpdateNote(r);
  else if (manual) toast(r.ok ? `You have the newest version (${state.version}).` : "Couldn't check for updates right now. Try again later.", 5000);
  return r;
}
function showUpdateNote(r) {
  const n = $('#updateNote');
  n.innerHTML = `<span><b>WhoSees ${esc(r.latest)}</b> is available${r.notes ? `: ${esc(r.notes)}` : ''}.</span>
    <a class="primary sm" href="${UPDATE_PAGE[wt.platform] || 'https://whosees.app/'}" target="_blank" rel="noopener">Download</a><button class="note-x" aria-label="Close">×</button>`;
  n.hidden = false;
  n.querySelector('.note-x').onclick = () => { n.hidden = true; };
}

// Licences of everything WhoSees includes (generated by tools/notices.py)
async function openNotices() {
  const d = $('#dlg');
  const text = await fetch('notices.txt').then((r) => r.text()).catch(() => 'The licence list could not be loaded.');
  d.innerHTML = `<div class="dlg notices"><h3>Open-source licences</h3>
    <p class="sub">WhoSees is free software (GPL-3.0) built on the work of many open-source projects. Thank you to all of them.</p>
    <pre></pre><div class="foot"><button class="primary" id="noticesClose">Close</button></div></div>`;
  d.querySelector('pre').textContent = text;
  if (!d.open) d.showModal();
  d.querySelector('#noticesClose').onclick = () => d.close();
}

// Android Private DNS in hostname mode: lookups are encrypted to that server, so WhoSees can't read website names.
function explainPrivateDns(server) {
  return new Promise((resolve) => {
    const d = $('#dlg');
    d.innerHTML = `<div class="dlg"><div class="dlg-icon"><svg viewBox="0 0 24 24" width="26" height="26"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3.5 3 14.5 0 18M12 3c-3 3.5-3 14.5 0 18"/></svg></div>
      <h3>Private DNS is on</h3>
      <p class="sub">Your phone sends its website lookups privately to <b>${esc(server)}</b>. That's good for privacy, but it means WhoSees <b>can't see the names of the websites</b> your apps use.</p>
      <ul class="why">
        <li><b>You'll still see</b> which app sent data, to which company, and where in the world.</li>
        <li><b>For the full picture</b>, turn Private DNS off while you look: open <b>Settings</b> and search <b>"Private DNS"</b>, then choose <b>Off</b>.</li>
        <li>Turn it back on afterwards. WhoSees will remind you when you press Stop.</li>
      </ul>
      <label class="check"><input type="checkbox" id="dontAsk"> Don't show this again</label>
      <div class="foot"><button class="ghost" id="pdSettings">Open Settings</button><button class="primary" id="pdGo">Start anyway</button></div></div>`;
    d.showModal();
    let settled = false;
    const done = async (v) => {
      if (settled) return; settled = true;
      if (v === 'go' && d.querySelector('#dontAsk').checked) state.settings = await wt.setSettings({ privateDnsNoted: true });
      d.close(); resolve(v);
    };
    d.querySelector('#pdGo').onclick = () => done('go');
    d.querySelector('#pdSettings').onclick = () => { done('settings'); wt.openNetworkSettings && wt.openNetworkSettings(); };
    d.oncancel = () => done('cancel');
  });
}

// Shown before the system's password window, so it's clear which password and why.
function explainPassword() {
  return new Promise((resolve) => {
    const d = $('#dlg');
    d.innerHTML = `<div class="dlg"><div class="dlg-icon"><svg viewBox="0 0 24 24" width="26" height="26"><rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg></div>
      ${wt.platform === 'win32'
        ? `<h3>Deep mode needs administrator permission</h3>
      <p class="sub">Next, Windows will ask <i>"Do you want to allow this app to make changes to your device?"</i> for <b>whosees-agent</b>. Click <b>Yes</b>. If your account isn't an administrator, Windows will ask for an administrator's password instead.</p>`
        : `<h3>Deep mode needs your password</h3>
      <p class="sub">Next, a system password window will open. Enter the <b>password you use to log in to this computer</b>${state.user ? ` (account <b>${esc(state.user)}</b>)` : ''}.</p>`}
      <ul class="why">
        <li><b>Why:</b> to see every connection and website names, WhoSees reads ${wt.platform === 'win32' ? 'Windows network events' : 'the address on each network packet'}${FEATURES.blocking ? ', and to block sites it adds firewall rules' : ''}. Your system only allows that with administrator approval.</li>
        <li><b>${wt.platform === 'win32' ? 'Windows handles the approval, not WhoSees.' : 'Your password goes to your system, not to WhoSees.'}</b> WhoSees never sees or stores a password.</li>
        <li>It's asked once each time you press Start. The access ends when you press Stop.</li>
        <li>If the ${wt.platform === 'win32' ? 'permission' : 'password'} window doesn't appear, it may be behind this one. Check your taskbar.</li>
      </ul>
      <label class="check"><input type="checkbox" id="dontAsk"> Don't show this again</label>
      <div class="foot"><button class="ghost" id="useStd">Use Standard mode</button><button class="primary" id="goDeep">Continue</button></div></div>`;
    d.showModal();
    let settled = false;
    const done = async (v) => {
      if (settled) return; settled = true;
      if (v === 'deep' && d.querySelector('#dontAsk').checked) state.settings = await wt.setSettings({ deepExplained: true });
      d.close(); resolve(v);
    };
    d.querySelector('#goDeep').onclick = () => done('deep');
    d.querySelector('#useStd').onclick = () => done('standard');
    d.oncancel = () => done('cancel');
  });
}

function deepFailed(info) {
  const d = $('#dlg');
  const cancelled = info.code === 126;
  d.innerHTML = `<div class="dlg"><div class="dlg-icon warn"><svg viewBox="0 0 24 24" width="26" height="26"><path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/></svg></div>
    <h3>Deep mode didn't start</h3>
    <p class="sub">${wt.platform === 'android'
      ? 'Android\'s VPN permission was declined, or another VPN app is active (only one can run at a time). Press <b>Try again</b> and tap <b>OK</b> when Android asks.'
      : cancelled && wt.platform === 'win32'
      ? 'The Windows permission prompt was closed or <b>No</b> was clicked. Press <b>Try again</b> and click <b>Yes</b> when Windows asks.'
      : cancelled
      ? `The password window was closed, or the password wasn't accepted. Use the <b>password you log in to this computer with</b>${state.user ? ` (account <b>${esc(state.user)}</b>)` : ''}, not a website or Wi-Fi password.`
      : 'Your system didn\'t allow WhoSees to run with administrator rights. Your account needs to be an administrator (in the <i>wheel</i> group on Fedora). If no password window appeared at all, the system\'s password service may be stuck: logging out and back in fixes that.'}</p>
    ${wt.platform === 'android' ? '' : `<p class="sub">WhoSees is showing the <b>Standard view</b> for now: apps, companies and places, without website names or tracker labels.</p>`}
    <div class="foot"><button class="ghost" id="keepStd">Keep Standard view</button><button class="primary" id="retryDeep">Try again</button></div></div>`;
  if (d.open) d.close();
  d.showModal();
  d.querySelector('#keepStd').onclick = () => d.close();
  d.querySelector('#retryDeep').onclick = async () => { d.close(); await wt.stop(); setRunning(false); start(); }; // a restart, not a Stop: blocks stay
}

function openLocation() {
  const d = $('#dlg');
  d.innerHTML = `<div class="dlg"><h3>Where are you?</h3>
    <p class="sub">Arcs on the map start from here. Pick the nearest city. This stays on your ${DEVICE} and nothing is looked up online.</p>
    <div class="search"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg><input id="cityQ" placeholder="Type a city" spellcheck="false" autofocus></div>
    <div class="results list" id="cityR"></div>
    <div class="foot"><button class="ghost" id="cityCancel">Cancel</button></div></div>`;
  d.showModal();
  const q = d.querySelector('#cityQ'), r = d.querySelector('#cityR');
  let seq = 0, hits = [];
  q.oninput = async () => {
    const my = ++seq;
    const res = q.value.trim().length >= 2 ? await wt.findCity(q.value) : [];
    if (my !== seq) return;
    hits = res;
    r.innerHTML = res.map((c, i) => `<div class="row" data-i="${i}"><div class="ic cc sm">${esc(c.country)}</div><div class="main"><div class="t">${esc(c.city)}</div><div class="s">${esc([c.region, countryName(c.country)].filter(Boolean).join(', '))}</div></div></div>`).join('')
      || (q.value.trim().length >= 2 ? '<div class="empty">No city found</div>' : '');
  };
  r.onclick = async (e) => {
    const row = e.target.closest('[data-i]'); if (!row) return;
    const h = hits[+row.dataset.i];
    state.settings = await wt.setSettings({ home: h, homeGuessed: false });
    setHome(h); d.close();
  };
  d.querySelector('#cityCancel').onclick = () => d.close();
  q.focus();
}

function openSettings() {
  const d = $('#dlg');
  const s = state.settings;
  const theme = s.theme || 'system';
  d.innerHTML = `<div class="dlg"><h3>Settings</h3><p class="sub">WhoSees only runs while a live view is on. Nothing about you is sent anywhere.</p>
    <div class="opt"><div><b>Appearance</b><small>Follow the system, or choose</small></div>
      <div class="seg" id="themeSeg">${['system', 'dark', 'light'].map((t) => `<button data-t="${t}" class="${t === theme ? 'on' : ''}">${t[0].toUpperCase() + t.slice(1)}</button>`).join('')}</div></div>
    <div class="opt"><div><b>Your location</b><small>${s.home ? esc(`${s.home.city}, ${countryName(s.home.country)}`) : 'Not set'}</small></div><button class="ghost" id="setLoc">Change</button></div>
    ${['linux', 'win32'].includes(wt.platform) ? `<div class="opt"><div><b>Deep mode</b><small>Shows website names and tracker labels, and catches every connection. Asks for ${wt.platform === 'win32' ? 'administrator permission' : 'your password'} each time you press Start. Only reads where data goes, never what's inside it.</small></div><button class="switch ${s.deep ? 'on' : ''}" id="deepSw" aria-label="Deep mode"></button></div>` : ''}
    <div class="opt"><div><b>Report</b><small>${session.started ? 'Save a PDF of what this live view found. Made on this ' + DEVICE + ', never uploaded.' : 'After a live view, save a PDF of what it found.'}</small></div><button class="ghost" id="setReport" ${session.started ? '' : 'disabled'}>Save PDF</button></div>
    <div class="opt"><div><b>Support WhoSees</b><small>Free, with every feature. If it's useful, you can buy me a coffee.</small></div><button class="ghost" data-support>Support</button></div>
    <div class="opt"><div><b>Threat alerts</b><small>Warn about dangerous websites, malicious servers and suspicious behaviour</small></div><button class="switch ${s.alerts !== false ? 'on' : ''}" id="alertSw" aria-label="Threat alerts"></button></div>
    <div class="opt"><div><b>Include local network</b><small>Also list traffic to devices in your home (printers, NAS, TV)</small></div><button class="switch ${s.lan ? 'on' : ''}" id="lanSw" aria-label="Include local network"></button></div>
    <div class="opt"><div><b>Check for updates</b><small>${s.updateCheck ? 'On: once a day when you open WhoSees.' : 'Off.'} Only asks whosees.app for the newest version number; your internet address is seen, nothing else.${s.updateLast ? ` Last checked ${new Date(s.updateLast).toLocaleDateString()}.` : ''}</small></div>
      <div style="display:flex;gap:8px;align-items:center"><button class="ghost sm" id="updNow">Check now</button><button class="switch ${s.updateCheck ? 'on' : ''}" id="updSw" aria-label="Check for updates"></button></div></div>
    <div class="opt"><div><b>About</b><small>WhoSees ${esc(state.version || '')} · GPL-3.0 · IP location by <u>DB-IP.com</u> (CC BY 4.0) · Tracker data: AdGuard companiesdb / WhoTracks.me (CC BY-SA 4.0) · Threat data: Hagezi Threat Intelligence Feeds (GPL-3.0), abuse.ch Feodo Tracker &amp; SSL Blacklist (CC0) · Map © OpenStreetMap contributors, Protomaps · <a href="#" class="link" data-notices>Open-source licences</a></small></div></div>
    <div class="foot"><button class="primary" id="done">Done</button></div></div>`;
  d.showModal();
  d.querySelector('#themeSeg').onclick = async (e) => {
    const b = e.target.closest('button'); if (!b) return;
    for (const x of d.querySelectorAll('#themeSeg button')) x.classList.toggle('on', x === b);
    state.settings = await wt.setSettings({ theme: b.dataset.t });
    applyTheme(b.dataset.t);
  };
  d.querySelector('#lanSw').onclick = async (e) => {
    const on = !e.currentTarget.classList.contains('on');
    e.currentTarget.classList.toggle('on', on);
    state.settings = await wt.setSettings({ lan: on });
    if (state.running) toast('Applies to the next live view');
  };
  d.querySelector('#deepSw')?.addEventListener('click', async (e) => {
    const on = !e.currentTarget.classList.contains('on');
    e.currentTarget.classList.toggle('on', on);
    state.settings = await wt.setSettings({ deep: on });
    syncDeepChip();
    if (state.running) toast('Applies to the next live view');
  });
  d.querySelector('#alertSw').onclick = async (e) => {
    const on = !e.currentTarget.classList.contains('on');
    e.currentTarget.classList.toggle('on', on);
    state.settings = await wt.setSettings({ alerts: on });
  };
  d.querySelector('#updSw').onclick = async (e) => {
    const on = !e.currentTarget.classList.contains('on');
    e.currentTarget.classList.toggle('on', on);
    state.settings = await wt.setSettings({ updateCheck: on, updatePromptSeen: true });
  };
  d.querySelector('#updNow').onclick = () => { d.close(); checkForUpdates(true); };
  d.querySelector('#setLoc').onclick = () => { d.close(); openLocation(); };
  d.querySelector('#setReport').onclick = () => { d.close(); openReport(); };
  d.querySelector('#done').onclick = () => d.close();
}

let toastT;
function toast(msg, ms = 3500) {
  const t = $('#toast'); t.textContent = msg; t.hidden = false;
  clearTimeout(toastT); toastT = setTimeout(() => (t.hidden = true), ms);
}
