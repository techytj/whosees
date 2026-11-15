// Offline basemap (MapLibre + PMTiles over IPC) and the animated flow layer on a canvas above it.
import * as maplibregl from 'maplibre-gl';
import { PMTiles, Protocol } from 'pmtiles';
import { layers, namedFlavor } from '@protomaps/basemaps';

// ---------- basemap ----------
class IpcSource {
  getKey() { return 'world'; }
  async getBytes(offset, length) {
    const d = await window.wt.readTiles(offset, length);
    return { data: d.buffer.slice(d.byteOffset, d.byteOffset + d.byteLength) };
  }
}

const FLAVORS = {
  dark: {
    ...namedFlavor('dark'),
    background: '#06080d', earth: '#0f1420', water: '#06080d', glacier: '#121826', sand: '#11161f',
    park_a: '#0f1520', park_b: '#0f1520', wood_a: '#0f1520', wood_b: '#0f1520', scrub_a: '#0f1420', scrub_b: '#0f1420',
    boundaries: '#2a3448', country_label: '#5d6a82', state_label: '#3b4558', city_label: '#4c586e',
    city_label_halo: '#06080d', state_label_halo: '#06080d', ocean_label: '#26304a',
    highway: '#1b2230', major: '#161c28', minor_a: '#131926', minor_b: '#131926', railway: '#141a26',
  },
  light: {
    ...namedFlavor('light'),
    background: '#dde4ee', earth: '#f5f7fb', water: '#dae2ed', glacier: '#ffffff', sand: '#f1f3f6',
    park_a: '#eef2f2', park_b: '#eef2f2', wood_a: '#eef2f2', wood_b: '#eef2f2', scrub_a: '#f1f4f4', scrub_b: '#f1f4f4',
    boundaries: '#b8c2d2', country_label: '#6c788c', city_label: '#7d889b', ocean_label: '#a4b0c2',
  },
};

function style(theme) {
  const ls = layers('protomaps', FLAVORS[theme], { lang: 'en' })
    .filter((l) => !(l.layout && l.layout['icon-image'])) // no sprite sheet bundled
    .filter((l) => !/^(pois|address_label|roads_label|roads_shield|landcover|landuse|places_locality|places_subplace)/.test(l.id));
  return {
    version: 8,
    glyphs: window.wt?.glyphs || 'wt://shared/map/fonts/{fontstack}/{range}.pbf',
    sources: { protomaps: { type: 'vector', url: 'pmtiles://world', attribution: '© OpenStreetMap, Protomaps' } },
    layers: ls,
  };
}

let protocolAdded = false;
export async function createMap(container, theme, center) {
  if (!protocolAdded) {
    // Workers can't load from the app's custom scheme directly: hand MapLibre a blob of the worker code.
    const code = await (await fetch(new URL('../node_modules/maplibre-gl/dist/maplibre-gl-worker.mjs', import.meta.url))).text();
    maplibregl.setWorkerUrl(URL.createObjectURL(new Blob([code], { type: 'text/javascript' })));
    const p = new Protocol();
    p.add(new PMTiles(new IpcSource()));
    maplibregl.addProtocol('pmtiles', p.tile);
    protocolAdded = true;
  }
  const map = new maplibregl.Map({
    container, style: style(theme), center: center || [0, 25], zoom: initialZoom(),
    minZoom: 0.6, maxZoom: 7.5, attributionControl: false, dragRotate: false, pitchWithRotate: false,
    renderWorldCopies: true, fadeDuration: 0,
  });
  map.touchZoomRotate.disableRotation();
  map.keyboard.disableRotation();
  map.setTheme = (t) => map.setStyle(style(t), { diff: false });
  return map;
}
function initialZoom() { return window.innerWidth < 700 ? 0.9 : window.innerWidth < 1200 ? 1.5 : 1.85; }

// ---------- flow layer ----------
const cssVar = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
function rgb(hex) { const v = parseInt(hex.replace('#', ''), 16); return [(v >> 16) & 255, (v >> 8) & 255, v & 255]; }

export class Flows {
  constructor(map, canvas, session) {
    this.map = map; this.canvas = canvas; this.s = session;
    this.ctx = canvas.getContext('2d');
    this.home = null;
    this.pulses = [];      // {key, t, speed, size, color}
    this.ripples = [];     // {key, t0, color}
    this.births = new Map(); // place key -> born ts
    this.hidden = new Set(); // categories filtered out via legend
    this.focus = null;       // set of place keys to highlight (app/place selected)
    this.colors = {};
    this.hover = null;
    this.readColors();
    this.resize();
    window.addEventListener('resize', () => this.resize());
    requestAnimationFrame((t) => this.frame(t));
  }

  readColors() {
    for (const c of ['tracker', 'ads', 'analytics', 'social', 'messaging', 'streaming', 'cdn', 'cloud', 'other', 'local'])
      this.colors[c] = rgb(cssVar(`--c-${c}`) || '#94a3b8');
    this.accent = rgb(cssVar('--accent') || '#5ee6d0');
    this.labelInk = cssVar('--text-2') || '#9aa6ba';
    this.labelStrong = cssVar('--text') || '#e8edf6';
    this.labelHalo = cssVar('--bg') || '#06080d';
    this.light = document.documentElement.dataset.theme === 'light';
  }

  resize() {
    const dpr = window.devicePixelRatio || 1;
    this.dpr = dpr;
    this.canvas.width = Math.round(window.innerWidth * dpr);
    this.canvas.height = Math.round(window.innerHeight * dpr);
    this.canvas.style.width = window.innerWidth + 'px';
    this.canvas.style.height = window.innerHeight + 'px';
  }

  setHome(lonlat, name) { this.home = lonlat; if (name) this.homeName = name; }

  born(key) { if (!this.births.has(key)) this.births.set(key, performance.now()); }

  /** Data moved: bright pulses fly out for data sent, smaller dim ones fly back for data received. */
  flow(place, sent, recv = 0) {
    if (!place || place.scope !== 'internet' || this.isBlocked?.(place)) return; // nothing gets through
    const color = this.s.topCat(place.cats);
    const count = (b) => (b <= 0 ? 0 : Math.max(1, Math.min(5, Math.round(Math.log10(Math.max(b, 10)) - 1.5))));
    for (let i = 0, n = count(sent); i < n; i++)
      this.pulses.push({ key: place.key, t: -i * 0.11, speed: 0.55 + Math.random() * 0.2, size: 1.8 + Math.min(2.4, Math.log10(sent + 1) * 0.45), color, back: false });
    for (let i = 0, n = Math.min(3, count(recv)); i < n; i++)
      this.pulses.push({ key: place.key, t: -i * 0.14 - 0.05, speed: 0.5 + Math.random() * 0.2, size: 1.2, color, back: true });
    if (this.pulses.length > 1500) this.pulses.splice(0, this.pulses.length - 1500);
  }

  // Screen-space geometry for one place: start, control and end points (handles world copies).
  geom(p) {
    if (!this.home || p.lat == null) return null;
    let lon = p.lon;
    const hl = this.home[0];
    while (lon - hl > 180) lon -= 360;
    while (lon - hl < -180) lon += 360;
    const a = this.map.project(this.home), b = this.map.project([lon, p.lat]);
    const dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy);
    if (len < 0.5) return { a, b, c: a, len };
    // bend "upwards" on screen, proportional to distance
    let nx = -dy / len, ny = dx / len;
    if (ny > 0) { nx = -nx; ny = -ny; }
    const k = Math.min(len * 0.28, 260);
    const c = { x: (a.x + b.x) / 2 + nx * k, y: (a.y + b.y) / 2 + ny * k };
    return { a, b, c, len };
  }

  /** Bounds [[w,s],[e,n]] around home and every visible place, longitudes unwrapped around home. */
  bounds() {
    if (!this.home) return null;
    let [w, s, e, n] = [this.home[0], this.home[1], this.home[0], this.home[1]];
    for (const p of this.s.places.values()) {
      if (p.scope !== 'internet' || p.lat == null || this.hidden.has(this.s.topCat(p.cats))) continue;
      let lon = p.lon;
      while (lon - this.home[0] > 180) lon -= 360;
      while (lon - this.home[0] < -180) lon += 360;
      w = Math.min(w, lon); e = Math.max(e, lon); s = Math.min(s, p.lat); n = Math.max(n, p.lat);
    }
    return [[w, Math.max(-70, s)], [e, Math.min(80, n)]];
  }

  static bez(g, t) {
    const u = 1 - t;
    return { x: u * u * g.a.x + 2 * u * t * g.c.x + t * t * g.b.x, y: u * u * g.a.y + 2 * u * t * g.c.y + t * t * g.b.y };
  }

  nearest(x, y) {
    let bd = Infinity, n = 0;
    for (const p of this.s.places.values()) {
      if (p.scope !== 'internet') continue;
      const g = this.geom(p); if (!g) continue; n++;
      bd = Math.min(bd, Math.hypot(g.b.x - x, g.b.y - y));
    }
    return `${Math.round(bd)}px of ${n} dots`;
  }

  hitTest(x, y) {
    let best = null, bd = 22; // generous target: dots are small
    for (const p of this.s.places.values()) {
      if (p.scope !== 'internet' || this.hidden.has(this.s.topCat(p.cats))) continue;
      const g = this.geom(p); if (!g) continue;
      const d = Math.hypot(g.b.x - x, g.b.y - y);
      if (d < bd) { bd = d; best = p; }
    }
    return best;
  }

  frame(now) {
    requestAnimationFrame((t) => this.frame(t));
    const dt = Math.min(0.05, (now - (this.lastT || now)) / 1000);
    this.lastT = now;
    const { ctx, dpr } = this;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    if (!this.home) return;

    const wall = Date.now();
    const lighter = this.light ? 'source-over' : 'lighter';
    const geoms = new Map();

    // arcs
    ctx.lineCap = 'round';
    for (const p of this.s.places.values()) {
      if (p.scope !== 'internet') continue;
      const cat = this.s.topCat(p.cats);
      if (this.hidden.has(cat)) continue;
      const g = this.geom(p); if (!g) continue;
      const blocked = this.isBlocked?.(p) || false;
      geoms.set(p.key, { g, cat, blocked });
      const [r, gg, b] = blocked ? this.colors.tracker : (this.colors[cat] || this.colors.other);
      const active = !blocked && wall - p.last < 4000;
      const focused = this.focus ? this.focus.has(p.key) : true;
      const born = this.births.get(p.key) ?? 0;
      const grow = Math.min(1, (now - born) / 900);
      const ease = 1 - Math.pow(1 - grow, 3);
      let alpha = p.live > 0 ? (active ? 0.9 : 0.45) : 0.16;
      if (!focused) alpha *= 0.18;
      if (this.hover === p) alpha = Math.max(alpha, 0.95);

      const steps = Math.max(12, Math.min(64, Math.round(g.len / 12)));
      const grad = ctx.createLinearGradient(g.a.x, g.a.y, g.b.x, g.b.y);
      const [ar, ag, ab] = this.accent;
      grad.addColorStop(0, `rgba(${ar},${ag},${ab},${alpha * 0.35})`);
      grad.addColorStop(1, `rgba(${r},${gg},${b},${alpha})`);
      ctx.beginPath();
      ctx.moveTo(g.a.x, g.a.y);
      for (let i = 1; i <= steps * ease; i++) { const q = Flows.bez(g, i / steps); ctx.lineTo(q.x, q.y); }
      if (active && focused) { // soft glow underlay
        ctx.strokeStyle = `rgba(${r},${gg},${b},${alpha * (this.light ? 0.16 : 0.22)})`;
        ctx.lineWidth = 4; ctx.stroke();
      }
      ctx.strokeStyle = grad;
      ctx.lineWidth = active && focused ? 2 : 1.3;
      if (blocked) ctx.setLineDash([3, 5]);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // pulses travelling along arcs (comet with a tail)
    ctx.globalCompositeOperation = lighter;
    const keep = [];
    for (const pu of this.pulses) {
      pu.t += dt * pu.speed * (pu.t < 0 ? 1 : 1);
      const e = geoms.get(pu.key);
      if (!e) { if (pu.t < 1) keep.push(pu); continue; }
      if (pu.t >= 1) { if (!pu.back) this.ripples.push({ key: pu.key, t0: now, color: e.cat }); continue; }
      keep.push(pu);
      if (pu.t < 0) continue;
      if (this.focus && !this.focus.has(pu.key)) continue;
      const [r, g, b] = this.colors[e.cat] || this.colors.other;
      const pos = (t) => Flows.bez(e.g, pu.back ? 1 - t : t);
      const dim = pu.back ? 0.45 : 1;
      for (let i = 6; i >= 0; i--) {
        const tt = pu.t - i * 0.018;
        if (tt < 0) continue;
        const q = pos(tt);
        const a = (i === 0 ? 1 : (1 - i / 7) * 0.45) * dim;
        const rad = pu.size * (i === 0 ? 1 : 1 - i / 9);
        ctx.fillStyle = `rgba(${r},${g},${b},${a})`;
        ctx.beginPath(); ctx.arc(q.x, q.y, rad, 0, Math.PI * 2); ctx.fill();
      }
      const q = pos(pu.t);
      const glow = ctx.createRadialGradient(q.x, q.y, 0, q.x, q.y, pu.size * 5);
      glow.addColorStop(0, `rgba(${r},${g},${b},${0.55 * dim})`); glow.addColorStop(1, `rgba(${r},${g},${b},0)`);
      ctx.fillStyle = glow; ctx.beginPath(); ctx.arc(q.x, q.y, pu.size * 5, 0, Math.PI * 2); ctx.fill();
    }
    this.pulses = keep;

    // arrival ripples
    this.ripples = this.ripples.filter((rp) => {
      const k = (now - rp.t0) / 900;
      if (k >= 1) return false;
      const e = geoms.get(rp.key); if (!e) return false;
      const [r, g, b] = this.colors[rp.color] || this.colors.other;
      ctx.strokeStyle = `rgba(${r},${g},${b},${(1 - k) * 0.8})`;
      ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.arc(e.g.b.x, e.g.b.y, 4 + k * 16, 0, Math.PI * 2); ctx.stroke();
      return true;
    });
    ctx.globalCompositeOperation = 'source-over';

    // destination dots
    for (const p of this.s.places.values()) {
      const e = geoms.get(p.key); if (!e) continue;
      const [r, g, b] = this.colors[e.cat] || this.colors.other;
      const focused = this.focus ? this.focus.has(p.key) : true;
      const total = p.sent + p.recv;
      const rad = 2.6 + Math.min(6, Math.log10(total + 10) * 0.9);
      const a = (p.live > 0 ? 1 : 0.45) * (focused ? 1 : 0.25);
      ctx.globalCompositeOperation = lighter;
      const glow = ctx.createRadialGradient(e.g.b.x, e.g.b.y, 0, e.g.b.x, e.g.b.y, rad * 3.2);
      glow.addColorStop(0, `rgba(${r},${g},${b},${0.45 * a})`); glow.addColorStop(1, `rgba(${r},${g},${b},0)`);
      ctx.fillStyle = glow; ctx.beginPath(); ctx.arc(e.g.b.x, e.g.b.y, rad * 3.2, 0, Math.PI * 2); ctx.fill();
      ctx.globalCompositeOperation = 'source-over';
      ctx.fillStyle = `rgba(${r},${g},${b},${a})`;
      ctx.beginPath(); ctx.arc(e.g.b.x, e.g.b.y, rad, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = this.light ? `rgba(255,255,255,${a})` : `rgba(6,8,13,${a * 0.9})`;
      ctx.lineWidth = 1.5; ctx.stroke();
      if (!e.blocked && this.hasAlert?.(p)) { // pulsing warning ring
        const k = (now % 1400) / 1400;
        ctx.strokeStyle = `rgba(${this.colors.tracker.join(',')},${(1 - k) * 0.9})`; ctx.lineWidth = 2;
        ctx.beginPath(); ctx.arc(e.g.b.x, e.g.b.y, rad + 3 + k * 14, 0, Math.PI * 2); ctx.stroke();
      }
      if (e.blocked) { // red ring with a slash
        const rr = rad + 4;
        ctx.strokeStyle = `rgba(${this.colors.tracker.join(',')},${0.95 * (focused ? 1 : 0.4)})`; ctx.lineWidth = 1.8;
        ctx.beginPath(); ctx.arc(e.g.b.x, e.g.b.y, rr, 0, Math.PI * 2); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(e.g.b.x - rr * 0.7, e.g.b.y - rr * 0.7); ctx.lineTo(e.g.b.x + rr * 0.7, e.g.b.y + rr * 0.7); ctx.stroke();
      }
      if (this.hover === p) {
        ctx.strokeStyle = `rgba(${r},${g},${b},0.9)`; ctx.lineWidth = 1.5;
        ctx.beginPath(); ctx.arc(e.g.b.x, e.g.b.y, rad + 5, 0, Math.PI * 2); ctx.stroke();
      }
    }

    // home: crosshair (the WhoSees "you are here" mark), with a slow scanning ring
    const h = this.map.project(this.home);
    const [ar, ag, ab] = this.accent;
    const beat = (now % 2600) / 2600;
    ctx.strokeStyle = `rgba(${ar},${ag},${ab},${(1 - beat) * 0.5})`;
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.arc(h.x, h.y, 8 + beat * 26, 0, Math.PI * 2); ctx.stroke();
    ctx.strokeStyle = `rgb(${ar},${ag},${ab})`; ctx.lineWidth = 1.4;
    ctx.beginPath(); ctx.arc(h.x, h.y, 11, 0, Math.PI * 2); ctx.stroke();
    ctx.beginPath();
    for (const [dx, dy] of [[-1, 0], [1, 0], [0, -1], [0, 1]]) { ctx.moveTo(h.x + dx * 15, h.y + dy * 15); ctx.lineTo(h.x + dx * 22, h.y + dy * 22); }
    ctx.stroke();
    ctx.fillStyle = `rgb(${ar},${ag},${ab})`;
    ctx.fillRect(h.x - 3, h.y - 3, 6, 6);

    this.drawLabels(h, geoms);
  }

  /** Small city names: home first, then destinations by traffic, skipping any that would overlap. */
  drawLabels(h, geoms) {
    const { ctx } = this;
    const boxes = [];
    const free = (b) => b.x > 2 && b.y > 2 && b.x + b.w < innerWidth - 2 && b.y + b.h < innerHeight - 2 &&
      !boxes.some((o) => b.x < o.x + o.w && b.x + b.w > o.x && b.y < o.y + o.h && b.y + b.h > o.y);
    const put = (text, x, y, r, strong) => {
      ctx.font = `${strong ? 700 : 500} ${strong ? 12 : 11}px Archivo, system-ui, sans-serif`;
      const w = ctx.measureText(text).width, hgt = strong ? 14 : 13;
      // try right, left, above, below the dot
      const spots = [[x + r + 5, y - hgt / 2], [x - r - 5 - w, y - hgt / 2], [x - w / 2, y - r - 4 - hgt], [x - w / 2, y + r + 4]];
      for (const [bx, by] of spots) {
        const b = { x: bx - 2, y: by - 1, w: w + 4, h: hgt + 2 };
        if (!free(b)) continue;
        boxes.push(b);
        ctx.textBaseline = 'top';
        ctx.lineJoin = 'round';
        ctx.lineWidth = 3;
        ctx.strokeStyle = this.labelHalo;
        ctx.strokeText(text, bx, by);
        ctx.fillStyle = strong ? this.labelStrong : this.labelInk;
        ctx.fillText(text, bx, by);
        return true;
      }
      return false;
    };

    // reserve the dots themselves so labels don't cover them
    for (const { g } of geoms.values()) boxes.push({ x: g.b.x - 5, y: g.b.y - 5, w: 10, h: 10 });

    if (this.homeName) put(this.homeName, h.x, h.y, 8, true);

    const places = [...this.s.places.values()].filter((p) => geoms.has(p.key));
    const rank = (p) => (this.hover === p ? 3e15 : 0) + (this.focus?.has(p.key) ? 2e15 : 0) + (p.live > 0 ? 1e15 : 0) + p.sent + p.recv;
    places.sort((a, b) => rank(b) - rank(a));
    const used = new Set();
    for (const p of places) {
      if (this.focus && !this.focus.has(p.key) && this.hover !== p) continue;
      const g = p.geo || {};
      const name = g.city ? g.city.split(' (')[0] : g.country || '';
      if (!name) continue;
      const { g: geom } = geoms.get(p.key);
      const key = name + '|' + Math.round(geom.b.x / 40) + ',' + Math.round(geom.b.y / 40);
      if (used.has(key)) continue;
      const r = 2.6 + Math.min(6, Math.log10(p.sent + p.recv + 10) * 0.9);
      if (put(name, geom.b.x, geom.b.y, r, this.hover === p)) used.add(key);
    }
  }
}
