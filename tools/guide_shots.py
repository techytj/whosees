#!/usr/bin/env python3
"""Screenshots for the user guide (website/guide/), taken from the real app.
Runs the desktop app on a hidden screen with no network (so no personal apps appear), feeds it an
example session, clicks through each task, and records where the important buttons are so the guide
can put numbered markers on them.   Run:  unshare -rn python3 tools/guide_shots.py
Writes website/img/guide/<name>.webp and website/img/guide/marks.json"""
import json, os, subprocess, sys, urllib.parse

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'tests', 'ui'))
import driver  # noqa: E402

OUT = os.path.join(ROOT, 'website', 'img', 'guide')
TMP = os.environ.get('WT_GUIDE_TMP', '/tmp/wt-guide')
os.makedirs(OUT, exist_ok=True); os.makedirs(TMP, exist_ok=True)
HOME = {'city': 'Toronto', 'region': 'Ontario', 'country': 'CA', 'lat': 43.65, 'lon': -79.38}

# An example session: everyday apps talking to real kinds of companies, in real cities.
EXAMPLE = r"""
var CITY = {
  'Mountain View': ['California', 'US', 37.42, -122.08], 'Ashburn': ['Virginia', 'US', 39.04, -77.49], 'Dublin': ['Leinster', 'IE', 53.35, -6.26],
  'San Francisco': ['California', 'US', 37.77, -122.42], 'Frankfurt': ['Hesse', 'DE', 50.11, 8.68], 'Singapore': ['Singapore', 'SG', 1.29, 103.85],
  'Amsterdam': ['North Holland', 'NL', 52.37, 4.9], 'Chicago': ['Illinois', 'US', 41.88, -87.63], 'London': ['England', 'GB', 51.51, -0.13],
  'Montreal': ['Quebec', 'CA', 45.5, -73.57], 'Stockholm': ['Stockholm', 'SE', 59.33, 18.07], 'Tokyo': ['Tokyo', 'JP', 35.68, 139.69] };
var APPS = { weather: ['Daily Weather'], photo: ['Photo Studio'], notes: ['Quick Notes'], music: ['Music Player'], browser: ['Web Browser'], game: ['Puzzle Quest'] };
var N = 1, T0 = Date.now();
function conn(app, city, owner, cat, host, site, sent, recv, data, ip) {
  var c = CITY[city];
  return { t: 'open', id: N++, ts: T0, app: { id: 'demo:' + app, name: APPS[app][0], system: false }, proto: 'tcp', local: '192.168.1.20', lport: 50000 + N,
    remote: ip, rport: 443, scope: 'internet', geo: { city: city, region: c[0], country: c[1], lat: c[2], lon: c[3], org: owner },
    owner: owner, category: cat, host: host, site: site, service: 'HTTPS', what: 'Encrypted web traffic', encrypted: true,
    sent: sent, recv: recv, data: data || [], existing: false, demo: true };
}
var L = (k, l) => ({ basis: 'likely', kind: k, label: l });
var S = (k, l, d) => ({ basis: 'seen', kind: k, label: l, detail: d });
window.__guideEvents = [
  conn('weather', 'Mountain View', 'Google', 'ads', 'pubads.g.doubleclick.net', 'Google Marketing', 48200, 9100, [L('advertising-id', 'Advertising ID'), L('device', 'Device details'), L('ads', 'Which ads you see and tap')], '142.250.65.98'),
  conn('weather', 'Chicago', 'AppLovin', 'ads', 'ms.applovin.com', 'AppLovin', 31900, 4400, [S('location', 'Your location', 'lat=43.65 lon=-79.38'), L('advertising-id', 'Advertising ID')], '34.117.59.81'),
  conn('weather', 'San Francisco', 'AppsFlyer', 'analytics', 'launches.appsflyer.com', 'AppsFlyer', 12100, 2300, [L('usage', 'How you use the app'), L('device', 'Device details')], '52.85.12.40'),
  conn('weather', 'Ashburn', 'Amazon', 'cloud', 'api.dailyweather.example', null, 6400, 88100, [], '3.215.4.11'),
  conn('photo', 'Dublin', 'Meta', 'social', 'graph.facebook.com', 'Facebook', 22400, 6100, [L('usage', 'How you use the app'), L('advertising-id', 'Advertising ID')], '157.240.1.35'),
  conn('photo', 'Frankfurt', 'Google', 'analytics', 'app-measurement.com', 'Google Analytics', 9800, 1700, [L('usage', 'How you use the app')], '142.250.185.78'),
  conn('photo', 'Ashburn', 'Amazon', 'cloud', 'upload.photostudio.example', null, 412000, 9200, [], '3.215.4.12'),
  conn('notes', 'Montreal', 'Microsoft', 'cloud', 'sync.quicknotes.example', null, 8700, 15200, [], '20.151.32.9'),
  conn('music', 'Stockholm', 'Spotify', 'streaming', 'audio.musicplayer.example', null, 3100, 1840000, [], '35.186.224.25'),
  conn('music', 'London', 'Google', 'ads', 'googleads.g.doubleclick.net', 'Google Marketing', 7600, 2100, [L('advertising-id', 'Advertising ID')], '142.250.180.2'),
  conn('browser', 'Ashburn', 'Cloudflare', 'cdn', 'www.example-news.com', null, 18300, 642000, [], '104.18.32.7'),
  conn('browser', 'Amsterdam', 'Criteo', 'ads', 'bidder.criteo.com', 'Criteo', 14700, 3900, [L('advertising-id', 'Advertising ID'), L('browsing', 'Pages you visit')], '185.235.84.1'),
  conn('game', 'Singapore', 'Unity', 'ads', 'unityads.unity3d.com', 'Unity Ads', 26200, 51000, [L('advertising-id', 'Advertising ID'), L('device', 'Device details')], '35.201.70.40'),
  conn('game', 'Tokyo', 'Game server', 'other', 'eu.puzzlequest.example', null, 4100, 6300, [], '13.112.9.80'),
];
window.__guideAlert = { t: 'alert', demo: true, conn: 13, host: 'promo-reward-claim.example', remote: '35.201.70.40',
  alert: { severity: 'high', kind: 'malicious-domain', title: 'Puzzle Quest connected to a dangerous website',
           detail: 'promo-reward-claim.example is on a list of websites used for scams and phishing. Legitimate apps almost never connect to these.' } };
"""

# Helpers: where things are on screen, as percentages of the screenshot (for the guide's numbered markers).
MARK = r"""
var W = window.__wt, $ = (s) => document.querySelector(s);
var pct = (x, y) => [+(100 * x / innerWidth).toFixed(2), +(100 * y / innerHeight).toFixed(2)];
var at = (el, where) => { if (typeof el === 'string') el = $(el); if (!el) return null; var b = el.getBoundingClientRect();
  var x = where === 'l' ? b.left + 14 : where === 'r' ? b.right - 14 : b.left + b.width / 2, y = where === 't' ? b.top + 12 : b.top + b.height / 2; return pct(x, y); };
var GUIDE = (shot, marks) => console.log('GUIDE ' + JSON.stringify({ shot: shot, marks: marks }));
var dot = (city) => { var p = [...W.session.places.values()].find((x) => x.geo && x.geo.city === city); var g = p && W.flows.geom(p); return g ? pct(g.b.x, g.b.y) : null; };
var home = () => { var h = W.map.project([-79.38, 43.65]); return pct(h.x, h.y); };
var appRow = (name) => [...document.querySelectorAll('#list .row')].find((r) => r.textContent.includes(name));
"""


def run_desktop():
    S = []  # (shot name, at ms, js)
    def step(name, at, js): S.append((name, at, MARK + js))
    step('start', 2600, "GUIDE('start', {1: at('#startBtn'), 2: at('#deepChip'), 3: at('#homeBtn')});")
    step('location', 3600, "$('#homeBtn').click(); setTimeout(() => {}, 0); GUIDE('location', {1: at('#cityQ')});")
    step('deep', 5200, "$('#dlg').close(); W.reloadSettings && 0; window.wt.setSettings({deep: true, deepExplained: false}).then(() => W.reloadSettings()).then(() => $('#startBtn').click());")
    step('deepask', 6200, "GUIDE('deepask', {1: at('#goDeep'), 2: at('#useStd')});")
    step('go', 7000, "$('#useStd').click();")
    step('inject', 9000, EXAMPLE + """
      var orig = W.session.ingest.bind(W.session);
      W.session.ingest = (evs) => orig(evs.filter((e) => e.demo));   // only the example, not the engine
      var sent = 0, k = 0;
      setInterval(() => { k++; var r = 2000 + Math.round(18000 * Math.abs(Math.sin(k / 2.3)) + 6000 * Math.random()); sent += r;
        W.session.ingest([{ t: 'stats', demo: true, sent: 1040000 + sent, recv: 3280000 + sent * 6, rate_sent: r, open: 9 }]); }, 1000);
      W.session.ingest(window.__guideEvents.slice(0, 7));""")
    step('inject2', 10200, "W.session.ingest(window.__guideEvents.slice(7));")
    step('map', 14500, "GUIDE('map', {1: at('#stats', 'l'), 2: home(), 3: dot('Dublin'), 4: at('#legend', 'l'), 5: at('.tabs'), 6: at('#stopBtn')});")
    step('apps', 15500, "$('[data-tab=apps]').click(); setTimeout(() => {}, 0); GUIDE('apps', {1: at(appRow('Daily Weather'), 'l'), 2: at('#list .row .chip'), 3: at('#search')});")
    step('appdetail', 16800, "appRow('Daily Weather').click(); setTimeout(() => {}, 0); GUIDE('appdetail', {1: at('#detail .sentence', 'l'), 2: at('#detail .report .grade'), 3: at('#detail .dataset', 'l'), 4: at('#detail [data-back]', 'l')});")
    step('appdetail2', 18000, "$('#detail').scrollTop = 99999; GUIDE('appdetail2', {});")
    step('hover', 19600, """$('#detail [data-back]') && $('#detail [data-back]').click();
      var p = [...W.session.places.values()].find((x) => x.geo && x.geo.city === 'Chicago'); var g = W.flows.geom(p);
      document.elementFromPoint(g.b.x, g.b.y).dispatchEvent(new MouseEvent('mousemove', {clientX: g.b.x, clientY: g.b.y, bubbles: true}));
      GUIDE('hover', {1: pct(g.b.x, g.b.y), 2: at('#tip', 't')});""")
    step('places', 21000, "var cv = W.map.getCanvas(); cv.dispatchEvent(new MouseEvent('mousemove', {clientX: 60, clientY: innerHeight - 140, bubbles: true})); cv.dispatchEvent(new MouseEvent('mouseleave', {bubbles: true})); $('#tip').hidden = true; $('[data-tab=places]').click(); GUIDE('places', {1: at('[data-tab=places]'), 2: at('#list .row', 'l')});")
    step('feed', 22400, "$('[data-tab=feed]').click(); GUIDE('feed', {1: at('[data-tab=feed]'), 2: at('#list .row', 'l')});")
    step('search', 23800, "var q = $('#search input') || $('#search'); q.value = 'google'; q.dispatchEvent(new Event('input', {bubbles: true})); GUIDE('search', {1: at('#search'), 2: at('#list .row', 'l')});")
    step('legend', 25200, "var q = $('#search input') || $('#search'); q.value = ''; q.dispatchEvent(new Event('input', {bubbles: true})); var ch = $('#legend .chip[data-cat=ads]'); ch && ch.click(); GUIDE('legend', {1: at(ch)});")
    step('expert', 26800, "var ch = $('#legend .chip[data-cat=ads]'); ch && ch.click(); $('[data-mode=expert]').click(); $('[data-tab=feed]').click(); GUIDE('expert', {1: at('[data-mode=expert]'), 2: at('#list .row', 'l')});")
    step('alert', 28600, "$('[data-mode=simple]').click(); $('[data-tab=apps]').click(); W.session.ingest([window.__guideAlert]);")
    step('alertcard', 30000, "GUIDE('alertcard', {1: at('#alertStack .alert-card', 'l'), 2: at('#alertStack [data-alert-trust]'), 3: at('#alertBadge')});")
    step('alerts', 31400, "var t = $('#alertStack [data-alert-trust]'); t && t.click(); $('[data-tab=alerts]').click(); GUIDE('alerts', {1: at('[data-tab=alerts]'), 2: at('#list .row, #list .alert-card', 'l')});")
    step('settings', 32800, "$('#settingsBtn').click(); GUIDE('settings', {1: at('#settingsBtn')});")
    step('support', 34200, "document.querySelector('#dlg [data-support]').click(); GUIDE('support', {1: at('#dlg .tips')});")
    step('stop', 35600, "$('#dlg').close(); GUIDE('stop', {1: at('#stopBtn')});")

    ud = os.path.join(TMP, 'ud-desk'); os.makedirs(ud, exist_ok=True)
    json.dump({'theme': 'dark', 'home': HOME, 'homeGuessed': False, 'mode': 'simple', 'updatePromptSeen': True}, open(os.path.join(ud, 'settings.json'), 'w'))
    driver.ensure_display('wt-guide', 1440, 900)
    spec = ','.join(f"{n}:{at}:{urllib.parse.quote(js)}" for n, at, js in S)
    env = dict(os.environ, WAYLAND_DISPLAY='wt-guide', WT_SHOT=os.path.join(TMP, 'd'), WT_SHOT_STEPS=spec)
    p = subprocess.run([driver.ELECTRON, driver.APP, '--ozone-platform=wayland', '--no-sandbox', f'--user-data-dir={ud}'], env=env, capture_output=True, text=True, timeout=120)
    marks = {}
    for line in (p.stdout + p.stderr).splitlines():
        if 'GUIDE {' in line:
            g = json.loads(line.split('GUIDE ', 1)[1]); marks[g['shot']] = {k: v for k, v in g['marks'].items() if v}
        if 'FAIL' in line and 'CHECK step-' in line: print(line)
    return marks


# ------------------------------------------------------------------ Android (emulator, debug build)
SDK = os.path.expanduser('~/Android/Sdk'); ADB = [f'{SDK}/platform-tools/adb', '-s', os.environ.get('WT_EMU', 'emulator-5560')]
PKG = 'io.github.techytj.whosees'; NODE = os.path.expanduser('~/.local/node/bin/node'); PORT = 9335

def adb(*a, timeout=60): return subprocess.run([*ADB, *a], capture_output=True, text=True, errors='replace', timeout=timeout).stdout
def js(expr):
    r = subprocess.run([NODE, os.path.join(ROOT, 'tests/android/cdp.mjs'), str(PORT), expr], capture_output=True, text=True, timeout=40)
    try: return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception: return {'error': r.stdout + r.stderr}
def wait(expr, t=20):
    import time; end = time.time() + t
    while time.time() < end:
        if js(expr) is True: return True
        time.sleep(0.5)
    return False
def cap(name):
    open(os.path.join(TMP, f'p-{name}.png'), 'wb').write(subprocess.run([*ADB, 'exec-out', 'screencap', '-p'], capture_output=True).stdout)
def marks(expr):  # run MARK helpers in the WebView and return {n: [x%, y%]}
    v = js('(() => {' + MARK.replace('var GUIDE', 'var _G') + ' return (' + expr + '); })()')
    return {k: x for k, x in (v or {}).items() if x} if isinstance(v, dict) else {}
def front():
    import time
    adb('shell', 'am', 'start', '-n', f'{PKG}/io.github.techytj.wiretrace.MainActivity'); time.sleep(3)
    pid = adb('shell', 'pidof', PKG).strip()
    subprocess.run([*ADB, 'forward', f'tcp:{PORT}', f'localabstract:webview_devtools_remote_{pid}'], capture_output=True)

def run_android():
    import re, time
    apk = os.path.join(ROOT, 'android/app/build/outputs/apk/debug/app-debug.apk')
    adb('install', '-r', apk, timeout=300)
    adb('shell', 'pm', 'clear', PKG); adb('shell', 'pm', 'grant', PKG, 'android.permission.POST_NOTIFICATIONS')
    adb('shell', 'appops', 'set', PKG, 'ACTIVATE_VPN', 'default')      # so Android shows its own VPN question
    pd = [adb('shell', 'settings', 'get', 'global', k).strip() for k in ('private_dns_mode', 'private_dns_specifier')]
    adb('shell', 'settings', 'put', 'global', 'private_dns_mode', 'off')
    front(); wait("!!(window.__wt && window.__wt.map && window.__wt.map.loaded())", 40)
    out_pre = {}
    if wait("!!document.getElementById('updNo')", 10):   # the first-launch update question, for the guide
        time.sleep(0.8); cap('updates'); out_pre['updates'] = marks("{1: at('#updNo'), 2: at('#updYes')}")
        js("document.getElementById('updNo').click()"); time.sleep(1)
    js(f"window.wt.setSettings({{home: {json.dumps(HOME)}, homeGuessed: false, theme: 'dark'}}).then(() => window.__wt.reloadSettings())"); time.sleep(2)
    out = dict(out_pre)
    cap('start'); out['start'] = marks("{1: at('#startBtn'), 2: at('#homeBtn')}")
    js("document.getElementById('startBtn').click()"); wait("!!document.getElementById('vpnGo')", 8); time.sleep(0.8)
    cap('vpnexplain'); out['vpnexplain'] = marks("{1: at('#vpnGo')}")
    js("document.getElementById('vpnGo').click()"); time.sleep(3)
    cap('vpnsystem')
    adb('shell', 'uiautomator', 'dump', '/sdcard/ui.xml'); ui = adb('shell', 'cat', '/sdcard/ui.xml')
    m = re.search(r'text="OK"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', ui) or re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*text="OK"', ui)
    if m:
        x1, y1, x2, y2 = map(int, m.groups()); out['vpnsystem'] = {'1': [round(100 * (x1 + x2) / 2 / 1080, 2), round(100 * (y1 + y2) / 2 / 2400, 2)]}
        adb('shell', 'input', 'tap', str((x1 + x2) // 2), str((y1 + y2) // 2))
    wait("document.getElementById('status').classList.contains('live')", 25); time.sleep(2)
    js("(() => {" + EXAMPLE + """
      var W = window.__wt; var ls = W.session.listeners; W.session.reset(); W.session.listeners = ls;   // keep the app's own listeners
      var orig = W.session.ingest.bind(W.session);
      W.session.ingest = (evs) => orig(evs.filter((e) => e.demo));
      var sent = 0, k = 0; window.__demoStats = setInterval(() => { k++; var r = 1500 + Math.round(9000 * Math.abs(Math.sin(k / 2.3)) + 3000 * Math.random()); sent += r;
        W.session.ingest([{ t: 'stats', demo: true, sent: 820000 + sent, recv: 2600000 + sent * 6, rate_sent: r, open: 8 }]); }, 1000);
      W.session.ingest(window.__guideEvents); return true; })()""")
    time.sleep(6)
    cap('live'); out['live'] = marks("{1: at('#stats', 'l'), 2: home(), 3: at('.tabs'), 4: at('#stopBtn')}")
    js("(() => { document.querySelector('[data-tab=apps]').click(); const r = [...document.querySelectorAll('#list .row')].find((x) => x.textContent.includes('Daily Weather')); r.click(); document.getElementById('panel').classList.add('max'); return true; })()")
    time.sleep(1.5)
    cap('appdetail'); out['appdetail'] = marks("{1: at('#detail .sentence', 'l'), 2: at('#detail .report .grade'), 3: at('#detail .dataset', 'l')}")
    cap('appdetail-max')
    js("(() => { const b = document.querySelector('#detail [data-back]'); if (b) b.click(); return true; })()"); time.sleep(0.8)
    js("(() => { document.getElementById('panel').classList.remove('max'); return true; })()"); time.sleep(0.8)
    js("(() => { window.__wt.session.ingest([window.__guideAlert]); return document.querySelectorAll('#alertStack .alert-card').length; })()")
    time.sleep(1.5)
    cap('alert'); out['alert'] = marks("{1: at('#alertStack .alert-card', 'l'), 2: at('#alertStack [data-alert-trust]')}")
    # Private DNS notice
    js("(() => { clearInterval(window.__demoStats); document.getElementById('stopBtn').click(); return true; })()"); time.sleep(3)
    adb('shell', 'settings', 'put', 'global', 'private_dns_mode', 'hostname'); adb('shell', 'settings', 'put', 'global', 'private_dns_specifier', 'dns.google')
    js("window.wt.setSettings({privateDnsNoted: false}).then(() => window.__wt.reloadSettings())"); time.sleep(1)
    js("document.getElementById('startBtn').click()"); wait("!!document.getElementById('pdGo')", 10); time.sleep(0.8)
    cap('privatedns'); out['privatedns'] = marks("{1: at('#pdSettings'), 2: at('#pdGo')}")
    js("(() => { document.getElementById('dlg').close(); return true; })()")
    for k, v in zip(('private_dns_mode', 'private_dns_specifier'), pd):
        if v in ('', 'null'): adb('shell', 'settings', 'delete', 'global', k)
        else: adb('shell', 'settings', 'put', 'global', k, v)
    adb('shell', 'am', 'force-stop', PKG)
    return out


if __name__ == '__main__' and 'android' in sys.argv:
    m = run_android()
    for k in m.keys() | {'vpnsystem'}:
        src = os.path.join(TMP, f'p-{k}.png')
        if os.path.exists(src): subprocess.run(['magick', src, '-resize', '540x', '-quality', '84', os.path.join(OUT, f'p-{k}.webp')], check=True)
    old = json.load(open(os.path.join(OUT, 'marks.json'))) if os.path.exists(os.path.join(OUT, 'marks.json')) else {}
    old.update({f'p-{k}': v for k, v in m.items()}); json.dump(old, open(os.path.join(OUT, 'marks.json'), 'w'), indent=1)
    print('android shots:', sorted(m))
elif __name__ == '__main__':
    marks = run_desktop()
    keep = ['start', 'location', 'deepask', 'map', 'apps', 'appdetail', 'appdetail2', 'hover', 'places', 'feed', 'search', 'expert', 'alertcard', 'alerts', 'settings', 'support']
    for k in keep:
        src = os.path.join(TMP, f'd-{k}.png')
        if os.path.exists(src):
            subprocess.run(['magick', src, '-quality', '84', os.path.join(OUT, f'd-{k}.webp')], check=True)
        else:
            print('missing shot', k)
    old = json.load(open(os.path.join(OUT, 'marks.json'))) if os.path.exists(os.path.join(OUT, 'marks.json')) else {}
    old.update({f'd-{k}': v for k, v in marks.items()})
    json.dump(old, open(os.path.join(OUT, 'marks.json'), 'w'), indent=1)
    print(f'{len(keep)} desktop shots; marks for {len(marks)}')
