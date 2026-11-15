"""Android regression tests on the emulator: build, install, live view through the VPN, names, blocking, stop.
Drives the real app UI over the WebView DevTools protocol. Exit code = number of failures."""
import json, os, re, subprocess, sys, time

ROOT = os.environ.get('WT_ROOT') or os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
SDK = os.path.expanduser('~/Android/Sdk'); ADB = [f'{SDK}/platform-tools/adb', '-s', os.environ.get('WT_EMU', 'emulator-5560')]
PKG = 'io.github.techytj.whosees'; NODE = os.path.expanduser('~/.local/node/bin/node'); PORT = 9333
OUT = os.environ.get('WT_OUT', '/tmp/wt-android'); os.makedirs(OUT, exist_ok=True)
fails = 0
def check(name, ok, detail=''):
    global fails
    print(('PASS' if ok else 'FAIL'), 'android:', name, '' if ok else str(detail)[:400])
    fails += 0 if ok else 1
def adb(*a, timeout=60): return subprocess.run([*ADB, *a], capture_output=True, text=True, timeout=timeout).stdout
def js(expr):
    r = subprocess.run([NODE, os.path.join(os.path.dirname(__file__), 'cdp.mjs'), str(PORT), expr], capture_output=True, text=True, timeout=40)
    try: return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception: return {'error': r.stdout + r.stderr}
def until(expr, t=20):
    end = time.time() + t
    while time.time() < end:
        v = js(expr)
        if v is True: return True
        time.sleep(0.7)
    return js(expr)
def shot(name): open(os.path.join(OUT, f'android-{name}.png'), 'wb').write(subprocess.run([*ADB, 'exec-out', 'screencap', '-p'], capture_output=True).stdout)
# Android's nc closes the connection when its input ends, so keep input open until the reply arrives.
HTTP = "(printf 'GET / HTTP/1.1\\r\\nHost: example.com\\r\\nConnection: close\\r\\n\\r\\n'; sleep 3) | nc -w 5 example.com 80 | head -c 15"
def vpn_up(): return 'WhoSees' in adb('shell', 'dumpsys', 'connectivity') and 'VPN' in adb('shell', 'dumpsys', 'connectivity')

env = dict(os.environ, JAVA_HOME=os.path.expanduser('~/Android/Jdk' if False else '~/Android/jdk'), ANDROID_HOME=SDK)
b = subprocess.run(['./gradlew', '--no-daemon', '-q', 'assembleDebug'], cwd=os.path.join(ROOT, 'android'), env=env, capture_output=True, text=True, timeout=1800)
apk = os.path.join(ROOT, 'android/app/build/outputs/apk/debug/app-debug.apk')
check('debug APK builds', b.returncode == 0 and os.path.exists(apk), b.stdout[-500:] + b.stderr[-500:])
check('emulator is up', adb('shell', 'getprop', 'sys.boot_completed').strip() == '1')
adb('uninstall', PKG)
check('APK installs', 'Success' in adb('install', '-r', apk, timeout=300))
adb('shell', 'appops', 'set', PKG, 'ACTIVATE_VPN', 'allow')        # the VPN consent tap, pre-approved for the test
adb('shell', 'pm', 'grant', PKG, 'android.permission.POST_NOTIFICATIONS')
adb('shell', 'am', 'start', '-n', f'{PKG}/io.github.techytj.wiretrace.MainActivity')
time.sleep(4)
pid = adb('shell', 'pidof', PKG).strip()
subprocess.run([*ADB, 'forward', f'tcp:{PORT}', f'localabstract:webview_devtools_remote_{pid}'], capture_output=True)
check('UI loads in the WebView', until("!!(window.__wt && window.__wt.map && window.__wt.map.loaded())", 40) is True, js("document.title"))
check('Android bridge active', js("window.wt && window.wt.platform") == 'android')
check('wording says phone, not computer', js("document.querySelector('#hero p').textContent.includes('phone')") is True, js("document.querySelector('#hero p').textContent"))
check('home city guessed offline', until("/,/.test(document.getElementById('homeBtn').textContent)", 15) is True, js("document.getElementById('homeBtn').textContent"))
shot('idle')
# first Start shows the VPN explanation; Continue starts the VPN
js("document.getElementById('startBtn').click()")
check('VPN explanation shown before Android asks', until("!!document.getElementById('vpnGo')", 8) is True, js("document.getElementById('dlg').innerText"))
js("document.getElementById('vpnGo').click()")
check('live view starts (VPN mode)', until("window.__wt.session.mode === 'vpn' && document.getElementById('status').classList.contains('live')", 20) is True,
      js("[window.__wt.session.mode, document.getElementById('statusText').textContent]"))
check('Android shows the VPN as active', vpn_up())
vpninfo = [l for l in adb('shell', 'dumpsys', 'connectivity').splitlines() if 'Transports: WIFI|VPN' in l or ('VPN' in l and 'Capabilities' in l and 'NOT_VPN' not in l)]
check('VPN not marked metered (apps that avoid metered data still work)', any('NOT_METERED' in l for l in vpninfo), vpninfo[:1])
check('VPN carries the real network type (apps that check Wi-Fi/mobile still work)', any(('WIFI' in l or 'CELLULAR' in l) and 'VPN' in l for l in vpninfo), vpninfo[:1])
check('no IPv6 offered when the network has none', '::/0' not in adb('shell', 'ip', '-6', 'route', 'show', 'table', 'all'), '')
# traffic from the phone's shell through the VPN
r = adb('shell', HTTP, timeout=40)
check('internet works through the VPN', 'HTTP' in r, r)
# skip Chrome's first-run screens so it actually loads the page
adb('shell', 'am', 'set-debug-app', '--persistent', 'com.android.chrome')
adb('shell', "echo 'chrome --disable-fre --no-default-browser-check --no-first-run' > /data/local/tmp/chrome-command-line")
adb('shell', 'am', 'force-stop', 'com.android.chrome')
adb('shell', 'am', 'start', '-a', 'android.intent.action.VIEW', '-d', 'https://www.wikipedia.org', '-p', 'com.android.chrome')
time.sleep(8)
adb('shell', 'am', 'start', '-n', f'{PKG}/io.github.techytj.wiretrace.MainActivity')
time.sleep(2)
check('connections seen', until("window.__wt.session.conns.size > 0", 10) is True, js("window.__wt.session.conns.size"))
check('website name learned (example.com)', until("[...window.__wt.session.conns.values()].some(c => c.host === 'example.com')", 10) is True,
      js("[...window.__wt.session.conns.values()].map(c => c.host).filter(Boolean)"))
check('apps named from Android', js("[...window.__wt.session.apps.values()].some(a => a.name && !/^Unknown/.test(a.name))") is True,
      js("[...window.__wt.session.apps.values()].map(a => a.name)"))
check('destinations on the map', js("[...window.__wt.session.places.values()].some(p => p.scope === 'internet' && p.lat != null)") is True)
check('Chrome traffic attributed to Chrome', until("[...window.__wt.session.apps.values()].some(a => /chrome/i.test(a.name))", 10) is True,
      js("[...window.__wt.session.apps.values()].map(a => a.name)"))
shot('live')
# v1: no blocking UI; every feature is free
check('no Blocked tab in v1', js("!document.querySelector('[data-tab=blocked]')") is True)
check('plain HTTP request seen (page requested)', until("[...window.__wt.session.conns.values()].some(c => c.host === 'example.com' && (c.data||[]).some(d => d.basis === 'seen'))", 10) is True,
      js("[...window.__wt.session.conns.values()].filter(c => c.host === 'example.com').map(c => c.data)"))
pk = js("(() => { const p = [...window.__wt.session.places.values()].find(p => p.hosts.has('example.com')); return p && p.key; })()")
js(f"document.querySelector('[data-tab=places]').click(); document.querySelector('#list .row[data-place=\"{pk}\"]')?.click()")
check('no paywall', js("!document.querySelector('.teaser')") is True)
check('what was sent is shown to everyone', until("(() => { const p = [...window.__wt.session.places.values()].find(p => p.hosts.has('example.com')); if (!p) return false; document.querySelector('[data-tab=places]').click(); document.querySelector('#list .row[data-place=\"' + CSS.escape(p.key) + '\"]')?.click(); return !!document.querySelector('#detail .dataset'); })()", 20) is True,
      js("document.getElementById('detail').textContent.slice(0,200)"))
# stop
js("document.getElementById('stopBtn').click()")
time.sleep(2)
check('Stop ends the VPN', not vpn_up())
check('UI back to idle', js("document.body.classList.contains('idle')") is True)
r = adb('shell', HTTP, timeout=30)
check('internet works normally after Stop', 'HTTP' in r, r)
# Private DNS (hostname mode) hides website names: explained before Start, reminder after Stop once it's off
pd_orig = [adb('shell', 'settings', 'get', 'global', k).strip() for k in ('private_dns_mode', 'private_dns_specifier')]
adb('shell', 'settings', 'put', 'global', 'private_dns_mode', 'hostname'); adb('shell', 'settings', 'put', 'global', 'private_dns_specifier', 'dns.google')
check('Private DNS detected', until("window.wt.privateDns().then(p => p.server === 'dns.google')", 15) is True, js("window.wt.privateDns()"))
js("document.getElementById('startBtn').click()")
check('Private DNS explained before Start', until("!!document.getElementById('pdGo')", 8) is True, js("document.getElementById('dlg').innerText"))
check('explanation names the server and the fix', js("(t => t.includes('dns.google') && t.includes('Private DNS') && t.includes('Off'))(document.getElementById('dlg').innerText)") is True)
shot('private-dns')
js("document.getElementById('pdGo').click()")
check('Start anyway starts the live view', until("document.getElementById('status').classList.contains('live')", 20) is True)
check('live view notes missing names', until("!document.getElementById('toast').hidden && /Private DNS/.test(document.getElementById('toast').textContent)", 5) is True,
      js("document.getElementById('toast').textContent"))
r = adb('shell', HTTP, timeout=40)
check('internet works through the VPN with Private DNS on', 'HTTP' in r, r)
js("document.getElementById('stopBtn').click()"); time.sleep(2)
adb('shell', 'settings', 'put', 'global', 'private_dns_mode', 'off')
js("document.getElementById('startBtn').click()")
check('no Private DNS notice when it is off', until("document.getElementById('status').classList.contains('live')", 20) is True and js("document.getElementById('dlg').open") is False)
js("document.getElementById('stopBtn').click()")
check('reminder to turn Private DNS back on', until("/still off/.test(document.getElementById('toast').textContent) && !document.getElementById('toast').hidden", 8) is True,
      js("document.getElementById('toast').textContent"))
for k, v in zip(('private_dns_mode', 'private_dns_specifier'), pd_orig):
    if v in ('', 'null'): adb('shell', 'settings', 'delete', 'global', k)
    else: adb('shell', 'settings', 'put', 'global', k, v)
errs = [l for l in adb('logcat', '-d', '-s', 'WhoSeesUI:I').splitlines() if 'Uncaught' in l or 'TypeError' in l]
check('no page errors', not errs, errs[:3])
print(f'ANDROID {"OK" if fails == 0 else f"{fails} FAILED"} (screenshots in {OUT})')
sys.exit(fails)
