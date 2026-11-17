// Session state: connections from the agent, rolled up by app and by place.
import { profileFor, controlsFor } from './profiles.js';

export const CATEGORIES = {
  tracker:   { label: 'Tracker',   plain: 'a tracking company' },
  ads:       { label: 'Ads',       plain: 'an advertising company' },
  analytics: { label: 'Analytics', plain: 'an analytics service' },
  social:    { label: 'Social',    plain: 'a social network' },
  messaging: { label: 'Messaging', plain: 'a messaging service' },
  streaming: { label: 'Streaming', plain: 'a streaming service' },
  cdn:       { label: 'CDN',       plain: 'a content network' },
  cloud:     { label: 'Cloud',     plain: 'a cloud provider' },
  other:     { label: 'Other',     plain: 'a server' },
  local:     { label: 'Local',     plain: 'a device on your network' },
};
export const TRACKING = new Set(['tracker', 'ads', 'analytics']);
// generic "likely" items that still apply when a service profile is known
const GENERIC_KEEP = new Set(['unencrypted', 'website-names', 'time', 'email', 'calls']);

const regionNames = (() => { try { return new Intl.DisplayNames(['en'], { type: 'region' }); } catch { return null; } })();
export const countryName = (cc) => { try { return (cc && regionNames?.of(cc)) || cc || 'Unknown'; } catch { return cc || 'Unknown'; } };

export function bytes(n) {
  if (!n) return '0 B';
  const u = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.min(u.length - 1, Math.floor(Math.log(n) / Math.log(1024)));
  const v = n / 1024 ** i;
  return `${v >= 100 || i === 0 ? Math.round(v) : v.toFixed(1)} ${u[i]}`;
}
export const rate = (n) => `${bytes(n)}/s`;
export function ago(ts) {
  const s = Math.max(0, Math.round((Date.now() - ts) / 1000));
  if (s < 5) return 'now';
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  return m < 60 ? `${m}m ago` : `${Math.round(m / 60)}h ago`;
}
export function placeName(g) {
  if (!g || !g.country) return 'Unknown location';
  const city = g.city ? g.city.split(' (')[0] : null;
  return city ? `${city}, ${countryName(g.country)}` : countryName(g.country);
}

export class Session {
  constructor() { this.platform = globalThis.wt?.platform || ''; this.reset(); }

  reset() {
    this.conns = new Map();   // id -> conn
    this.apps = new Map();    // app id -> app rollup
    this.places = new Map();  // place key -> place rollup
    this.feed = [];           // newest first
    this.started = null;
    this.mode = 'standard';
    this.totals = { sent: 0, recv: 0, rateSent: 0, open: 0 };
    this.history = [];        // send rate per second (sparkline)
    this.rateLog = [];        // [time, send rate] for the whole live view (the report's chart)
    this.ended = null;        // when the live view was stopped
    this.blockedHits = {};    // ip -> packets stopped by the firewall
    this.alerts = [];         // newest first
    this.threatLists = null;
    this.blocking = false;
    this.readPayloads = false; // whether this live view read TLS payloads (opt-in)
    this.listeners = new Set();
    this.dirty = true;
  }

  on(fn) { this.listeners.add(fn); }
  emit(type, data) { for (const fn of this.listeners) fn(type, data); }

  placeKey(c) {
    const g = c.geo || {};
    if (c.scope !== 'internet' || g.lat == null) return `lan:${c.scope}`;
    return `${g.lat.toFixed(1)},${g.lon.toFixed(1)}`;
  }

  ingest(events) {
    for (const e of events) {
      switch (e.t) {
        case 'hello': this.mode = e.mode; this.blocking = !!e.blocking; this.readPayloads = !!e.read_payloads; this.threatLists = e.threats || null; this.started ??= Date.now(); this.emit('hello', e); break;
        case 'open': this.open(e); break;
        case 'update': this.update(e); break;
        case 'close': this.close(e); break;
        case 'stats':
          this.totals = { sent: e.sent, recv: e.recv, rateSent: e.rate_sent, open: e.open };
          this.history.push(e.rate_sent); if (this.history.length > 90) this.history.shift();
          this.logRate(e.rate_sent);
          break;
        case 'host': this.host(e); break;
        case 'alert': this.alert(e); break;
        case 'data': { const c = this.conns.get(e.id); if (c) { c.data = [...c.data, ...(e.items || [])]; this.emit('data', { conn: c, items: e.items }); } break; }
        case 'rules': this.emit('rules', e); break;
        case 'blockstats':
          this.blockedHits = e.ips || {};
          for (const [ip, w] of Object.entries(e.where || {})) this.stopped(ip, w);
          break;
        case 'warn': this.emit('warn', e.msg); break;
        case 'deepfail': this.emit('deepfail', e); break;
        case 'error': this.emit('error', e.msg); break;
      }
    }
    this.dirty = true;
  }

  open(e) {
    const now = Date.now();
    const c = { ...e, open: true, last: now, key: this.placeKey(e), data: e.data || [] };
    this.conns.set(e.id, c);

    let a = this.apps.get(e.app.id);
    if (!a) {
      a = { id: e.app.id, name: e.app.name, icon: e.app.icon, system: e.app.system, exe: e.app.exe, uid: e.app.uid, perms: e.app.perms || [],
            sent: 0, recv: 0, conns: new Set(), places: new Set(), countries: new Set(), owners: new Map(), cats: new Map(), sites: new Map(), last: now, first: now };
      this.apps.set(a.id, a);
    }
    a.conns.add(e.id); a.places.add(c.key); a.last = now;
    if (e.geo?.country) a.countries.add(e.geo.country);
    if (e.owner) a.owners.set(e.owner, (a.owners.get(e.owner) || 0) + 1);
    a.cats.set(e.category, (a.cats.get(e.category) || 0) + 1);

    const p = this.place(c.key, e, now);
    p.conns.add(e.id); p.apps.add(a.id); p.live++; p.last = now;
    if (e.owner) p.owners.set(e.owner, (p.owners.get(e.owner) || 0) + 1);
    p.cats.set(e.category, (p.cats.get(e.category) || 0) + 1);
    this.noteSite(a, p, c);

    this.add(c, e.sent, e.recv, false);
    this.feed.unshift(c);
    if (this.feed.length > 600) this.feed.length = 600;
    this.emit('open', { conn: c, place: p, app: a, fresh: !e.existing });
  }

  place(key, e, now) {
    let p = this.places.get(key);
    if (!p) {
      p = { key, lat: e.geo?.lat, lon: e.geo?.lon, geo: e.geo, scope: e.scope, sent: 0, recv: 0,
            conns: new Set(), apps: new Set(), owners: new Map(), cats: new Map(), sites: new Map(), hosts: new Set(),
            stops: new Map(), live: 0, last: now, first: now };
      this.places.set(key, p);
    }
    return p;
  }

  // The firewall stopped an address before any connection to it showed up (blocked from its first lookup).
  // Put it on the map so the attempts are visible: only where it is and who runs it, no app and no data.
  stopped(ip, w) {
    if (w.scope !== 'internet' || w.geo?.lat == null) return;
    for (const c of this.conns.values()) if (c.remote === ip) return;
    const p = this.place(this.placeKey(w), w, Date.now());
    if (p.stops.has(ip)) return;
    p.stops.set(ip, { host: w.host || null, category: w.category });
    if (w.owner) p.owners.set(w.owner, (p.owners.get(w.owner) || 0) + 1);
    p.cats.set(w.category, (p.cats.get(w.category) || 0) + 1);
    this.noteSite(null, p, w);
    this.emit('stopped', { place: p, ip });
  }

  add(c, ds, dr, pulse = true) {
    c.ss = (c.ss || 0) + (ds || 0); c.sr = (c.sr || 0) + (dr || 0); // this live view only
    const a = this.apps.get(c.app.id), p = this.places.get(c.key);
    for (const x of [a, p]) if (x) { x.sent += ds; x.recv += dr; x.last = Date.now(); }
    if (pulse && (ds > 0 || dr > 0)) this.emit('flow', { conn: c, place: p, sent: ds, recv: dr });
  }

  /** One sample a second; when the live view gets long, neighbouring samples are merged so it stays small. */
  logRate(v) {
    this.rateLog.push([Date.now(), v || 0]);
    if (this.rateLog.length > 1800) this.rateLog = this.rateLog.filter((_, i) => i % 2 === 0).map((x, i) => [x[0], (x[1] + (this.rateLog[2 * i + 1]?.[1] ?? x[1])) / 2]);
  }

  noteSite(a, p, c) {
    const label = c.site || c.host;
    if (!label) return;
    for (const x of [a, p]) if (x) x.sites.set(label, (x.sites.get(label) || 0) + 1);
    if (p && c.host) p.hosts.add(c.host);
  }

  // Deep mode learned the website after the connection was first reported.
  host(e) {
    const c = this.conns.get(e.id);
    if (!c) return;
    const a = this.apps.get(c.app.id), p = this.places.get(c.key);
    const bump = (m, k, d) => { if (!m || !k) return; const v = (m.get(k) || 0) + d; v > 0 ? m.set(k, v) : m.delete(k); };
    if (e.category && e.category !== c.category && c.scope === 'internet') {
      for (const x of [a, p]) { bump(x?.cats, c.category, -1); bump(x?.cats, e.category, 1); }
      c.category = e.category;
    }
    if (e.owner && e.owner !== c.owner) {
      for (const x of [a, p]) { bump(x?.owners, c.owner, -1); bump(x?.owners, e.owner, 1); }
      c.owner = e.owner;
    }
    c.host = e.host; c.site = e.site || null;
    if (e.data) c.data = [...e.data, ...c.data.filter((d) => d.basis === 'seen')]; // better guess now we know the website
    this.noteSite(a, p, c);
    this.dirty = true;
  }

  alert(e) {
    const c = e.conn != null ? this.conns.get(e.conn) : null;
    const a = { ...e.alert, id: this.alerts.length + 1, ts: Date.now(), conn: e.conn, host: e.host, remote: e.remote,
                appId: c?.app.id || null, appName: c?.app.name || null, placeKey: c?.key || null, status: 'new' };
    a.key = `${a.kind}|${a.appId || ''}|${a.block?.value || a.host || a.remote || ''}`;
    if (c) { const p = this.places.get(c.key); if (p) p.alerts = (p.alerts || 0) + 1; }
    this.alerts.unshift(a);
    this.emit('alert', a);
  }

  update(e) {
    const c = this.conns.get(e.id);
    if (!c) return;
    c.sent = e.sent; c.recv = e.recv; c.last = Date.now();
    this.add(c, e.ds || 0, e.dr || 0);
  }

  close(e) {
    const c = this.conns.get(e.id);
    if (!c) return;
    c.open = false; c.closed = Date.now();
    const p = this.places.get(c.key);
    if (p) p.live = Math.max(0, p.live - 1);
    this.emit('close', { conn: c, place: p });
  }

  topCat(m) {
    let best = 'other', n = -1;
    for (const [k, v] of m) {
      const w = v + (TRACKING.has(k) ? 1000 : 0); // tracking always wins the colour
      if (w > n) { n = w; best = k; }
    }
    return best;
  }
  /** Packets stopped for a place (sum over its addresses, each counted once). */
  stoppedAt(p) {
    const ips = new Set(p.stops?.keys());
    for (const id of p.conns) { const c = this.conns.get(id); if (c) ips.add(c.remote); }
    let n = 0;
    for (const ip of ips) n += this.blockedHits[ip] || 0;
    return n;
  }

  /**
   * What kind of data went out on these connections:
   *  seen   - read in unencrypted traffic        likely - what this kind of destination usually gets
   *  could  - Android: the app holds a permission (e.g. location) and talks to ad/tracking companies
   */
  dataFor(ids) {
    const seen = new Map(), likely = new Map(), could = new Map(), services = new Map();
    const PERM = { location: 'Your location', contacts: 'Your contacts', camera: 'Photos or video from the camera', microphone: 'Audio from the microphone',
      phone: 'Phone number and device IDs', calls: 'Your call history', sms: 'Your text messages', calendar: 'Your calendar',
      photos: 'Your photos and videos', health: 'Health and fitness data', activity: 'Your physical activity' };
    for (const id of ids) {
      const c = this.conns.get(id); if (!c) continue;
      // a known service: its own documented list replaces the guess from the kind of company
      const prof = profileFor(c.host, this.platform, c.app?.name);
      if (prof) {
        const sp = services.get(prof.id) || { ...prof, conns: 0 };
        sp.conns++; services.set(prof.id, sp);
        prof.sends.forEach((label, i) => {
          const k = `${prof.id}:${i}`, x = likely.get(k) || { kind: k, label, details: new Set([prof.name]), count: 0, service: prof.id };
          x.count++; likely.set(k, x);
        });
      }
      for (const d of c.data || []) {
        if (prof && d.basis !== 'seen' && !GENERIC_KEEP.has(d.kind)) continue;
        const m = d.basis === 'seen' ? seen : likely;
        const x = m.get(d.kind) || { kind: d.kind, label: d.label, details: new Set(), count: 0 };
        x.count++; if (d.detail) x.details.add(d.detail);
        m.set(d.kind, x);
      }
      const app = this.apps.get(c.app.id);
      if (app?.perms?.length && TRACKING.has(c.category) || (app?.perms?.length && c.category === 'social')) {
        for (const p of app.perms) if (PERM[p] && !could.has(p)) could.set(p, { kind: p, label: `${PERM[p]} (the app is allowed to read it)`, details: new Set(), count: 1 });
      }
    }
    for (const k of seen.keys()) likely.delete(k); // seen beats likely
    const profs = [...services.values()];
    return { seen: [...seen.values()], likely: [...likely.values()], could: [...could.values()], services: profs,
      controls: this.controlsFor(ids, profs) };
  }

  /** "What you can do": steps for the companies these connections reached. */
  controlsFor(ids, profs = []) {
    const out = [], have = new Set(), owners = new Map();
    for (const id of ids) {
      const c = this.conns.get(id);
      if (c?.owner && c.scope === 'internet') {
        const o = owners.get(c.owner) || { ads: false };
        o.ads ||= TRACKING.has(c.category); owners.set(c.owner, o);
      }
    }
    for (const p of profs) if (p.owner && !owners.has(p.owner)) owners.set(p.owner, { ads: false });
    const add = (owner, list) => { for (const c of list) if (!have.has(c.label)) { have.add(c.label); out.push({ ...c, owner }); } };
    for (const p of profs) add(p.owner, controlsFor(p.owner, [p], this.platform, false));
    for (const [owner, o] of owners) add(owner, controlsFor(owner, [], this.platform, o.ads));
    return out;
  }

  topSites(m, n = 3) { return [...(m || new Map()).entries()].sort((a, b) => b[1] - a[1]).slice(0, n).map((x) => x[0]); }
  topOwner(m) { let best = null, n = 0; for (const [k, v] of m) if (v > n) { n = v; best = k; } return best; }

  summary() {
    const places = [...this.places.values()].filter((p) => p.scope === 'internet');
    const countries = new Set(places.map((p) => p.geo?.country).filter(Boolean));
    const tracking = places.filter((p) => TRACKING.has(this.topCat(p.cats))).length;
    return { places: places.length, countries: countries.size, tracking };
  }
}
