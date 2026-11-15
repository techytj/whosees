// Session report: one self-contained, printable HTML document built from what this live view saw.
// It becomes a PDF on this device (desktop: Chromium's PDF printer; Android: the system print service).
// Nothing in it is uploaded anywhere.
import { CATEGORIES, TRACKING, bytes, countryName, placeName } from './model.js';

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
// a web address as printable text (no link: the report loads and links nothing), breaking only after slashes
const urlText = (u) => esc(String(u || '').replace(/^https?:\/\/(www\.)?/, '').replace(/\/$/, '')).replace(/\//g, '/<wbr>');
const plural = (n, one, many = one + 's') => `${n} ${n === 1 ? one : many}`;
const pct = (a, b) => (b > 0 ? Math.round((100 * a) / b) : 0);
const CAT_COLOR = { tracker: '#ff5c7a', ads: '#ffb547', analytics: '#ff8a4c', social: '#f472d0', messaging: '#4ade80',
  streaming: '#a78bfa', cdn: '#2dd4bf', cloud: '#60a5fa', other: '#94a3b8', local: '#cbd5e1' };
export const MAX_ROWS = 5000; // the connection list stops here (a very long session would otherwise be hundreds of pages)

export function duration(ms) {
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 60) return `${s} s`;
  const m = Math.round(s / 60);
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, '0')} min`;
}
const when = (ts) => new Date(ts).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
const clock = (ts) => new Date(ts).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
const hms = (ts) => { const d = new Date(ts), p = (n) => String(n).padStart(2, '0'); return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`; };
const DEVICES = { linux: 'Linux computer', win32: 'Windows computer', android: 'Android phone' };
const MODES = { standard: 'Standard', deep: 'Deep', vpn: 'Full (Android VPN)' };

/** Privacy grade for one app: the same rule the app's detail panel uses. */
export function grade(s, a) {
  const places = [...a.places].map((k) => s.places.get(k)).filter((p) => p && p.scope === 'internet');
  const d = s.dataFor([...a.conns]);
  const tracking = places.filter((p) => TRACKING.has(s.topCat(p.cats)));
  const unenc = [...a.conns].map((id) => s.conns.get(id)).filter((c) => c && !c.encrypted && c.scope === 'internet').length;
  const g = d.seen.some((x) => ['location', 'email', 'phone', 'advertising-id', 'password'].includes(x.kind)) || tracking.length >= 3 ? 'Poor'
    : tracking.length || unenc ? 'Fair' : 'Good';
  return { grade: g, places, tracking, unenc, data: d };
}

// ---------- the numbers ----------
export function collect(s, { rules = [], home = null, now = Date.now() } = {}) {
  const conns = [...s.conns.values()];
  const net = conns.filter((c) => c.scope === 'internet');
  const sent = (c) => c.ss || 0, recv = (c) => c.sr || 0;
  const bump = (m, k, n = 1) => { if (k != null) m.set(k, (m.get(k) || 0) + n); };

  const companies = new Map();
  for (const c of net) {
    const name = c.owner || 'Unknown company';
    let x = companies.get(name);
    if (!x) companies.set(name, x = { name, cats: new Map(), apps: new Map(), countries: new Set(), places: new Set(), sites: new Map(), sent: 0, recv: 0, n: 0, plain: 0, blocked: 0 });
    bump(x.cats, c.category); bump(x.apps, c.app.name); bump(x.sites, c.site || c.host);
    if (c.geo?.country) x.countries.add(c.geo.country);
    x.places.add(placeName(c.geo)); x.sent += sent(c); x.recv += recv(c); x.n++;
    if (!c.encrypted) x.plain++;
    if (c.blocked) x.blocked++;
  }
  for (const x of companies.values()) x.cat = s.topCat(x.cats);

  const countries = new Map();
  for (const p of s.places.values()) {
    if (p.scope !== 'internet') continue;
    const cc = p.geo?.country || '??';
    let x = countries.get(cc);
    if (!x) countries.set(cc, x = { cc, name: cc === '??' ? 'Unknown location' : countryName(cc), cities: new Map(), companies: new Set(), apps: new Set(), sent: 0, recv: 0, n: 0, tracking: 0 });
    bump(x.cities, p.geo?.city ? p.geo.city.split(' (')[0] : null, p.sent);
    for (const o of p.owners.keys()) x.companies.add(o);
    for (const id of p.apps) x.apps.add(s.apps.get(id)?.name);
    x.sent += p.sent; x.recv += p.recv; x.n += p.conns.size;
    if (TRACKING.has(s.topCat(p.cats))) x.tracking++;
  }

  const apps = [...s.apps.values()].map((a) => {
    const g = grade(s, a);
    const mine = [...a.conns].map((id) => s.conns.get(id)).filter(Boolean);
    const onNet = mine.filter((c) => c.scope === 'internet');
    const owners = new Map(), trackers = new Set();
    for (const c of onNet) {
      const o = c.owner || 'Unknown company';
      const x = owners.get(o) || { name: o, sent: 0, n: 0, cat: c.category };
      x.sent += sent(c); x.n++; if (TRACKING.has(c.category)) { x.cat = c.category; trackers.add(o); }
      owners.set(o, x);
    }
    return { a, ...g, owners: [...owners.values()].sort((x, y) => y.sent - x.sent || y.n - x.n), trackers: [...trackers],
      sites: s.topSites(a.sites, 40), countries: [...a.countries], n: mine.length, nNet: onNet.length,
      local: onNet.length === 0, blocked: mine.filter((c) => c.blocked).length };
  }).sort((x, y) => y.a.sent - x.a.sent || y.n - x.n);

  const trackers = [...companies.values()].filter((x) => TRACKING.has(x.cat)).sort((x, y) => y.n - x.n);
  const byCat = new Map();
  for (const c of net) bump(byCat, c.category, sent(c));
  const totalSent = s.totals.sent || net.reduce((t, c) => t + sent(c), 0);
  const totalRecv = s.totals.recv || net.reduce((t, c) => t + recv(c), 0);
  const plain = net.filter((c) => !c.encrypted);
  const alerts = []; const seenKey = new Set();
  for (const a of [...s.alerts].reverse()) { const k = a.block ? `${a.block.kind}|${a.block.value}|${a.kind}` : a.key; if (!seenKey.has(k)) { seenKey.add(k); alerts.push(a); } }
  const stopped = Object.values(s.blockedHits || {}).reduce((t, n) => t + n, 0);
  const blockedConns = conns.filter((c) => c.blocked);
  const blockedPlaces = [...s.places.values()].map((p) => ({ p, n: s.stoppedAt(p) })).filter((x) => x.n > 0);
  const abroad = home?.country ? [...countries.values()].filter((x) => x.cc !== home.country).reduce((t, x) => t + x.sent, 0) : null;
  const ended = s.ended || now;
  return {
    started: s.started || now, ended, running: !s.ended, mode: s.mode, conns, net, companies: [...companies.values()].sort((x, y) => y.sent - x.sent || y.n - x.n),
    countries: [...countries.values()].sort((x, y) => y.sent - x.sent || y.n - x.n), apps, trackers, byCat, totalSent, totalRecv,
    plain, alerts, rules, stopped, blockedConns, blockedPlaces, abroad, home,
    data: s.dataFor(net.map((c) => c.id)), timeline: s.rateLog?.length ? s.rateLog : (s.history || []).map((v, i, h) => [ended - (h.length - i) * 1000, v]),
    places: [...s.places.values()].filter((p) => p.scope === 'internet' && p.lat != null),
  };
}

// ---------- findings: the few sentences that matter most ----------
export function findings(r, device) {
  const out = [];
  const netApps = r.apps.filter((x) => !x.local);
  if (!r.net.length) {
    out.push(['info', `No app on your ${device} sent anything to the internet during this live view.`]);
    return out;
  }
  if (r.trackers.length) {
    out.push(['warn', `<b>${r.trackers.length} of the ${r.companies.length} companies</b> your apps talked to are trackers or advertisers: ${esc(r.trackers.slice(0, 5).map((t) => t.name).join(', '))}${r.trackers.length > 5 ? ' and others' : ''}.`]);
    const worst = [...netApps].sort((x, y) => y.trackers.length - x.trackers.length)[0];
    if (worst?.trackers.length) out.push([worst.trackers.length >= 3 ? 'high' : 'warn', `<b>${esc(worst.a.name)}</b> contacted the most trackers: ${plural(worst.trackers.length, 'tracking company', 'tracking companies')} (${esc(worst.trackers.slice(0, 4).join(', '))}${worst.trackers.length > 4 ? ', …' : ''}).`]);
  } else out.push(['good', 'No known tracking or advertising companies were contacted.']);
  const top = netApps[0];
  if (top && r.totalSent > 0 && top.a.sent > 0) out.push(['info', `<b>${esc(top.a.name)}</b> sent the most data: ${bytes(top.a.sent)} (${pct(top.a.sent, r.totalSent)}% of everything sent).`]);
  if (r.countries.length && !r.totalSent) {
    out.push(['info', `Your apps connected to servers in <b>${plural(r.countries.length, 'country', 'countries')}</b> (${esc(r.countries.slice(0, 5).map((c) => c.name).join(', '))}), but sent no data yet.`]);
  } else if (r.countries.length) {
    const c0 = r.countries[0];
    out.push(['info', `Your data went to <b>${plural(r.countries.length, 'country', 'countries')}</b>. The most went to ${esc(c0.name)} (${pct(c0.sent, r.totalSent)}%).` +
      (r.abroad != null && r.home ? ` ${pct(r.abroad, r.totalSent)}% left ${esc(countryName(r.home.country))}.` : '')]);
  }
  const seen = r.data.seen.filter((d) => d.kind !== 'website');
  if (seen.length) out.push(['high', `Readable (unencrypted) traffic contained: <b>${esc(seen.map((d) => d.label).join(', '))}</b>.`]);
  if (r.plain.length) {
    const who = [...new Set(r.plain.map((c) => c.app.name))];
    out.push(['warn', `<b>${plural(r.plain.length, 'connection')}</b> ${r.plain.length === 1 ? 'was' : 'were'} not encrypted (${esc(who.slice(0, 4).join(', '))}${who.length > 4 ? ', …' : ''}). Anyone on the network path could read ${r.plain.length === 1 ? 'it' : 'them'}.`]);
  } else out.push(['good', 'Every internet connection was encrypted.']);
  const hi = r.alerts.filter((a) => a.severity === 'high');
  if (r.alerts.length) out.push([hi.length ? 'high' : 'warn', `<b>${plural(r.alerts.length, 'threat alert')}</b>${hi.length ? `, ${hi.length} serious` : ''}: ${esc(r.alerts.slice(0, 2).map((a) => a.title).join('; '))}${r.alerts.length > 2 ? '; …' : ''}.`]);
  else out.push(['good', 'No threats were found: no known malicious websites or servers, and nothing behaved suspiciously.']);
  if (r.blockedConns.length || r.stopped) out.push(['good', `WhoSees blocked <b>${plural(r.blockedConns.length || r.stopped, 'attempt')}</b> to reach places on your block list.`]);
  if (r.mode === 'standard') out.push(['info', 'This was a Standard-mode view: very short connections can be missed and some website names may be missing. Deep mode catches every connection.']);
  return out;
}

// ---------- small static charts (a PDF has no hover: values are printed beside each bar) ----------
function bars(items, { fmt = bytes, color = 'var(--accent)', max } = {}) {
  if (!items.length) return '';
  const W = 640, row = 24, lw = 190, vw = 74, h = items.length * row;
  const m = max || Math.max(1, ...items.map((i) => i.value));
  const bw = W - lw - vw - 12;
  return `<svg class="chart" viewBox="0 0 ${W} ${h}" width="100%" role="img">${items.map((it, i) => {
    const y = i * row, w = Math.max(2, (it.value / m) * bw), r = Math.min(4, w / 2);
    const c = it.color || color;
    return `<text x="0" y="${y + 15.5}" class="bl">${esc(it.label.length > 30 ? it.label.slice(0, 29) + '…' : it.label)}</text>
      <rect x="${lw}" y="${y + 6}" width="${bw}" height="12" class="track"/>
      <path d="M${lw} ${y + 6}h${w - r}a${r} ${r} 0 0 1 ${r} ${r}v${12 - 2 * r}a${r} ${r} 0 0 1 -${r} ${r}h-${w - r}z" fill="${c}"/>
      <text x="${W}" y="${y + 15.5}" class="bv" text-anchor="end">${esc(fmt(it.value))}</text>`;
  }).join('')}</svg>`;
}
function timeline(points) {
  if (!points || points.length < 3) return '';
  const W = 640, H = 120, t0 = points[0][0], t1 = points[points.length - 1][0], span = Math.max(1, t1 - t0);
  const m = Math.max(1024, ...points.map((p) => p[1]));
  const xy = points.map(([t, v]) => [((t - t0) / span) * W, H - 18 - (v / m) * (H - 30)]);
  const line = xy.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`).join('');
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" width="100%" role="img">
    <line x1="0" x2="${W}" y1="${H - 18}" y2="${H - 18}" class="axis"/>
    <line x1="0" x2="${W}" y1="12" y2="12" class="grid"/>
    <text x="0" y="9" class="bv">${esc(bytes(m))}/s</text>
    <path d="${line}L${W} ${H - 18}L0 ${H - 18}Z" class="area"/><path d="${line}" class="line"/>
    <text x="0" y="${H - 3}" class="bv">${esc(clock(t0))}</text><text x="${W}" y="${H - 3}" class="bv" text-anchor="end">${esc(clock(t1))}</text></svg>`;
}
function catShare(byCat, total) {
  const items = [...byCat.entries()].filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]);
  if (!items.length || !total) return '';
  const W = 640; let x = 0;
  const sum = items.reduce((t, [, v]) => t + v, 0);
  const segs = items.map(([k, v]) => { const w = (v / sum) * W; const s = `<rect x="${(x + (x ? 1 : 0)).toFixed(1)}" y="0" width="${Math.max(0.5, w - (x ? 1 : 0) - 1).toFixed(1)}" height="14" rx="2" fill="${CAT_COLOR[k] || CAT_COLOR.other}"/>`; x += w; return s; }).join('');
  return `<svg class="chart" viewBox="0 0 ${W} 14" width="100%" role="img">${segs}</svg>
    <div class="legend">${items.map(([k, v]) => `<span><i style="background:${CAT_COLOR[k] || CAT_COLOR.other}"></i>${esc(CATEGORIES[k]?.label || k)} <b>${pct(v, sum)}%</b></span>`).join('')}</div>`;
}

// ---------- map picture (an offscreen map, never the one on screen) ----------
/** Draws every destination with an arc from home; returns a JPEG data URL, or null if the map can't render. */
export async function snapshotMap(maplibregl, style, places, home, { width = 1600, height = 900 } = {}) {
  if (!home || !places.length) return null;
  const box = document.createElement('div');
  box.style.cssText = `position:fixed;left:-${width + 200}px;top:0;width:${width}px;height:${height}px;pointer-events:none`;
  document.body.appendChild(box);
  let map;
  try {
    map = new maplibregl.Map({ container: box, style, interactive: false, attributionControl: false, fadeDuration: 0, pixelRatio: 1,
      canvasContextAttributes: { preserveDrawingBuffer: true }, preserveDrawingBuffer: true, renderWorldCopies: true, center: [home.lon, home.lat], zoom: 1 });
    const unwrap = (lon) => { while (lon - home.lon > 180) lon -= 360; while (lon - home.lon < -180) lon += 360; return lon; };
    const pts = [[home.lon, home.lat], ...places.map((p) => [unwrap(p.lon), p.lat])];
    const lons = pts.map((p) => p[0]), lats = pts.map((p) => p[1]);
    await new Promise((res) => map.once('load', res));
    map.fitBounds([[Math.min(...lons), Math.max(-60, Math.min(...lats))], [Math.max(...lons), Math.min(78, Math.max(...lats))]], { padding: { top: 90, bottom: 90, left: 120, right: 120 }, maxZoom: 4.2, duration: 0 });
    await new Promise((res) => { const t = setTimeout(res, 8000); map.once('idle', () => { clearTimeout(t); res(); }); });
    const out = document.createElement('canvas'); out.width = width; out.height = height;
    const g = out.getContext('2d');
    g.drawImage(map.getCanvas(), 0, 0, width, height);
    const a = map.project([home.lon, home.lat]);
    const maxB = Math.max(1, ...places.map((p) => p.sent));
    const sorted = [...places].sort((x, y) => x.sent - y.sent); // big ones on top
    for (const p of sorted) {
      const b = map.project([unwrap(p.lon), p.lat]);
      const dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy);
      if (len < 1) continue;
      let nx = -dy / len, ny = dx / len; if (ny > 0) { nx = -nx; ny = -ny; }
      const k = Math.min(len * 0.28, 260), cx = (a.x + b.x) / 2 + nx * k, cy = (a.y + b.y) / 2 + ny * k;
      const col = CAT_COLOR[p.cat] || CAT_COLOR.other;
      g.strokeStyle = col; g.globalAlpha = 0.55; g.lineWidth = 2;
      g.beginPath(); g.moveTo(a.x, a.y); g.quadraticCurveTo(cx, cy, b.x, b.y); g.stroke();
      g.globalAlpha = 1;
      const r = 4 + 10 * Math.sqrt(p.sent / maxB);
      g.fillStyle = col; g.beginPath(); g.arc(b.x, b.y, r, 0, Math.PI * 2); g.fill();
      g.lineWidth = 2; g.strokeStyle = '#06080d'; g.stroke();
    }
    // labels for the biggest destinations
    g.font = '600 20px Archivo, Arial, sans-serif'; g.textBaseline = 'middle';
    for (const p of [...places].sort((x, y) => y.sent - x.sent).slice(0, 6)) {
      const b = map.project([unwrap(p.lon), p.lat]);
      const r = 4 + 10 * Math.sqrt(p.sent / maxB);
      const t = p.label; if (!t) continue;
      g.lineWidth = 5; g.strokeStyle = '#06080d'; g.strokeText(t, b.x + r + 6, b.y);
      g.fillStyle = '#eceae4'; g.fillText(t, b.x + r + 6, b.y);
    }
    // home
    g.fillStyle = '#ff5b1f'; g.fillRect(a.x - 9, a.y - 9, 18, 18);
    g.lineWidth = 3; g.strokeStyle = '#ff5b1f'; g.beginPath(); g.arc(a.x, a.y, 22, 0, Math.PI * 2); g.stroke();
    return out.toDataURL('image/jpeg', 0.9); // a JPEG keeps the report small
  } catch (e) {
    console.log('report map failed', e?.message || e);
    return null;
  } finally {
    try { map?.remove(); } catch {}
    box.remove();
  }
}

/** Font files as data: URLs, so the PDF printer needs nothing from outside the document. */
export async function fontCss() {
  const load = async (f) => {
    const b = await (await fetch(new URL(`fonts/${f}`, document.baseURI))).blob();
    return await new Promise((res) => { const r = new FileReader(); r.onload = () => res(r.result); r.readAsDataURL(b); });
  };
  try {
    const [a, m, m5] = await Promise.all(['archivo.woff2', 'plex-mono.woff2', 'plex-mono-500.woff2'].map(load));
    return `@font-face{font-family:"Archivo";src:url(${a}) format("woff2-variations");font-weight:100 900;font-stretch:62% 125%}
@font-face{font-family:"Plex Mono";src:url(${m}) format("woff2");font-weight:400}
@font-face{font-family:"Plex Mono";src:url(${m5}) format("woff2");font-weight:500 700}`;
  } catch { return ''; }
}

export function reportFileName(ts = Date.now()) {
  const d = new Date(ts), p = (n) => String(n).padStart(2, '0');
  return `WhoSees report ${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}${p(d.getMinutes())}.pdf`;
}
/** Letter in North America and a few others, A4 everywhere else. */
export function paperFor(locale = navigator.language || 'en-US') {
  const region = (locale.split(/[-_]/)[1] || '').toUpperCase();
  return ['US', 'CA', 'MX', 'PH', 'CL', 'CO', 'VE', 'GT', 'PR', 'CR', 'PA', 'SV', 'DO', 'NI', 'HN'].includes(region) ? 'letter' : 'a4';
}

// ---------- the document ----------
export function buildReport(s, ctx) {
  const { platform = 'linux', version = '', theme = 'dark', mapImage = null, fonts = '', paper = 'letter', home = null, rules = [], now = Date.now() } = ctx;
  const device = platform === 'android' ? 'phone' : 'computer';
  const r = collect(s, { rules, home, now });
  const F = findings(r, device);
  const netApps = r.apps.filter((x) => !x.local);
  const [pw, ph] = paper === 'a4' ? ['210mm', '297mm'] : ['8.5in', '11in'];
  const title = `What your ${device} sent, and who received it`;
  const lede = r.net.length && !r.totalSent
    ? `In ${duration(r.ended - r.started)}, ${plural(netApps.length, 'app')} on your ${device} connected to <b>${plural(r.companies.length, 'company', 'companies')}</b> in <b>${plural(r.countries.length, 'country', 'countries')}</b> but sent no data yet.`
    : r.net.length
    ? `In ${duration(r.ended - r.started)}, ${plural(netApps.length, 'app')} on your ${device} sent <b>${bytes(r.totalSent)}</b> to <b>${plural(r.companies.length, 'company', 'companies')}</b> in <b>${plural(r.countries.length, 'country', 'countries')}</b>.` +
      (r.trackers.length ? ` <b class="hot">${plural(r.trackers.length, 'of them was a tracker or advertiser', 'of them were trackers or advertisers')}</b>.` : ' None of them were known trackers or advertisers.')
    : `During this ${duration(r.ended - r.started)} live view, nothing on your ${device} sent data to the internet.`;
  const tile = (label, value, sub = '', hot = false) => `<div class="tile${hot ? ' hot' : ''}"><label>${label}</label><strong>${value}</strong>${sub ? `<small>${sub}</small>` : ''}</div>`;
  const chip = (k) => `<span class="chip"><i style="background:${CAT_COLOR[k] || CAT_COLOR.other}"></i>${esc(CATEGORIES[k]?.label || k)}</span>`;
  const gradeTag = (g) => `<span class="grade g-${g.toLowerCase()}">${g}</span>`;
  const more = (list, n, fmt) => list.slice(0, n).map(fmt).join('') + (list.length > n ? `<li class="more">+ ${list.length - n} more</li>` : '');
  let secN = 0;
  const NEW_PAGE = new Set(['apps', 'companies', 'connections']); // the long sections start on a fresh page, the rest flow on
  const sec = (id, name, intro = '') => `<h2 id="${id}"${NEW_PAGE.has(id) ? ' class="np"' : ''}><span class="k">${String(++secN).padStart(2, '0')}</span>${esc(name)}</h2>${intro ? `<p class="intro">${intro}</p>` : ''}`;

  const cover = `<section class="cover">
    <div class="cv-top"><span class="brand">${LOGO}WhoSees</span><span class="mono">PRIVACY REPORT · ${esc(when(r.ended).toUpperCase())}</span></div>
    <h1>${esc(title)}</h1>
    <p class="lede">${lede}</p>
    ${mapImage ? `<figure class="cv-map"><img src="${mapImage}" alt="Map of where your data went"><figcaption>${[...new Set(r.places.map((p) => s.topCat(p.cats)))].map(chip).join('')}<span class="chip"><i class="home"></i>You (${esc(home ? home.city : 'your location')})</span></figcaption></figure>` : ''}
    <div class="tiles">
      ${tile('Data sent', bytes(r.totalSent))}${tile('Data received', bytes(r.totalRecv))}
      ${tile('Apps online', netApps.length, `of ${r.apps.length} seen`)}${tile('Companies', r.companies.length)}
      ${tile('Countries', r.countries.length)}${tile('Trackers &amp; ads', r.trackers.length, 'companies', r.trackers.length > 0)}
      ${tile('Threat alerts', r.alerts.length, r.alerts.length ? `${r.alerts.filter((a) => a.severity === 'high').length} serious` : 'none found', r.alerts.length > 0)}
      ${tile('Not encrypted', r.plain.length, 'connections', r.plain.length > 0)}
    </div>
    <dl class="cv-meta">
      <div><dt>Live view</dt><dd>${esc(when(r.started))} – ${esc(clock(r.ended))}${r.running ? ' (still running)' : ''}<br>${esc(duration(r.ended - r.started))}</dd></div>
      <div><dt>Device</dt><dd>${esc(DEVICES[platform] || 'Computer')}</dd></div>
      <div><dt>Mode</dt><dd>${esc(MODES[r.mode] || r.mode)}</dd></div>
      <div><dt>Your location</dt><dd>${home ? esc(`${home.city}, ${countryName(home.country)}`) : 'Not set'}</dd></div>
    </dl>
    <p class="cv-foot">Made on this ${device} by WhoSees ${esc(version)}. Nothing in this report was uploaded or shared. · whosees.app</p>
  </section>`;

  const findingsSec = `${sec('findings', 'Key findings')}
    <ul class="findings">${F.map(([lvl, t]) => `<li class="f-${lvl}"><span class="dot"></span><span>${t}</span></li>`).join('')}</ul>
    ${r.totalSent ? `<h3>Where your data went, by kind of company</h3>${catShare(r.byCat, r.totalSent)}` : ''}
    ${r.timeline.length > 2 && r.timeline.some((p) => p[1] > 0) ? `<h3>Data sent over time</h3>${timeline(r.timeline)}` : ''}
    <div class="howto"><h3>How to read this report</h3>
      <p><b>Seen</b> means WhoSees read it in traffic that wasn't encrypted. <b>Likely</b> means it's what that kind of company usually receives: the traffic was encrypted, so its contents stay private between the app and the server, and WhoSees can only see who received it. <b>Could include</b> (Android) means the app is allowed to read that information and talks to tracking or advertising companies.</p>
      <p><b>Privacy grade</b> per app: <i>Good</i> = no trackers, everything encrypted. <i>Fair</i> = some trackers or unencrypted traffic. <i>Poor</i> = three or more trackers, or personal details seen in readable traffic.</p></div>`;

  const appsSec = `${sec('apps', 'Apps', `Every app that used the network during this live view, the most data first.`)}
    ${netApps.length ? bars(netApps.slice(0, 12).map((x) => ({ label: x.a.name, value: x.a.sent }))) : ''}
    <table class="t"><thead><tr><th>App</th><th>Grade</th><th class="n">Sent</th><th class="n">Received</th><th class="n">Companies</th><th class="n">Countries</th><th class="n">Trackers</th><th class="n">Not encrypted</th></tr></thead><tbody>
    ${r.apps.map((x) => `<tr><td><b>${esc(x.a.name)}</b>${x.local ? ' <span class="muted">(local network only)</span>' : ''}</td><td>${x.local ? '–' : gradeTag(x.grade)}</td><td class="n">${bytes(x.a.sent)}</td><td class="n">${bytes(x.a.recv)}</td><td class="n">${x.owners.length}</td><td class="n">${x.countries.length}</td><td class="n${x.trackers.length ? ' hot' : ''}">${x.trackers.length}</td><td class="n${x.unenc ? ' hot' : ''}">${x.unenc}</td></tr>`).join('')}
    </tbody></table>
    ${netApps.map((x) => {
      const d = x.data, kinds = [...d.seen.map((k) => ['seen', k]), ...d.could.map((k) => ['could', k]), ...d.likely.filter((k) => !k.service).map((k) => ['likely', k]), ...(d.services || []).map((sv) => ['likely', { label: sv.name }])];
      return `<article class="card">
        <header><h3>${esc(x.a.name)}</h3>${gradeTag(x.grade)}<span class="spacer"></span><span class="mono">${bytes(x.a.sent)} sent · ${bytes(x.a.recv)} received · ${plural(x.nNet, 'connection')}</span></header>
        ${x.a.exe ? `<p class="path">${esc(x.a.exe)}</p>` : ''}
        <div class="cols">
          <div><h4>Companies</h4><ul class="kv">${more(x.owners, 10, (o) => `<li><span>${TRACKING.has(o.cat) ? '<i class="tr"></i>' : ''}${esc(o.name)}</span><span>${bytes(o.sent)}</span></li>`)}</ul></div>
          <div><h4>Websites</h4><ul class="kv">${x.sites.length ? more(x.sites, 10, (w) => `<li><span>${esc(w)}</span></li>`) : '<li class="muted">No website names seen</li>'}</ul>
            <h4>Countries</h4><p>${esc(x.countries.map(countryName).join(', ') || 'Unknown')}</p></div>
        </div>
        ${kinds.length ? `<h4>What it sent</h4><p class="kinds">${kinds.map(([b, k]) => `<span class="dk dk-${b}">${b === 'seen' ? 'Seen: ' : b === 'could' ? 'Could include: ' : ''}${esc(k.label)}</span>`).join('')}</p>` : ''}
        ${x.blocked ? `<p class="okline">WhoSees blocked ${plural(x.blocked, 'connection')} from this app.</p>` : ''}
      </article>`;
    }).join('')}`;

  const companiesSec = r.companies.length ? `${sec('companies', 'Companies', `Who received your data. The company is the owner of the server or website, from its address and name.`)}
    <table class="t"><thead><tr><th>Company</th><th>Kind</th><th>Apps</th><th>Where</th><th class="n">Sent</th><th class="n">Connections</th></tr></thead><tbody>
    ${r.companies.map((c) => `<tr><td><b>${esc(c.name)}</b>${c.sites.size ? `<div class="sub">${esc([...c.sites.keys()].filter(Boolean).slice(0, 3).join(', '))}</div>` : ''}</td><td>${chip(c.cat)}</td><td>${esc([...c.apps.keys()].slice(0, 4).join(', '))}${c.apps.size > 4 ? '…' : ''}</td><td>${esc([...c.places].slice(0, 2).join('; '))}${c.places.size > 2 ? '…' : ''}</td><td class="n">${bytes(c.sent)}</td><td class="n">${c.n}</td></tr>`).join('')}
    </tbody></table>` : '';

  const countriesSec = r.countries.length ? `${sec('countries', 'Countries', r.abroad != null && home && r.totalSent ? `${pct(r.abroad, r.totalSent)}% of the data sent went outside ${esc(countryName(home.country))}.` : '')}
    ${bars(r.countries.slice(0, 10).map((c) => ({ label: c.name, value: c.sent })))}
    <table class="t"><thead><tr><th>Country</th><th>Cities</th><th class="n">Companies</th><th class="n">Apps</th><th class="n">Sent</th><th class="n">Share</th></tr></thead><tbody>
    ${r.countries.map((c) => `<tr><td><b>${esc(c.name)}</b></td><td>${esc([...c.cities.keys()].slice(0, 4).join(', ') || '–')}</td><td class="n">${c.companies.size}</td><td class="n">${c.apps.size}</td><td class="n">${bytes(c.sent)}</td><td class="n">${pct(c.sent, r.totalSent)}%</td></tr>`).join('')}
    </tbody></table>` : '';

  const trackersSec = `${sec('trackers', 'Tracking and advertising', r.trackers.length ? `Companies that build profiles of people or sell advertising. They often receive identifiers, which screens you open and your rough location.` : '')}
    ${r.trackers.length ? `<table class="t"><thead><tr><th>Company</th><th>Kind</th><th>Contacted by</th><th>Websites</th><th class="n">Times</th></tr></thead><tbody>
      ${r.trackers.map((t) => `<tr><td><b>${esc(t.name)}</b></td><td>${chip(t.cat)}</td><td>${esc([...t.apps.keys()].join(', '))}</td><td class="sub">${esc([...t.sites.keys()].filter(Boolean).slice(0, 4).join(', ') || '–')}</td><td class="n">${t.n}</td></tr>`).join('')}
      </tbody></table>` : `<p class="okline">No known tracking or advertising companies were contacted during this live view.</p>`}`;

  const generic = r.data.likely.filter((d) => !d.service), svcs = r.data.services || [], ctls = r.data.controls || [];
  const dataSec = r.data.seen.length + r.data.likely.length + r.data.could.length ? `${sec('data', 'What kinds of data went out')}
    ${r.data.seen.length ? `<h3>Seen in readable traffic</h3><ul class="kv">${r.data.seen.map((d) => `<li><span><b>${esc(d.label)}</b>${d.details.size ? ` <span class="sub">${esc([...d.details].slice(0, 3).join(' · '))}</span>` : ''}</span><span>${plural(d.count, 'time')}</span></li>`).join('')}</ul>` : ''}
    ${r.data.could.length ? `<h3>Could include</h3><ul class="kv">${r.data.could.map((d) => `<li><span>${esc(d.label)}</span></li>`).join('')}</ul>` : ''}
    ${generic.length ? `<h3>Likely, based on who received it</h3><ul class="kv">${generic.map((d) => `<li><span>${esc(d.label)}</span><span>${plural(d.count, 'connection')}</span></li>`).join('')}</ul>` : ''}
    ${svcs.length ? `<h3>Known services</h3><p class="intro">What each service says it is built to collect, from its own documentation. The traffic was encrypted, so this is what it is designed to receive, not a reading of it.</p>
      <table class="t"><thead><tr><th>Service</th><th>Built to collect</th><th class="n">Connections</th></tr></thead><tbody>
      ${svcs.map((v) => `<tr><td><b>${esc(v.name)}</b>${v.owner ? `<br><span class="sub">${esc(v.owner)}</span>` : ''}<br><span class="url">${urlText(v.src)}</span></td><td>${esc(v.sends.join('; '))}</td><td class="n">${v.conns}</td></tr>`).join('')}
      </tbody></table>` : ''}
    ${ctls.length ? `<h3>What you can do</h3><ul class="kv ctl">${ctls.map((c) => `<li><span><b>${esc(c.label)}</b>${c.owner ? ` <span class="own">${esc(c.owner)}</span>` : ''}${c.how ? `<br><span class="how">${esc(c.how)}</span>` : ''}</span><span class="url">${c.url ? urlText(c.url) : ''}</span></li>`).join('')}</ul>` : ''}` : '';

  const plainSec = r.plain.length ? `${sec('unencrypted', 'Unencrypted connections', 'Traffic that anyone on the way (public Wi-Fi, your internet provider) could read or change.')}
    <table class="t"><thead><tr><th>Time</th><th>App</th><th>Website or address</th><th>Company</th><th>Type</th><th class="n">Sent</th></tr></thead><tbody>
    ${r.plain.slice(0, 500).map((c) => `<tr><td class="mono">${hms(c.ts || r.started)}</td><td>${esc(c.app.name)}</td><td>${esc(c.host || c.remote)}<span class="sub"> :${c.rport}</span></td><td>${esc(c.owner || '–')}</td><td>${esc(c.what || c.service || c.proto)}</td><td class="n">${bytes(c.ss || 0)}</td></tr>`).join('')}
    </tbody></table>` : '';

  const alertsSec = r.alerts.length ? `${sec('alerts', 'Threat alerts')}
    ${r.alerts.map((a) => `<article class="alert a-${a.severity}"><header><span class="sev">${a.severity === 'high' ? 'SERIOUS' : 'WARNING'}</span><b>${esc(a.title)}</b><span class="spacer"></span><span class="mono">${esc(clock(a.ts))}</span></header>
      <p>${esc(a.detail)}</p><p class="sub">${[a.appName && `App: ${a.appName}`, a.host && `Website: ${a.host}`, a.remote && `Address: ${a.remote}`, a.status === 'blocked' ? 'You blocked it' : a.status === 'trusted' ? 'You marked it as trusted' : ''].filter(Boolean).map(esc).join(' · ')}</p></article>`).join('')}` : '';

  const blockSec = r.rules.length || r.blockedConns.length || r.stopped ? `${sec('blocking', 'Blocking')}
    ${r.rules.length ? `<h3>Your block list</h3><ul class="kv">${r.rules.map((x) => `<li><span><b>${esc(x.label || x.value)}</b> <span class="sub">${esc({ host: 'website', company: 'company', country: 'country', ip: 'address', app: 'whole app', uid: 'whole app', category: 'kind of company' }[x.kind] || x.kind)}</span></span><span class="sub">${x.added ? esc(new Date(x.added).toLocaleDateString()) : ''}</span></li>`).join('')}</ul>` : ''}
    ${!s.blocking && r.rules.length ? `<p class="muted">Blocking wasn't on during this live view (on a computer it needs Deep mode), so nothing on this list was blocked.</p>` : r.blockedConns.length || r.stopped ? `<p class="okline">WhoSees stopped ${plural(r.blockedConns.length || r.stopped, 'attempt')} during this live view${r.blockedPlaces.length ? `, to ${esc(r.blockedPlaces.slice(0, 5).map((x) => s.topOwner(x.p.owners) || placeName(x.p.geo)).join(', '))}` : ''}.</p>` : '<p class="muted">Nothing on the list was contacted during this live view.</p>'}` : '';

  const rows = [...r.conns].sort((a, b) => (a.ts || 0) - (b.ts || 0));
  const shown = rows.slice(-MAX_ROWS);
  const allSec = rows.length ? `${sec('connections', 'Every connection', `${plural(rows.length, 'connection')}${rows.length > shown.length ? `; the ${shown.length} most recent are listed` : ''}. Times are when each one was first seen.`)}
    <table class="t dense"><thead><tr><th>Time</th><th>App</th><th>Website or address</th><th>Company</th><th>Location</th><th>Type</th><th class="n">Sent</th><th class="n">Recv</th></tr></thead><tbody>
    ${shown.map((c) => `<tr${c.blocked ? ' class="blk"' : ''}><td class="mono">${hms(c.ts || r.started)}</td><td>${esc(c.app.name)}</td><td>${esc(c.host || c.remote)}${c.host ? `<span class="sub"> ${esc(c.remote)}</span>` : ''}<span class="sub">:${c.rport}</span></td><td>${esc(c.scope === 'internet' ? c.owner || '–' : 'Your network')}</td><td>${esc(c.scope === 'internet' ? placeName(c.geo) : '–')}</td><td>${esc(c.blocked ? 'Blocked' : (c.what || c.service || c.proto || '').toString())}${c.encrypted === false && c.scope === 'internet' ? ' <b class="hot">plain</b>' : ''}</td><td class="n">${bytes(c.ss || 0)}</td><td class="n">${bytes(c.sr || 0)}</td></tr>`).join('')}
    </tbody></table>` : '';

  const aboutSec = `${sec('about', 'About this report')}
    <p>WhoSees watched which apps on this ${device} opened network connections and where they went. It doesn't read the contents of encrypted traffic, which is almost all traffic today. Company names come from the address owner and from public tracker lists, and places are where the server's address is registered, which is usually, but not always, where the server stands.</p>
    <p>${r.mode === 'standard' ? 'This live view used Standard mode, which checks the list of open connections several times a second: very short connections can be missed, and some website names may be missing.' : 'This live view saw every connection.'} Byte counts cover this live view only.</p>
    <p class="sub">IP location by DB-IP.com (CC BY 4.0). Tracker data: AdGuard companiesdb / WhoTracks.me (CC BY-SA 4.0). Threat data: Hagezi Threat Intelligence Feeds (GPL-3.0), abuse.ch (CC0). Map © OpenStreetMap contributors, Protomaps. WhoSees is free, open-source software (GPL-3.0): whosees.app</p>`;

  const T = theme === 'light'
    ? '--bg:#ffffff;--panel:#f5f4f0;--line:rgba(18,19,20,.12);--line2:rgba(18,19,20,.22);--text:#141516;--text2:#4d4e49;--text3:#7b7c76;--accent:#d9420b;--hot:#c2410c;--good:#15803d;--danger:#c81e3a;--warn:#a16207;'
    : '--bg:#0a0b0d;--panel:#121417;--line:rgba(236,234,228,.1);--line2:rgba(236,234,228,.2);--text:#eceae4;--text2:#a4a39c;--text3:#7a7b75;--accent:#ff5b1f;--hot:#ff8a4c;--good:#4ade80;--danger:#ff3d5a;--warn:#f2c14e;';
  const css = `${fonts}
:root{${T}}
@page{size:${paper === 'a4' ? 'A4' : 'letter'};margin:15mm 14mm 17mm;background:${theme === 'light' ? '#ffffff' : '#0a0b0d'};
  @bottom-left{content:"WhoSees privacy report · ${esc(when(r.ended)).replace(/"/g, '')}";font:400 7.5pt "Plex Mono",monospace;color:${theme === 'light' ? '#7b7c76' : '#7a7b75'}}
  @bottom-right{content:"Page " counter(page) " of " counter(pages);font:400 7.5pt "Plex Mono",monospace;color:${theme === 'light' ? '#7b7c76' : '#7a7b75'}}}
@page cover{margin:0;background:#0a0b0d;@bottom-left{content:none}@bottom-right{content:none}}
*{box-sizing:border-box;-webkit-print-color-adjust:exact;print-color-adjust:exact}
html,body{margin:0;background:var(--bg);color:var(--text);font:400 9.4pt/1.5 "Archivo",Arial,sans-serif}
b{font-weight:640}.mono,.sub,.path,th,.tile label,dt,.k,.bv,.bl{font-family:"Plex Mono",monospace}
.muted{color:var(--text3)}.hot{color:var(--hot)}
.cover{page:cover;width:${pw};height:${ph};padding:15mm 15mm 12mm;display:flex;flex-direction:column;gap:6mm;background:#0a0b0d;color:#eceae4;overflow:hidden;break-after:page;
  --text:#eceae4;--text2:#a4a39c;--text3:#7a7b75;--line:rgba(236,234,228,.1);--accent:#ff5b1f;--hot:#ff8a4c;--panel:#121417}
.cv-top{display:flex;justify-content:space-between;align-items:center;font-size:8pt;letter-spacing:.12em;color:#a4a39c}
.brand{display:flex;align-items:center;gap:8px;font:700 13pt "Archivo";letter-spacing:0;color:#eceae4;font-stretch:110%}.brand svg{width:26px;height:26px}
.cover h1{font:720 30pt/1.04 "Archivo";font-stretch:112%;letter-spacing:-.01em;margin:4mm 0 0;max-width:150mm}
.lede{font-size:12.5pt;line-height:1.45;color:#cfcdc6;margin:0;max-width:165mm}.lede b{color:#eceae4}.lede .hot{color:#ff8a4c}
.cv-map{margin:0;border:1px solid rgba(236,234,228,.14)}.cv-map img{display:block;width:100%}
.cv-map figcaption{display:flex;flex-wrap:wrap;gap:4px 12px;padding:6px 9px;border-top:1px solid rgba(236,234,228,.1);font:400 7.5pt "Plex Mono";color:#a4a39c}
.chip{display:inline-flex;align-items:center;gap:5px;font:400 7.5pt "Plex Mono";color:var(--text2);white-space:nowrap}.chip i{width:8px;height:8px;border-radius:50%;display:inline-block}.chip i.home{background:#ff5b1f;border-radius:0}
.tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:0;border:1px solid var(--line);border-width:1px 0 0 1px}
.tile{padding:3mm 3.5mm;border:1px solid var(--line);border-width:0 1px 1px 0;display:flex;flex-direction:column;gap:1px}
.tile label{font-size:6.8pt;letter-spacing:.12em;text-transform:uppercase;color:var(--text3)}
.tile strong{font:680 17pt/1.15 "Archivo";font-stretch:108%;font-variant-numeric:tabular-nums}.tile small{font-size:7.5pt;color:var(--text3)}.tile.hot strong{color:var(--hot)}
.cv-meta{display:grid;grid-template-columns:repeat(4,1fr);gap:3mm;margin:0}.cv-meta dt{font-size:6.8pt;letter-spacing:.12em;text-transform:uppercase;color:#7a7b75}.cv-meta dd{margin:1mm 0 0;font-size:8.6pt}
.cv-foot{margin-top:auto;font:400 7.4pt "Plex Mono";color:#7a7b75;border-top:1px solid rgba(236,234,228,.1);padding-top:3mm}
h2{font:700 19pt/1.1 "Archivo";font-stretch:110%;margin:0 0 3mm;padding-top:2mm;break-after:avoid;display:flex;align-items:baseline;gap:9px}
h2 .k{font:500 9pt "Plex Mono";color:var(--accent);letter-spacing:.08em}
h2.np{break-before:page}h2:not(.np):not(#findings){margin-top:11mm}
h3{font:650 11pt "Archivo";margin:6mm 0 2mm;break-after:avoid}h4{font:500 7pt "Plex Mono";letter-spacing:.12em;text-transform:uppercase;color:var(--text3);margin:3mm 0 1.5mm}
.intro{color:var(--text2);margin:0 0 4mm;max-width:160mm;break-after:avoid}h3+*,h2+*{break-before:avoid}
.findings{list-style:none;padding:0;margin:0 0 2mm;border-top:1px solid var(--line)}
.findings li{display:flex;gap:10px;padding:2.6mm 0;border-bottom:1px solid var(--line);font-size:10.2pt;break-inside:avoid}
.findings .dot{flex:none;width:9px;height:9px;margin-top:5px;background:var(--text3)}
.f-high .dot{background:var(--danger)}.f-warn .dot{background:var(--warn)}.f-good .dot{background:var(--good);border-radius:50%}.f-info .dot{background:var(--text3);border-radius:50%}
.howto{margin-top:6mm;padding:3mm 4mm;background:var(--panel);border-left:2px solid var(--accent);break-inside:avoid}.howto h3{margin-top:1mm}.howto p{color:var(--text2);margin:1.5mm 0}
.chart{display:block;margin:2mm 0 4mm;overflow:visible}.chart .bl{font-size:9px;fill:var(--text)}.chart .bv{font-size:9px;fill:var(--text2)}.chart .track{fill:var(--line)}
.chart .axis{stroke:var(--line2);stroke-width:1}.chart .grid{stroke:var(--line);stroke-width:1;stroke-dasharray:2 3}.chart .area{fill:var(--accent);opacity:.16}.chart .line{fill:none;stroke:var(--accent);stroke-width:2;stroke-linejoin:round}
.legend{display:flex;flex-wrap:wrap;gap:3px 14px;font:400 8pt "Plex Mono";color:var(--text2);margin:-1mm 0 4mm}.legend i{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:5px}.legend b{color:var(--text);font-weight:500}
table.t{width:100%;border-collapse:collapse;margin:2mm 0 5mm;font-size:8.2pt}
.t thead{display:table-header-group}.t tr{break-inside:avoid}
.t th{text-align:left;font-size:6.6pt;font-weight:500;letter-spacing:.1em;text-transform:uppercase;color:var(--text3);padding:1.6mm 2mm;border-bottom:1px solid var(--line2)}
.t td.mono{white-space:nowrap}.t td{padding:1.5mm 2mm;border-bottom:1px solid var(--line);vertical-align:top}.t .n{text-align:right;font-family:"Plex Mono";font-variant-numeric:tabular-nums;white-space:nowrap}
.t.dense{font-size:7pt}.t.dense td{padding:.9mm 1.4mm}.t.dense th{padding:1.2mm 1.4mm}.t tr.blk td{color:var(--text3)}
.sub{font-size:.88em;color:var(--text3);word-break:break-all}
.grade{display:inline-block;font:500 7pt "Plex Mono";letter-spacing:.08em;text-transform:uppercase;padding:.4mm 1.6mm;border:1px solid currentColor}
.g-good{color:var(--good)}.g-fair{color:var(--warn)}.g-poor{color:var(--danger)}
/* inline-block: Chromium's printer can't split these across pages (break-inside:avoid isn't always honoured) */
.card{border:1px solid var(--line);padding:3.5mm 4mm;margin:0 0 4mm;display:inline-block;width:100%;vertical-align:top;background:var(--panel)}
.card header{display:flex;align-items:center;gap:8px}.card h3{margin:0;font-size:12pt}.spacer{flex:1}.card header .mono{font-size:7.5pt;color:var(--text2)}
.path{font-size:7pt;color:var(--text3);margin:1mm 0 0;word-break:break-all}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:6mm}.cols p{margin:0;font-size:8.4pt;color:var(--text2)}
ul.kv{list-style:none;padding:0;margin:0}ul.kv.ctl li{align-items:baseline;break-inside:avoid}ul.kv.ctl li span.how{font-family:inherit;font-size:8pt;color:var(--text2);white-space:normal}ul.kv.ctl li span.own{font:400 7pt "Plex Mono",monospace;color:var(--text3);text-transform:uppercase;letter-spacing:.06em;margin-left:4px}.url{font:7pt "Plex Mono",monospace;color:var(--text3);word-break:normal;overflow-wrap:normal}ul.kv.ctl li span.url{font:400 7pt "Plex Mono",monospace;white-space:normal;text-align:right;max-width:60%;color:var(--text3)}ul.kv li{display:flex;justify-content:space-between;gap:8px;padding:.8mm 0;border-bottom:1px dotted var(--line);font-size:8.4pt}
ul.kv li span:last-child{font-family:"Plex Mono";font-size:7.6pt;color:var(--text2);white-space:nowrap}ul.kv li.more{color:var(--text3);border:0}
i.tr{display:inline-block;width:7px;height:7px;border-radius:50%;background:#ff5c7a;margin-right:5px}
.kinds{display:flex;flex-wrap:wrap;gap:4px;margin:0}.dk{font:400 7.4pt "Plex Mono";padding:.5mm 1.8mm;border:1px solid var(--line2);color:var(--text2)}
.dk-seen{border-color:var(--danger);color:var(--danger)}.dk-could{border-color:var(--warn);color:var(--warn)}
.okline{color:var(--good);margin:2mm 0}
.alert{border:1px solid var(--line);border-left:3px solid var(--warn);padding:3mm 4mm;margin:0 0 3mm;display:inline-block;width:100%;vertical-align:top;background:var(--panel)}.alert.a-high{border-left-color:var(--danger)}
.alert header{display:flex;gap:8px;align-items:baseline}.alert .sev{font:500 7pt "Plex Mono";letter-spacing:.1em;color:var(--warn)}.alert.a-high .sev{color:var(--danger)}.alert p{margin:1.5mm 0 0}
`;
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>${esc(title)} · WhoSees report</title><style>${css}</style></head><body>
${cover}
<main>${findingsSec}${appsSec}${companiesSec}${countriesSec}${trackersSec}${dataSec}${plainSec}${alertsSec}${blockSec}${allSec}${aboutSec}</main>
</body></html>`;
}

const LOGO = `<svg viewBox="64 64 896 896" aria-hidden="true"><rect x="64" y="64" width="896" height="896" rx="190" fill="#16181c"/><path d="M318 706 C 360 440, 560 300, 724 318" fill="none" stroke="#eceae4" stroke-width="44"/><g stroke="#ff5b1f" stroke-width="26" fill="none"><circle cx="318" cy="706" r="78"/></g><rect x="292" y="680" width="52" height="52" fill="#ff5b1f"/><rect x="676" y="270" width="104" height="104" fill="#ff5b1f"/></svg>`;
