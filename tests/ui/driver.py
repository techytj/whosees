"""Run the real Electron app on a virtual KWin display, drive it with JS steps, collect CHECK lines.

Steps run in the page; each can console.log('CHECK <name> PASS|FAIL <detail>').
Uses the dev-only WT_SHOT hook in main.js (screenshots are saved next to the results)."""
import json, os, subprocess, time, urllib.parse

ROOT = os.environ.get('WT_ROOT') or os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
APP = os.path.join(ROOT, 'desktop/app')
ELECTRON = os.path.join(APP, 'node_modules/electron/dist/electron')
RUNTIME = os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')

# Helpers available to every step (prepended to each step's JS).
PRELUDE = r"""
var W = window.__wt, $ = (s) => document.querySelector(s);
var CHECK = (name, ok, detail) => console.log('CHECK ' + name + ' ' + (ok ? 'PASS' : 'FAIL') + ' ' + (ok ? '' : JSON.stringify(detail ?? '')));
var dots = () => [...W.session.places.values()].filter((p) => p.scope === 'internet').map((p) => ({ p, g: W.flows.geom(p) })).filter((x) => x.g);
var visibleDot = () => dots().find((x) => x.g.b.x > 20 && x.g.b.x < innerWidth - 20 && x.g.b.y > 140 && x.g.b.y < innerHeight - 160 && document.elementFromPoint(x.g.b.x, x.g.b.y) === W.map.getCanvas());
"""


def ensure_display(name, w, h):
    sock = os.path.join(RUNTIME, name)
    if not os.path.exists(sock):
        subprocess.Popen(['kwin_wayland', '--virtual', '--no-lockscreen', '--socket', name, '--width', str(w), '--height', str(h)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        for _ in range(60):
            if os.path.exists(sock): break
            time.sleep(0.25)
    return name


def run(out_dir, label, steps, settings, display='wt-shot', size=(1440, 900), env=None, args=(), timeout=90):
    """steps: list of (name, at_ms, js). Returns list of (check, ok, detail)."""
    ensure_display(display, *size)
    ud = os.path.join(out_dir, f'ud-{label}')
    os.makedirs(ud, exist_ok=True)
    with open(os.path.join(ud, 'settings.json'), 'w') as f: json.dump(settings, f)
    spec = ','.join(f"{n}:{at}:{urllib.parse.quote(PRELUDE + js) if js else ''}" if js else f'{n}:{at}' for n, at, js in steps)
    e = dict(os.environ, WAYLAND_DISPLAY=display, WT_SHOT=os.path.join(out_dir, label), WT_SHOT_STEPS=spec, **(env or {}))
    p = subprocess.run([ELECTRON, APP, '--ozone-platform=wayland', f'--user-data-dir={ud}', *args],
                       env=e, capture_output=True, text=True, timeout=timeout)
    results = []
    for line in (p.stdout + p.stderr).splitlines():
        if 'CHECK ' not in line: continue
        parts = line.split('CHECK ', 1)[1].split(' ', 2)
        if len(parts) >= 2: results.append((f'{label}: {parts[0]}', parts[1] == 'PASS', parts[2] if len(parts) > 2 else ''))
    return results


def page_errors(out_dir, label):
    """Uncaught errors the page logged during a run (from the app's wiretrace.log)."""
    try:
        with open(os.path.join(out_dir, f'ud-{label}', 'wiretrace.log')) as f:
            return [l.strip() for l in f if 'Uncaught' in l or 'TypeError' in l or 'ReferenceError' in l]
    except FileNotFoundError:
        return []
