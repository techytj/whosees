"""Packaging regression: build Linux AppImage + rpm and the Windows installer, then smoke-test them."""
import glob, json, os, subprocess, sys, tempfile, time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
APP = os.path.join(ROOT, 'desktop/app')
def _local(name):  # your machines live in tools/local.env (not in the repo); see tools/local.env.example
    if name in os.environ: return os.environ[name]
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'tools', 'local.env')
    for l in open(p) if os.path.exists(p) else []:
        k, _, v = l.strip().partition('=')
        if k == name: return v.strip().strip('"\'')
    sys.exit(f'set {name} in tools/local.env')
VM = _local('VM')
NODE = os.path.expanduser('~/.local/node/bin')
fails = 0

def check(name, ok, detail=''):
    global fails
    print(('PASS' if ok else 'FAIL'), 'packaging:', name, '' if ok else str(detail)[-400:])
    fails += 0 if ok else 1

env = dict(os.environ, PATH=NODE + ':' + os.environ['PATH'])
b = subprocess.run(['npx', 'electron-builder', '--linux', 'AppImage'], cwd=APP, env=env, capture_output=True, text=True, timeout=1200)
img = glob.glob(os.path.join(APP, 'dist', 'WhoSees-*.AppImage'))
check('AppImage builds', b.returncode == 0 and img, b.stdout + b.stderr)
r = subprocess.run([os.path.join(ROOT, 'desktop/packaging/build-rpm.sh')], capture_output=True, text=True, timeout=900)
rpm = sorted(glob.glob(os.path.join(APP, 'dist', 'whosees-*.rpm')), key=os.path.getmtime)
check('rpm builds', r.returncode == 0 and rpm, r.stdout + r.stderr)
if rpm:
    files = subprocess.run(['rpm', '-qlp', rpm[-1]], capture_output=True, text=True).stdout
    for f in ['/opt/WhoSees/resources/agent/whosees-agent', '/opt/WhoSees/resources/shared/geo/world.wtgeo',
              '/opt/WhoSees/resources/shared/map/world-z6.pmtiles', '/usr/share/applications/whosees.desktop',
              '/usr/share/polkit-1/actions/io.github.techytj.whosees.policy', '/usr/bin/whosees',
              '/opt/WhoSees/resources/shared/threats/domains.txt', '/opt/WhoSees/resources/shared/threats/ips.txt']:
        check(f'rpm contains {f}', f in files, '')
    reqs = subprocess.run(['rpm', '-qRp', rpm[-1]], capture_output=True, text=True).stdout
    check('rpm requires polkit + nftables', 'polkit' in reqs and 'nftables' in reqs, reqs)
if img:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'ui')); import driver
    driver.ensure_display('wt-shot', 1440, 900)  # its own hidden screen, whatever ran before
    ft = subprocess.run(['file', '-L', img[0]], capture_output=True, text=True).stdout
    check('AppImage runtime is static (runs without libfuse2)', 'static' in ft and 'dynamically linked' not in ft, ft)
    ud = tempfile.mkdtemp(prefix='wt-appimage-'); netlog = os.path.join(ud, 'net.json')
    # first launch, in a language whose spellcheck dictionary Chromium would otherwise download from Google
    p = subprocess.Popen([img[0], '--ozone-platform=wayland', f'--user-data-dir={ud}', f'--log-net-log={netlog}'],
                         env=dict(os.environ, WAYLAND_DISPLAY='wt-shot', LANG='de_DE.UTF-8', LC_ALL='de_DE.UTF-8'),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(12); p.terminate()
    try: p.wait(10)
    except Exception: p.kill()
    try: home = json.load(open(os.path.join(ud, 'settings.json'))).get('home')
    except Exception: home = None
    check('AppImage starts and its agent works (home city found)', bool(home), home)
    log = open(os.path.join(ud, 'wiretrace.log')).read() if os.path.exists(os.path.join(ud, 'wiretrace.log')) else ''
    check('AppImage page has no errors', 'Uncaught' not in log and 'Error' not in log, log[-300:])
    import re
    urls = sorted(set(re.findall(r'"url":"(https?://[^"]+)"', open(netlog).read() if os.path.exists(netlog) else '')))
    check('AppImage sends nothing on first launch (no network requests at all)', os.path.exists(netlog) and not urls, urls[:5])

# Windows installer (built inside the VM)
w = subprocess.run([os.path.join(ROOT, 'tools/vm-dist.sh')], capture_output=True, text=True, timeout=1800)
exe = glob.glob(os.path.join(APP, 'dist', 'WhoSees Setup *.exe'))
check('Windows installer builds', w.returncode == 0 and exe and time.time() - os.path.getmtime(exe[0]) < 1800, w.stdout[-400:] + w.stderr[-400:])
s = subprocess.run(['ssh', '-o', 'BatchMode=yes', VM, 'powershell -NoProfile -Command "Remove-Item -Recurse -Force C:\\wiretrace\\ud-test -ea 0; '
                    "Remove-Item -Force C:\\wiretrace\\net-test.json -ea 0; "
                    "Start-Process 'C:\\wiretrace\\desktop\\app\\dist\\win-unpacked\\WhoSees.exe' -ArgumentList '--user-data-dir=C:\\wiretrace\\ud-test','--log-net-log=C:\\wiretrace\\net-test.json'; "
                    'Start-Sleep 12; Stop-Process -Name WhoSees -Force -ea 0; Start-Sleep 2; Get-Content C:\\wiretrace\\ud-test\\settings.json -ea 0; '
                    "if (Test-Path C:\\wiretrace\\net-test.json) { 'NETLOG' } ; Select-String -Path C:\\wiretrace\\net-test.json -Pattern 'url.:.https?://[^\\x22]+' -AllMatches -ea 0 | ForEach-Object { $_.Matches.Value } | Sort-Object -Unique | ForEach-Object { 'NETURL ' + $_ }; "
                    'Remove-Item -Recurse -Force C:\\wiretrace\\ud-test -ea 0"'], capture_output=True, text=True, timeout=120)
check('Windows app starts and its agent works (home city found)', '"home"' in s.stdout, s.stdout + s.stderr)
check('Windows app sends nothing on first launch (no network requests at all)', 'NETLOG' in s.stdout and 'NETURL' not in s.stdout,
      [l for l in s.stdout.splitlines() if l.startswith('NETURL') or l == 'NETLOG'] or s.stderr[-300:])
t = subprocess.run(['ssh', '-o', 'BatchMode=yes', VM, 'dir /b C:\\wiretrace\\desktop\\app\\dist\\win-unpacked\\resources\\shared\\threats'], capture_output=True, text=True, timeout=60)
check('Windows package includes threat lists', 'domains.txt' in t.stdout and 'ips.txt' in t.stdout, t.stdout + t.stderr)

# Android release APK
env2 = dict(os.environ, JAVA_HOME=os.path.expanduser('~/Android/jdk'), ANDROID_HOME=os.path.expanduser('~/Android/Sdk'))
a = subprocess.run(['./gradlew', '--no-daemon', '-q', 'assembleRelease'], cwd=os.path.join(ROOT, 'android'), env=env2, capture_output=True, text=True, timeout=1800)
apk = os.path.join(ROOT, 'android/app/build/outputs/apk/release/app-release.apk')
check('Android release APK builds', a.returncode == 0 and os.path.exists(apk), a.stdout[-300:] + a.stderr[-300:])
if os.path.exists(apk):
    z = subprocess.run(['unzip', '-l', apk], capture_output=True, text=True).stdout
    for f in ['lib/arm64-v8a/libwtengine.so', 'lib/x86_64/libwtengine.so', 'assets/shared/geo/world.wtgeo', 'assets/shared/map/world-z6.pmtiles',
              'assets/shared/threats/domains.txt', 'assets/app/renderer/index.html', 'assets/app/node_modules/maplibre-gl/dist/maplibre-gl-worker.mjs']:
        check(f'APK contains {f}', f in z, '')
    check('APK under 120 MB', os.path.getsize(apk) < 120e6, os.path.getsize(apk))
    import shutil; shutil.copy(apk, os.path.join(APP, 'dist', f"WhoSees-{json.load(open(os.path.join(APP, 'package.json')))['version']}-android.apk"))

print(f'PACKAGING {"OK" if fails == 0 else f"{fails} FAILED"}')
sys.exit(fails)
