"""UI regression tests on virtual displays (no sudo, nothing shown on the real screen).
Usage: python3 tests/ui/tests.py OUT_DIR      exit code = number of failures"""
import os, stat, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(__file__))
import driver

out = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp(prefix='wt-ui-')
os.makedirs(out, exist_ok=True)
HOME = {'city': 'Toronto', 'region': 'Ontario', 'country': 'CA', 'lat': 43.65, 'lon': -79.38}
results = []

def agents():
    r = subprocess.run(['pgrep', '-x', 'whosees-agent'], capture_output=True, text=True)
    return set(r.stdout.split())

# ---------- A. Standard mode, wide window ----------
before = agents()
results += driver.run(out, 'wide', [
    ('boot', 2500, """
      CHECK('map-loaded', !!W.map && W.map.loaded(), '');
      CHECK('home-set', !!$('#homeBtn').textContent.match(/Toronto/), $('#homeBtn').textContent);
      CHECK('idle-hero-visible', !$('#hero').classList.contains('gone'), '');
      CHECK('stop-hidden-when-idle', $('#stopBtn').hidden, '');
    """),
    ('live', 3500, None),
    ('running', 10500, """
      CHECK('status-live', $('#status').classList.contains('live'), $('#statusText').textContent);
      CHECK('connections-seen', W.session.conns.size > 0, W.session.conns.size);
      CHECK('apps-listed', document.querySelectorAll('#list .row[data-app]').length > 0, $('#list').innerText.slice(0, 80));
      CHECK('mode-standard', W.session.mode === 'standard', W.session.mode);
      CHECK('sent-is-session-relative', W.session.totals.sent < 5e8, W.session.totals.sent);
      var d = visibleDot();
      CHECK('a-dot-is-reachable-by-mouse', !!d, dots().length);
      if (d) {
        document.elementFromPoint(d.g.b.x, d.g.b.y).dispatchEvent(new MouseEvent('mousemove', { clientX: d.g.b.x, clientY: d.g.b.y, bubbles: true }));
        CHECK('hover-card-shows', !$('#tip').hidden && getComputedStyle($('#tip')).display !== 'none', '');
        CHECK('hover-card-has-city', $('#tip').innerText.length > 5 && !!$('.tip-city'), $('#tip').innerText);
        CHECK('hover-card-lists-app', !!$('.tip-app'), $('#tip').innerText);
      }
    """),
    ('tabs', 12500, """
      document.querySelector('[data-tab=feed]').click();
      CHECK('feed-rows', document.querySelectorAll('#list .row').length > 0, '');
      document.querySelector('[data-tab=places]').click();
      CHECK('places-rows', document.querySelectorAll('#list .row[data-place]').length > 0, '');
      CHECK('no-blocked-tab-in-v1', !document.querySelector('[data-tab=blocked]'), '');
      document.querySelector('[data-mode=expert]').click();
      document.querySelector('[data-tab=feed]').click();
      CHECK('expert-shows-addresses', !!document.querySelector('#list .mono'), '');
      document.querySelector('[data-mode=simple]').click();
      var row = document.querySelector('[data-tab=places]'); row.click();
      var pr = document.querySelector('#list .row[data-place]'); if (pr) pr.click();
      CHECK('place-detail-opens', !$('#detail').hidden && $('#detail').textContent.includes('Sent'), $('#detail').textContent.slice(0, 80));
      CHECK('no-block-buttons-in-v1', !document.querySelector('[data-block-kind]') && !document.querySelector('.blockbox'), '');
      CHECK('no-paywall-anywhere', !document.querySelector('.teaser') && !document.body.innerHTML.includes('Unlock'), '');
      document.querySelector('[data-back]')?.click();
      CHECK('back-returns-to-list', $('#detail').hidden, '');
    """),
    ('stop', 14000, """
      $('#stopBtn').click();
    """),
    ('stopped', 15500, """
      CHECK('idle-after-stop', document.body.classList.contains('idle'), '');
      CHECK('status-not-live', !$('#status').classList.contains('live'), '');
    """),
], {'theme': 'dark', 'home': HOME})
leftover = agents() - before
results.append(('wide: no-agent-left-after-stop', not leftover, leftover))
results.append(('wide: no-page-errors', not driver.page_errors(out, 'wide'), driver.page_errors(out, 'wide')))

# ---------- A2. Premium: what's being sent + privacy report ----------
results += driver.run(out, 'premium', [
    ('live', 3000, None),
    ('check', 10000, """
      var a = [...W.session.apps.values()].sort((x, y) => y.conns.size - x.conns.size)[0];
      document.querySelector('[data-tab=apps]').click();
      document.querySelector('#list .row[data-app="' + CSS.escape(a.id) + '"]').click();
      var internet = [...a.conns].some((id) => W.session.conns.get(id)?.scope === 'internet');
      CHECK('premium-privacy-report', !internet || !!document.querySelector('#detail .report .grade'), $('#detail').textContent.slice(0, 200));
      CHECK('premium-data-or-nothing-to-show', !!document.querySelector('#detail .dataset') || W.session.dataFor([...a.conns]).likely.length === 0, '');
      CHECK('premium-no-teaser', !document.querySelector('#detail .teaser'), '');
      document.querySelector('[data-back]').click();
      $('#settingsBtn').click();
      CHECK('settings-offers-support', !!document.querySelector('#dlg [data-support]') && !$('#dlg').innerText.includes('Premium'), $('#dlg').innerText.slice(0, 160));
      document.querySelector('#dlg [data-support]').click();
      var tips = [...document.querySelectorAll('#dlg .tip-amt')];
      CHECK('support-offers-5-10-15', tips.map((a) => a.dataset.amount).join() === '5,10,15', tips.map((a) => a.dataset.amount));
      CHECK('support-links-go-to-paypal-in-browser', tips.every((a) => a.href.startsWith('https://www.paypal.com/paypalme/') && a.target === '_blank'), tips.map((a) => a.href));
      $('#supClose').click();
      CHECK('support-dialog-closes', !$('#dlg').open, '');
      $('#settingsBtn').click();
      document.querySelector('[data-notices]').click();
    """),
    ('licences', 1500, """
      var t = ($('#dlg pre') || {}).textContent || '';
      CHECK('licences-list-opens', $('#dlg').open && t.includes('maplibre-gl') && t.includes('ipstack') && t.includes('DB-IP'), t.slice(0, 120));
      $('#noticesClose').click();
      CHECK('licences-close', !$('#dlg').open, '');
    """),
], {'theme': 'dark', 'home': HOME})  # no 'premium' flag: everything must show for free
results.append(('premium: no-page-errors', not driver.page_errors(out, 'premium'), driver.page_errors(out, 'premium')))

# ---------- B. Narrow window / phone size ----------
results += driver.run(out, 'narrow', [
    ('live', 3000, None),
    ('layout', 9500, """
      CHECK('bottom-sheet-layout', $('#panel').getBoundingClientRect().width >= innerWidth - 2, $('#panel').getBoundingClientRect().width);
      CHECK('stats-single-row', $('#stats').getBoundingClientRect().height < 80, $('#stats').getBoundingClientRect().height);
      CHECK('no-horizontal-page-scroll', document.documentElement.scrollWidth <= innerWidth, document.documentElement.scrollWidth);
      var d = dots().find((x) => x.g.b.x > 10 && x.g.b.x < innerWidth - 10 && x.g.b.y > 110 && x.g.b.y < innerHeight * 0.5
        && document.elementFromPoint(x.g.b.x, x.g.b.y)?.tagName === 'CANVAS');  // not under a card (e.g. a real alert)
      if (d) {
        var hit = document.elementFromPoint(d.g.b.x, d.g.b.y);
        hit.dispatchEvent(new MouseEvent('mousemove', { clientX: d.g.b.x, clientY: d.g.b.y, bubbles: true }));
        CHECK('hover-card-in-narrow-window', getComputedStyle($('#tip')).display !== 'none' && !$('#tip').hidden,
              'hit ' + hit.tagName + '#' + hit.id + '.' + hit.className + ' at ' + Math.round(d.g.b.x) + ',' + Math.round(d.g.b.y) + ' dot ' + (d.key || d.g.key || ''));
      } else CHECK('hover-card-in-narrow-window', true, 'no dot on screen; skipped');
    """),
], {'theme': 'light', 'home': HOME}, display='wt-phone', size=(390, 844))
results.append(('narrow: no-page-errors', not driver.page_errors(out, 'narrow'), driver.page_errors(out, 'narrow')))

# ---------- C. Deep mode password flow (pkexec stand-in: cancelled) ----------
fake = os.path.join(out, 'fakebin'); os.makedirs(fake, exist_ok=True)
pk = os.path.join(fake, 'pkexec')
with open(pk, 'w') as f: f.write('#!/bin/sh\necho "Error executing command as another user: Not authorized" >&2\nexit 126\n')
os.chmod(pk, os.stat(pk).st_mode | stat.S_IEXEC)
results += driver.run(out, 'deeppw', [
    ('start', 3000, "$('#startBtn').click();"),
    ('explain', 4500, """
      CHECK('explain-dialog-open', $('#dlg').open && !!$('#goDeep'), $('#dlg').innerText.slice(0, 80));
      CHECK('explain-names-password', $('#dlg').innerText.includes('log in to this computer'), $('#dlg').innerText.slice(0, 200));
      $('#goDeep').click();
    """),
    ('failed', 8000, """
      CHECK('fail-dialog-open', $('#dlg').open && !!$('#retryDeep'), $('#dlg').innerText.slice(0, 120));
      CHECK('fell-back-to-standard', W.session.mode === 'standard', W.session.mode);
      $('#keepStd').click();
      CHECK('still-running-standard', $('#status').classList.contains('live'), '');
    """),
], {'theme': 'dark', 'home': HOME, 'deep': True}, env={'PATH': fake + ':' + os.environ['PATH']})
results.append(('deeppw: no-page-errors', not driver.page_errors(out, 'deeppw'), driver.page_errors(out, 'deeppw')))

fails = 0
for name, ok, detail in results:
    print(('PASS' if ok else 'FAIL'), name, '' if ok else detail)
    fails += 0 if ok else 1
print(f'UI {"OK" if fails == 0 else f"{fails} FAILED"} ({len(results)} checks, screenshots in {out})')
sys.exit(fails)
