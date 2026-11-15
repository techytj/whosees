#!/usr/bin/env python3
"""Pictures for the Android install section of the website (website/android/), taken on the test emulator:
a real APK download and install in Chrome on a current Android, plus turning on Developer options.
Run with the emulator up (tools/emulator.sh):  python3 tools/android_install_shots.py
Writes website/img/guide/install/<name>.webp and adds marker positions to website/img/guide/marks.json"""
import json, os, re, subprocess, sys, time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
OUT = os.path.join(ROOT, 'website', 'img', 'guide', 'install'); os.makedirs(OUT, exist_ok=True)
TMP = os.environ.get('WT_GUIDE_TMP', '/tmp/wt-install'); os.makedirs(TMP, exist_ok=True)
ADB = [os.path.expanduser('~/Android/Sdk/platform-tools/adb'), '-s', os.environ.get('WT_EMU', 'emulator-5560')]
PAGE = os.environ.get('WT_INSTALL_PAGE', 'https://whosees.app/android/')
W, H = 1080, 2400
marks = {}


def adb(*a, timeout=60):
    return subprocess.run([*ADB, *a], capture_output=True, text=True, errors='replace', timeout=timeout).stdout


def nodes():
    xml = ''
    for _ in range(2):  # the dump fails while the screen is animating: retry, never read a stale file
        adb('shell', 'rm', '-f', '/sdcard/ui.xml')
        if 'dumped' in adb('shell', 'uiautomator', 'dump', '/sdcard/ui.xml'):
            xml = adb('shell', 'cat', '/sdcard/ui.xml'); break
        time.sleep(0.6)
    out = []
    for m in re.finditer(r'<node [^>]*>', xml):
        n = m.group(0)
        t = re.search(r' text="([^"]*)"', n); d = re.search(r'content-desc="([^"]*)"', n); b = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', n)
        if b: out.append((((t.group(1) if t else '') + ' ' + (d.group(1) if d else '')).strip(), tuple(map(int, b.groups()))))
    return out


def find(pattern, timeout=12):
    end = time.time() + timeout
    while time.time() < end:
        for label, (x1, y1, x2, y2) in nodes():
            if re.fullmatch(pattern, label, re.I): return ((x1 + x2) // 2, (y1 + y2) // 2)
        time.sleep(0.8)
    return None


def tap(pattern, timeout=12):
    p = find(pattern, timeout)
    if not p: print('not found:', pattern); return None
    adb('shell', 'input', 'tap', str(p[0]), str(p[1])); return p


def pct(p): return [round(100 * p[0] / W, 2), round(100 * p[1] / H, 2)] if p else None


def shot(name, mark=None):
    """mark: {number: pattern} buttons to circle in the picture"""
    time.sleep(1.2)
    png = os.path.join(TMP, f'{name}.png')
    open(png, 'wb').write(subprocess.run([*ADB, 'exec-out', 'screencap', '-p'], capture_output=True).stdout)
    m = {}
    for k, pat in (mark or {}).items():
        p = find(pat, 4)
        if p: m[k] = pct(p)
    marks[f'i-{name}'] = m
    subprocess.run(['magick', png, '-resize', '540x', '-quality', '84', os.path.join(OUT, f'{name}.webp')], check=True)
    print('shot', name, m, flush=True)


def main():
    pkg = 'io.github.techytj.whosees'
    adb('uninstall', pkg)
    adb('shell', 'appops', 'set', 'com.android.chrome', 'REQUEST_INSTALL_PACKAGES', 'default')
    adb('shell', 'rm -f /sdcard/Download/WhoSees-Android*.apk')
    for k in ('window_animation_scale', 'transition_animation_scale', 'animator_duration_scale'):
        adb('shell', 'settings', 'put', 'global', k, '0')
    adb('shell', 'settings', 'put', 'global', 'development_settings_enabled', '0')
    adb('shell', 'am', 'set-debug-app', '--persistent', 'com.android.chrome')
    adb('shell', "echo 'chrome --disable-fre --no-default-browser-check --no-first-run' > /data/local/tmp/chrome-command-line")
    adb('shell', 'pm', 'grant', 'com.android.chrome', 'android.permission.POST_NOTIFICATIONS')
    adb('shell', 'am', 'force-stop', 'com.android.chrome')
    adb('shell', 'input', 'keyevent', 'KEYCODE_WAKEUP')

    # 1. the download page in Chrome
    adb('shell', 'am', 'start', '-a', 'android.intent.action.VIEW', '-d', PAGE, '-p', 'com.android.chrome'); time.sleep(8)
    tap(r'No thanks', 4)  # Chrome's own notification prompt, if it appears
    shot('a-page', {'1': r'Download for Android.*'})
    tap(r'Download for Android.*'); time.sleep(2)
    if find(r'.*(harm|Download anyway|Keep anyway).*', 4):   # some Chrome versions warn about APK files
        shot('b-warning', {'1': r'Download anyway|Keep anyway|Download'})
        tap(r'Download anyway|Keep anyway', 4)
    shot('b-downloading', {})
    for _ in range(90):  # wait for the whole file
        if '81750039' in adb('shell', 'ls', '-l', '/sdcard/Download/WhoSees-Android.apk'): break
        time.sleep(1)
    time.sleep(2)
    adb('shell', 'cmd', 'statusbar', 'expand-notifications'); time.sleep(2)
    shot('c-notification', {'1': r'.*WhoSees-Android.*'})
    tap(r'.*WhoSees-Android.*', 6); time.sleep(3)
    # 3. Android: Chrome isn't allowed to install apps yet
    shot('d-blocked', {'1': r'Settings'})
    tap(r'Settings'); time.sleep(2)
    shot('e-allow', {'1': r'Allow from this source.*'})
    tap(r'Allow from this source.*'); time.sleep(2)
    # 4. the installer comes straight back once Chrome is allowed (older versions: press Back)
    if not find(r'Install', 5): adb('shell', 'input', 'keyevent', 'KEYCODE_BACK'); time.sleep(2)
    shot('g-install', {'1': r'Install'})
    tap(r'Install'); time.sleep(4)
    # Google Play Protect may step in for apps it hasn't seen before
    if find(r'.*(Play Protect|scan|Unsafe app|Install anyway|More details).*', 6):
        shot('h-protect', {'1': r'More details|Details', '2': r'Install anyway|Install without scanning|Don.t send'})
        tap(r'More details|Details', 3); time.sleep(1)
        tap(r'Install anyway|Install without scanning|Don.t send', 4); time.sleep(6)
    shot('i-done', {'1': r'Open'})
    # 5. Developer options (only needed for the unverified-developer setting, or for installing from a computer)
    adb('shell', 'am', 'start', '-a', 'android.settings.DEVICE_INFO_SETTINGS'); time.sleep(3)
    for _ in range(4): adb('shell', 'input', 'swipe', '540', '1900', '540', '500', '200'); time.sleep(0.6)
    time.sleep(1)
    bx, by = 300, 2165   # "Build number" at the bottom of About phone (this screen never idles, so no text lookup)
    shot('j-build'); marks['i-j-build'] = {'1': pct((bx, by))}
    for _ in range(7): adb('shell', 'input', 'tap', str(bx), str(by)); time.sleep(0.3)
    shot('k-developer'); marks['i-k-developer'] = {'1': pct((bx, by))}
    adb('shell', 'am', 'start', '-a', 'android.settings.APPLICATION_DEVELOPMENT_SETTINGS'); time.sleep(3)
    shot('l-devoptions', {})
    # put things back
    adb('shell', 'settings', 'put', 'global', 'development_settings_enabled', '0')
    adb('shell', 'am', 'force-stop', 'com.android.settings')
    for k in ('window_animation_scale', 'transition_animation_scale', 'animator_duration_scale'):
        adb('shell', 'settings', 'put', 'global', k, '1')
    path = os.path.join(ROOT, 'website', 'img', 'guide', 'marks.json')
    allm = json.load(open(path)) if os.path.exists(path) else {}
    allm.update(marks); json.dump(allm, open(path, 'w'), indent=1)


if __name__ == '__main__':
    main()
