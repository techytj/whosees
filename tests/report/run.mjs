// Report unit tests: build the report HTML from made-up sessions and check what it says.
// (The PDF itself is made and checked by the UI tests, in the real app.)  Run: node tests/report/run.mjs
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', '..');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'wt-report-'));
for (const f of ['model.js', 'report.js']) fs.copyFileSync(path.join(ROOT, 'desktop/app/renderer', f), path.join(tmp, f));
fs.writeFileSync(path.join(tmp, 'package.json'), '{"type":"module"}');
const { Session } = await import(pathToFileURL(path.join(tmp, 'model.js')));
const R = await import(pathToFileURL(path.join(tmp, 'report.js')));

let fails = 0;
const check = (name, ok, detail = '') => { console.log(`${ok ? 'PASS' : 'FAIL'} report: ${name}${ok ? '' : ' ' + JSON.stringify(detail).slice(0, 300)}`); if (!ok) fails++; };
const HOME = { city: 'Toronto', country: 'CA', lat: 43.65, lon: -79.38 };

function session({ n = 40, evil = false, plain = false, alerts = false, blocked = false } = {}) {
  const s = new Session();
  const t0 = Date.now() - 10 * 60e3;
  const ev = [{ t: 'hello', mode: 'deep', blocking: true }];
  const dests = [['www.google-analytics.com', 'Google', 'analytics', 'US', 'Ashburn', 39, -77.5], ['graph.facebook.com', 'Meta', 'social', 'IE', 'Dublin', 53.3, -6.3],
    ['cdn.example.net', 'Cloudflare', 'cdn', 'CA', 'Toronto', 43.7, -79.4], ['tracker.adjust.com', 'Adjust', 'tracker', 'DE', 'Berlin', 52.5, 13.4]];
  for (let i = 1; i <= n; i++) {
    const d = dests[i % dests.length];
    const app = i % 3 ? { id: 'firefox', name: 'Firefox', exe: '/usr/bin/firefox' } : { id: 'weird', name: evil ? '<script>alert(1)</script>Evil & "Co"' : 'Weather', exe: '/opt/w' };
    const unenc = plain && i === 2;
    ev.push({ t: 'open', id: i, ts: t0 + i * 1000, proto: 'tcp', service: unenc ? 'http' : 'https', what: 'Web', encrypted: !unenc, scope: 'internet',
      remote: `203.0.113.${i}`, rport: unenc ? 80 : 443, app, owner: d[1], category: d[2], host: evil && i === 3 ? '<img src=x onerror=alert(1)>.example' : d[0], site: d[0],
      geo: { country: d[3], city: d[4], lat: d[5], lon: d[6] }, blocked: blocked && i === 4, sent: 0, recv: 0,
      data: unenc ? [{ kind: 'location', label: 'Your location', basis: 'seen', detail: 'lat=43.6' }] : [] });
    ev.push({ t: 'update', id: i, sent: 1000 * i, recv: 5000, ds: 1000 * i, dr: 5000 });
  }
  ev.push({ t: 'open', id: n + 1, ts: t0, proto: 'udp', scope: 'lan', remote: '192.168.1.5', rport: 5353, app: { id: 'avahi', name: 'Avahi' }, category: 'local', geo: {}, sent: 0, recv: 0 });
  for (let i = 0; i < 30; i++) ev.push({ t: 'stats', sent: i * 1000, recv: i * 2000, rate_sent: 500 + i * 10, open: 3 });
  if (alerts) ev.push({ t: 'alert', conn: 1, host: 'evil.example', remote: '203.0.113.1', alert: { severity: 'high', kind: 'malicious-website', title: 'Firefox connected to a dangerous website', detail: 'evil.example is on a malware list.', block: { kind: 'host', value: 'evil.example', label: 'evil.example' } } });
  s.ingest(ev);
  s.started = t0; s.ended = t0 + 10 * 60e3;
  return s;
}
const text = (html) => html.replace(/<style>[\s\S]*?<\/style>/, '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');

// ---- a normal session
const s1 = session({ plain: true, alerts: true, blocked: true });
const h1 = R.buildReport(s1, { platform: 'linux', version: '9.9.9', theme: 'dark', paper: 'letter', home: HOME, rules: [{ kind: 'host', value: 'evil.example', label: 'evil.example' }] });
const t1 = text(h1);
check('model counts session bytes per connection', [...s1.conns.values()].find((c) => c.id === 5)?.ss === 5000, [...s1.conns.values()].find((c) => c.id === 5));
check('model keeps a send-rate log for the whole live view', s1.rateLog.length === 30, s1.rateLog.length);
for (const sec of ['Key findings', 'Apps', 'Companies', 'Countries', 'Tracking and advertising', 'Unencrypted connections', 'Threat alerts', 'Blocking', 'Every connection', 'About this report'])
  check(`has section: ${sec}`, t1.includes(sec), '');
check('cover headline', t1.includes('What your computer sent, and who received it'), t1.slice(0, 200));
check('cover says nothing was uploaded', t1.includes('Nothing in this report was uploaded'), '');
check('names the apps', t1.includes('Firefox') && t1.includes('Weather'), '');
check('names the companies and countries', ['Google', 'Meta', 'Cloudflare', 'Adjust', 'United States', 'Ireland', 'Germany'].every((w) => t1.includes(w)), '');
check('counts trackers (Google analytics + Adjust)', /2 of the 4 companies/.test(t1), t1.match(/\d+ of the \d+ companies/));
check('reports data seen in readable traffic', t1.includes('Your location'), '');
check('lists the unencrypted connection', /1 connection was not encrypted/.test(t1), '');
check('includes the threat alert', t1.includes('Firefox connected to a dangerous website'), '');
check('includes the block list and blocked attempts', t1.includes('Your block list') && t1.includes('evil.example') && /blocked 1 attempt/.test(t1), '');
check('every connection is listed (41)', (h1.match(/<tr( class="blk")?><td class="mono">/g) || []).length >= 41, (h1.match(/<tr( class="blk")?><td class="mono">/g) || []).length);
check('share of data that left Canada', /\d+% left Canada/.test(t1), '');
check('version and DB-IP attribution', t1.includes('WhoSees 9.9.9') && t1.includes('DB-IP.com'), '');
check('no undefined / NaN / [object Object]', !/undefined|NaN|\[object Object\]/.test(t1), t1.match(/.{40}(undefined|NaN|\[object Object\]).{40}/)?.[0]);
check('letter paper by default here', /@page\{size:letter/.test(h1), '');
check('page numbers in the footer', h1.includes('counter(pages)'), '');
check('loads nothing from outside the document', !/(src|href)="(https?:)?\/\//.test(h1) && !/url\((https?:)?\/\//.test(h1), h1.match(/(src|href)="https?:[^"]+/)?.[0]);

// ---- hostile names from the network are shown as text, never run
const h2 = R.buildReport(session({ evil: true }), { platform: 'linux', theme: 'light', paper: 'a4', home: HOME });
check('app and website names are escaped', !h2.includes('<script>alert(1)') && !h2.includes('<img src=x') && h2.includes('&lt;script&gt;'), h2.match(/.{30}alert\(1\).{30}/)?.[0]);
check('A4 paper', /@page\{size:A4/.test(h2), '');
check('light style', h2.includes('--bg:#ffffff'), '');

// ---- a session where nothing went out
const s3 = new Session(); s3.ingest([{ t: 'hello', mode: 'standard' }]); s3.started = Date.now() - 60e3; s3.ended = Date.now();
const t3 = text(R.buildReport(s3, { platform: 'android', theme: 'dark', paper: 'letter', home: HOME }));
check('empty live view: says nothing was sent', t3.includes('nothing on your phone sent data to the internet'), t3.slice(0, 300));
check('empty live view: still a valid report', t3.includes('About this report') && !/undefined|NaN/.test(t3), '');
check('Standard mode limits are explained', t3.includes('Standard mode'), '');

// ---- connections that sent nothing yet: no "0%" sentences
const s5 = new Session(); s5.ingest([{ t: 'hello', mode: 'standard' }, { t: 'open', id: 1, ts: Date.now(), proto: 'tcp', encrypted: true, scope: 'internet', remote: '20.1.1.1', rport: 443,
  app: { id: 'svc', name: 'Windows service host' }, owner: 'Microsoft', category: 'cloud', geo: { country: 'US', city: 'Ashburn', lat: 39, lon: -77.5 }, sent: 0, recv: 0 }]);
s5.started = Date.now() - 20e3; s5.ended = Date.now();
const t5 = text(R.buildReport(s5, { platform: 'win32', theme: 'light', paper: 'a4', home: HOME }));
check('nothing sent yet: says so plainly', t5.includes('but sent no data yet') && !/\(0%\)|0% left/.test(t5), t5.slice(0, 400));

// ---- Standard mode can't block: the report must not say anything was blocked
const s6 = session({}); s6.blocking = false;
const t6 = text(R.buildReport(s6, { platform: 'linux', theme: 'dark', paper: 'letter', home: HOME, rules: [{ kind: 'company', value: 'Meta', label: 'Meta' }] }));
check("blocking off: says the list wasn't applied", t6.includes("Blocking wasn't on during this live view") && !/WhoSees (stopped|blocked) \d/.test(t6), t6.match(/Blocking.{0,200}/)?.[0]);

// ---- blocked from the first lookup: no connection ever opened, but the firewall stopped attempts
const s7 = session({ n: 8 });
const crit = { host: 'bidder.criteo.com', owner: 'Criteo', category: 'advertising', site: 'Criteo', scope: 'internet', geo: { country: 'FR', city: 'Paris', lat: 48.9, lon: 2.3 } };
s7.ingest([{ t: 'blockstats', ips: { '185.235.84.1': 2 }, where: { '185.235.84.1': crit } }, { t: 'blockstats', ips: { '185.235.84.1': 3 } }]);
const pc = [...s7.places.values()].find((p) => p.owners.has('Criteo'));
check('stopped-only address gets a place', !!pc && pc.conns.size === 0 && pc.stops.has('185.235.84.1') && pc.hosts.has('bidder.criteo.com'), pc && { conns: pc.conns.size, owners: [...pc.owners.keys()] });
check('stopped-only place counts the latest firewall hits', pc && s7.stoppedAt(pc) === 3, pc && s7.stoppedAt(pc));
check('stopped-only address adds no app or connection', s7.apps.size === session({ n: 8 }).apps.size && s7.conns.size === session({ n: 8 }).conns.size, s7.apps.size);
s7.ingest([{ t: 'blockstats', ips: { '203.0.113.1': 4, '185.235.84.1': 3 }, where: { '203.0.113.1': { ...crit, owner: 'Google', geo: { country: 'US', city: 'Ashburn', lat: 39, lon: -77.5 } } } }]);
check('an address that already has a connection is not added twice', ![...s7.places.values()].some((p) => p.stops?.has('203.0.113.1')), '');
const t7 = text(R.buildReport(s7, { platform: 'linux', theme: 'light', paper: 'letter', home: HOME, rules: [{ kind: 'company', value: 'Criteo', label: 'Criteo' }] }));
check('report: attempts stopped before connecting are reported', /WhoSees stopped \d+ attempts during this live view, to [^.]*Criteo/.test(t7) && !t7.includes('Nothing on the list was contacted'), t7.match(/Your block list.{0,300}/)?.[0]);
const s8 = session({ n: 8 }); // same address seen on several connections: its hits count once
s8.ingest([{ t: 'blockstats', ips: { '203.0.113.4': 5 } }, { t: 'open', id: 99, ts: Date.now(), proto: 'tcp', scope: 'internet', remote: '203.0.113.4', rport: 443, app: { id: 'firefox', name: 'Firefox' }, owner: 'Adjust', category: 'tracker', geo: { country: 'DE', city: 'Berlin', lat: 52.5, lon: 13.4 }, sent: 0, recv: 0 }]);
const pb = [...s8.places.values()].find((p) => p.owners.has('Adjust'));
check('an address on several connections counts its stopped attempts once', pb && s8.stoppedAt(pb) === 5, pb && s8.stoppedAt(pb));

// ---- very long live view: the connection list is capped, and says so
const s4 = session({ n: R.MAX_ROWS + 50 });
const t4 = text(R.buildReport(s4, { platform: 'win32', theme: 'dark', paper: 'letter', home: HOME }));
check('long live view: connection list capped with a note', t4.includes(`the ${R.MAX_ROWS} most recent are listed`), '');
check('Windows wording', t4.includes('Windows computer'), '');

// ---- helpers
check('file name has date and time', /^WhoSees report \d{4}-\d\d-\d\d \d{4}\.pdf$/.test(R.reportFileName()), R.reportFileName());
check('paper: Letter in Canada/US, A4 in UK/Germany', R.paperFor('en-CA') === 'letter' && R.paperFor('en-US') === 'letter' && R.paperFor('en-GB') === 'a4' && R.paperFor('de-DE') === 'a4', '');
check('durations read naturally', R.duration(45e3) === '45 s' && R.duration(14 * 60e3) === '14 min' && R.duration(125 * 60e3) === '2 h 05 min', [R.duration(45e3), R.duration(14 * 60e3), R.duration(125 * 60e3)]);

fs.rmSync(tmp, { recursive: true, force: true });
console.log(`REPORT ${fails ? `${fails} FAILED` : 'OK'}`);
process.exit(fails);
