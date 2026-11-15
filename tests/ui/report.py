"""Report (PDF) in the real app: the button appears once a live view has data, the dialog explains it,
and a saved PDF holds what the live view found. Used by tests.py; can also run alone:
  python3 tests/ui/report.py OUT_DIR"""
import json, os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(__file__))
import driver

HOME = {'city': 'Toronto', 'region': 'Ontario', 'country': 'CA', 'lat': 43.65, 'lon': -79.38}


def run(out):
    rep = os.path.join(out, 'report.pdf')
    if os.path.exists(rep): os.remove(rep)
    netlog = os.path.join(out, 'report-net.json')
    if os.path.exists(netlog): os.remove(netlog)
    import shutil; shutil.rmtree(os.path.join(out, 'ud-report'), ignore_errors=True)  # a fresh profile, like a first launch
    results = driver.run(out, 'report', [
        ('idle', 2500, "CHECK('report-button-hidden-before-a-live-view', $('#reportBtn').hidden, '');"),
        ('live', 3000, None),
        ('running', 11000, """
          CHECK('report-button-shows-during-live-view', !$('#reportBtn').hidden && $('#reportBtn').getBoundingClientRect().width > 0, '');
          CHECK('coffee-still-next-to-settings', $('#coffeeBtn').nextElementSibling === $('#settingsBtn'), '');
          $('#reportBtn').click();
          CHECK('report-dialog-opens', $('#dlg').open && !!$('#repGo'), $('#dlg').innerText.slice(0, 100));
          CHECK('report-dialog-says-nothing-uploaded', $('#dlg').innerText.includes("isn't uploaded anywhere"), $('#dlg').innerText.slice(0, 300));
          CHECK('report-dialog-offers-style-and-paper', document.querySelectorAll('#repTheme button').length === 2 && document.querySelectorAll('#repPaper button').length === 2, '');
          $('#repCancel').click();
          CHECK('report-dialog-cancels', !$('#dlg').open, '');
          $('#stopBtn').click();
        """),
        ('stopped', 13500, """
          CHECK('stopped-card-offers-report', !$('#heroReport').hidden && $('#heroReport').getBoundingClientRect().width > 0, '');
          (async () => {
            var t0 = performance.now();
            var r = await W.saveReport({ theme: 'dark', paper: 'letter' });
            CHECK('report-saved', r.ok && r.path && r.bytes > 50000, r);
            CHECK('report-made-in-under-20-seconds', performance.now() - t0 < 20000, performance.now() - t0);
            var apps = [...W.session.apps.values()].filter((a) => [...a.conns].some((id) => W.session.conns.get(id)?.scope === 'internet')).map((a) => a.name);
            await window.wt.setSettings({ testReport: { apps, conns: W.session.conns.size, ended: !!W.session.ended } });
            CHECK('map-snapshot-left-nothing-behind', document.querySelectorAll('.maplibregl-map').length === 1, document.querySelectorAll('.maplibregl-map').length);
          })()
        """),
    ], {'theme': 'dark', 'home': HOME}, env={'WT_REPORT_OUT': rep, 'LANG': 'de_DE.UTF-8', 'LC_ALL': 'de_DE.UTF-8'},
       args=(f'--log-net-log={netlog}',), timeout=150)
    urls = sorted(set(re.findall(r'"url":"(https?://[^"]+)"', open(netlog).read() if os.path.exists(netlog) else '')))
    results.append(('report: making a report sends nothing (no network requests at all)', os.path.exists(netlog) and not urls, urls[:5]))
    results.append(('report: no-page-errors', not driver.page_errors(out, 'report'), driver.page_errors(out, 'report')))

    ok = os.path.exists(rep)
    results.append(('report: pdf-file-written', ok, rep))
    if not ok: return results
    info = subprocess.run(['pdfinfo', rep], capture_output=True, text=True).stdout
    pages = int((re.search(r'Pages:\s+(\d+)', info) or [0, 0])[1])
    results.append(('report: pdf-has-several-pages', pages >= 3, info[-300:]))
    results.append(('report: pdf-is-letter-size', '612 x 792' in info, info[-300:]))
    text = subprocess.run(['pdftotext', '-layout', rep, '-'], capture_output=True, text=True).stdout
    for s in ['What your computer sent', 'Key findings', 'Apps', 'Every connection', 'About this report', 'Nothing in this report was uploaded']:
        results.append((f'report: pdf-contains "{s}"', s in text, ''))
    results.append(('report: pdf-has-no-undefined-or-NaN', not re.search(r'undefined|NaN|\[object Object\]', text), (re.search(r'.{30}(undefined|NaN|\[object Object\]).{30}', text) or [''])[0]))
    try: tr = json.load(open(os.path.join(out, 'ud-report', 'settings.json'))).get('testReport') or {}
    except Exception: tr = {}
    results.append(('report: live view had internet apps to report', bool(tr.get('apps')), tr))
    flat = re.sub(r'\s+', ' ', text)
    missing = [a for a in tr.get('apps', []) if a[:25] not in flat]
    results.append(('report: pdf-names-every-app-that-went-online', not missing, missing))
    imgs = subprocess.run(['pdfimages', '-list', rep], capture_output=True, text=True).stdout.splitlines()[2:]
    results.append(('report: pdf-has-the-map-picture', any(' jpeg ' in l or 'image' in l for l in imgs), imgs[:3]))
    results.append(('report: pdf-is-tagged-for-screen-readers', bool(re.search(r'Tagged:\s+yes', info)), info[-300:]))
    starts = [subprocess.run(['pdftotext', '-f', str(i), '-l', str(i), rep, '-'], capture_output=True, text=True).stdout.strip().split('\n')[0].strip() for i in range(2, pages + 1)]
    results.append(('report: no app card is split across pages', not [x for x in starts if x in ('COMPANIES', 'WEBSITES', 'COUNTRIES', 'WHAT IT SENT')], starts))
    subprocess.run(['pdftoppm', '-r', '50', '-f', '1', '-l', '3', '-png', rep, os.path.join(out, 'report-page')], capture_output=True)
    return results


if __name__ == '__main__':
    import tempfile
    out = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp(prefix='wt-ui-report-')
    os.makedirs(out, exist_ok=True)
    fails = 0
    for name, ok, detail in run(out):
        print(('PASS' if ok else 'FAIL'), name, '' if ok else detail); fails += 0 if ok else 1
    print(f'REPORT UI {"OK" if not fails else f"{fails} FAILED"} ({out})')
    sys.exit(fails)
