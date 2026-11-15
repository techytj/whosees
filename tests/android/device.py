"""Thorough test on a real Android phone (wireless debugging): live view with real apps, attribution,
app errors, speed, resource use, stop behaviour. Never uninstalls anything or changes app data.
Usage: WT_DEVICE=ip:port python3 tests/android/device.py      exit code = number of failures"""
import json, os, re, subprocess, sys, time

DEV = os.environ['WT_DEVICE']
SDK = os.path.expanduser('~/Android/Sdk'); ADB = [f'{SDK}/platform-tools/adb', '-s', DEV]
PKG = 'io.github.techytj.whosees'; NODE = os.path.expanduser('~/.local/node/bin/node'); PORT = 9334
OUT = os.environ.get('WT_OUT', '/tmp/wt-device'); os.makedirs(OUT, exist_ok=True)
APPS = [  # (package, friendly name, how to exercise it)
    ('com.netflix.mediaclient', 'Netflix', None),
    ('com.android.chrome', 'Chrome', 'https://en.wikipedia.org/wiki/World_map'),
    ('com.android.vending', 'Google Play Store', None),
]
NET_ERRORS = re.compile(r'UnknownHostException|SocketTimeoutException|ConnectException|SSLHandshakeException|NoRouteToHost|'
                        r'Unable to resolve host|ERR_NAME_NOT_RESOLVED|ERR_CONNECTION|ERR_TIMED_OUT|net::ERR_', re.I)
fails = 0; notes = []
def check(name, ok, detail=''):
    global fails
    print(('PASS' if ok else 'FAIL'), 'device:', name, '' if ok else str(detail)[:500])
    fails += 0 if ok else 1
def note(s): print('NOTE', s); notes.append(s)
def adb(*a, timeout=60): return subprocess.run([*ADB, *a], capture_output=True, text=True, errors='replace', timeout=timeout).stdout
def js(expr):
    r = subprocess.run([NODE, os.path.join(os.path.dirname(__file__), 'cdp.mjs'), str(PORT), expr], capture_output=True, text=True, timeout=40)
    try: return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception: return {'error': r.stdout + r.stderr}
def until(expr, t=20):
    end = time.time() + t
    while time.time() < end:
        if js(expr) is True: return True
        time.sleep(0.7)
    return js(expr)
def shot(name): open(os.path.join(OUT, f'phone-{name}.png'), 'wb').write(subprocess.run([*ADB, 'exec-out', 'screencap', '-p'], capture_output=True).stdout)
def front():
    adb('shell', 'am', 'start', '-n', f'{PKG}/io.github.techytj.wiretrace.MainActivity'); time.sleep(2)
    pid = adb('shell', 'pidof', PKG).strip()
    subprocess.run([*ADB, 'forward', f'tcp:{PORT}', f'localabstract:webview_devtools_remote_{pid}'], capture_output=True)
    return pid
def vpn_up():
    d = adb('shell', 'dumpsys', 'connectivity')
    return any('VPN' in l and 'Capabilities' in l and 'NOT_VPN' not in l for l in d.splitlines())

adb('shell', 'appops', 'set', PKG, 'ACTIVATE_VPN', 'allow')
# keep the screen on during the test (apps are paused when it sleeps); the owner's setting is restored at the end
orig_timeout = adb('shell', 'settings', 'get', 'system', 'screen_off_timeout').strip()
adb('shell', 'settings', 'put', 'system', 'screen_off_timeout', '1800000')
adb('shell', 'input', 'keyevent', 'KEYCODE_WAKEUP')
import atexit
atexit.register(lambda: adb('shell', 'settings', 'put', 'system', 'screen_off_timeout', orig_timeout or '60000'))
pid = front()
check('WhoSees UI loads on the phone', until("!!(window.__wt && window.__wt.map && window.__wt.map.loaded())", 40) is True)
before_settings = js("window.wt.getSettings()")
js("window.wt.setSettings({vpnExplained:true}).then(() => window.__wt.reloadSettings())")
t0 = time.time()
js("document.getElementById('startBtn').click()")
check('live view starts', until("window.__wt.session.mode === 'vpn' && document.getElementById('status').classList.contains('live')", 20) is True)
note(f'time to start live view: {time.time() - t0:.1f}s')
check('VPN active on the phone', vpn_up())
caps = [l for l in adb('shell', 'dumpsys', 'connectivity').splitlines() if 'VPN' in l and 'Capabilities' in l and 'NOT_VPN' not in l]
check('VPN not metered', any('NOT_METERED' in l for l in caps), caps[:1])
check('VPN shows Wi-Fi underneath', any('WIFI' in l for l in caps), caps[:1])
shot('live-start')

for pkg, name, url in APPS:
    if pkg not in adb('shell', 'pm', 'list', 'packages', pkg):
        note(f'{name} not installed, skipped'); continue
    adb('logcat', '-c')
    if url: adb('shell', 'am', 'start', '-a', 'android.intent.action.VIEW', '-d', url, '-p', pkg)
    else: adb('shell', 'monkey', '-p', pkg, '-c', 'android.intent.category.LAUNCHER', '1')
    time.sleep(14)
    shot(f'app-{name.replace(" ", "")}')
    apid = adb('shell', 'pidof', pkg).strip().split()
    log = adb('logcat', '-d', *(['--pid', apid[0]] if apid else []), '-t', '4000', timeout=60)
    errs = [l for l in log.splitlines() if NET_ERRORS.search(l)]
    check(f'{name}: no network errors in its log', not errs, errs[:3])
    front()
    seen = js(f"(() => {{ const a = window.__wt.session.apps.get('{pkg}'); return a ? {{conns: a.conns.size, sent: a.sent, recv: a.recv, places: a.places.size, sites: [...a.sites.keys()].slice(0, 6)}} : null; }})()")
    check(f'{name}: traffic seen and credited to {name}', isinstance(seen, dict) and seen.get('conns', 0) > 0, seen)
    if isinstance(seen, dict):
        check(f'{name}: website names learned', len(seen.get('sites') or []) > 0, seen)
        note(f'{name}: {seen}')

# speed: a 20 MB download in Chrome through the VPN
before = js("(() => { const a = window.__wt.session.apps.get('com.android.chrome'); return a ? a.recv : 0; })()") or 0
t0 = time.time()
adb('shell', 'am', 'start', '-a', 'android.intent.action.VIEW', '-d', 'https://speed.cloudflare.com/__down?bytes=20000000', '-p', 'com.android.chrome')
time.sleep(20)
front()
after = js("(() => { const a = window.__wt.session.apps.get('com.android.chrome'); return a ? a.recv : 0; })()") or 0
got = (after - before) / 1e6
note(f'download through the VPN: {got:.1f} MB in <= 20 s')
check('download works through the VPN (>= 5 MB in 20 s)', got >= 5, got)
for f in adb('shell', 'ls', '/sdcard/Download').split():
    if f.startswith('__down'): adb('shell', 'rm', f'/sdcard/Download/{f}')  # remove the test download

# resource use while live
cpu = adb('shell', 'top', '-b', '-n', '1', '-q', '-o', '%CPU,ARGS').splitlines()
cpu = [l for l in cpu if 'wiretrace' in l]
pss = re.search(r'TOTAL PSS:\s+(\d+)', adb('shell', 'dumpsys', 'meminfo', PKG))
note(f'CPU sample: {cpu[:1]}  memory: {int(pss.group(1)) // 1024 if pss else "?"} MB')
check('memory under 600 MB', pss and int(pss.group(1)) < 600 * 1024, pss and pss.group(1))

# UI on the real phone: an app's details (every feature is free)
js("document.querySelector('[data-tab=apps]').click()"); time.sleep(1); shot('ui-apps-free')
js("(() => { const a = [...window.__wt.session.apps.values()].sort((x, y) => y.recv - x.recv)[0]; document.querySelector('#list .row[data-app=\"' + CSS.escape(a.id) + '\"]').click(); })()")
time.sleep(1.5); shot('ui-app-detail')
check('details show what each app sent', js("!!document.querySelector('#detail .dataset') || !!document.querySelector('#detail .report')") is True)
js("document.querySelector('[data-back]')?.click()")

# stop
js("document.getElementById('stopBtn').click()"); time.sleep(3)
check('Stop ends the VPN', not vpn_up())
r = adb('shell', 'ping', '-c', '1', '-W', '3', '1.1.1.1')
check('internet works after Stop', ' 0% packet loss' in r, r[-200:])
# swiping the app away / killing it must not leave the VPN behind
js("document.getElementById('startBtn').click()"); until("document.getElementById('status').classList.contains('live')", 15)
adb('shell', 'am', 'force-stop', PKG); time.sleep(4)
check('killing WhoSees ends the VPN', not vpn_up())
front()
check('no page errors', not [l for l in adb('logcat', '-d', '-s', 'WhoSeesUI:I').splitlines() if 'Uncaught' in l])
print('NOTES:\n  ' + '\n  '.join(notes))
print(f'DEVICE {"OK" if fails == 0 else f"{fails} FAILED"} (screenshots in {OUT})')
sys.exit(fails)
