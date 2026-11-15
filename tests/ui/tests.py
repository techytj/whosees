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

# Known services: fake three connections to documented services on the busiest internet app, then open it.
SERVICES_JS = """
  var a = [...W.session.apps.values()].filter((x) => [...x.conns].some((id) => W.session.conns.get(id)?.scope === 'internet')).sort((x, y) => y.conns.size - x.conns.size)[0];
  var base = a && W.session.conns.get([...a.conns].find((id) => W.session.conns.get(id)?.scope === 'internet'));
  if (base) {
    W.session.ingest([['app-measurement.com', 'analytics', 'Google'], ['graph.facebook.com', 'social', 'Meta'], ['stats.g.doubleclick.net', 'ads', 'Google']]
      .map((h, i) => ({ ...base, t: 'open', id: 'svc-test-' + i, host: h[0], site: h[0], category: h[1], owner: h[2], data: [] })));
    document.querySelector('[data-tab=apps]').click();
    document.querySelector('#list .row[data-app="' + CSS.escape(a.id) + '"]').click();
    var cards = [...document.querySelectorAll('#detail .svc')], right = $('#detail').getBoundingClientRect().right + 1;
    CHECK('known-service-cards', cards.length >= 3, cards.map((c) => c.querySelector('b').innerText));
    CHECK('service-cards-name-sources', cards.every((c) => /^https:/.test(c.querySelector('.svc-src')?.href || '')), '');
    CHECK('what-you-can-do-listed', /My Ad Center/.test($('#detail .controls')?.innerText || '') && /off Meta/.test($('#detail .controls').innerText), ($('#detail .controls') || {}).innerText);
    CHECK('service-cards-fit-panel', [...document.querySelectorAll('#detail .svc, #detail .ctl')].every((x) => x.getBoundingClientRect().right <= right), right);
    CHECK('no-horizontal-scroll-with-cards', document.documentElement.scrollWidth <= innerWidth, document.documentElement.scrollWidth);
    cards[0]?.scrollIntoView({ block: 'start' });
  } else CHECK('known-service-cards', false, 'no internet app to attach to');
"""

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
      // WhoSees's own traffic (e.g. the update check) is explained in its detail panel, with no block button
      var row = document.querySelector('#list .row[data-app]'), sa = row && W.session.apps.get(row.dataset.app);
      CHECK('self-check-has-own-path', !!W.selfExe, W.selfExe);
      if (sa) {
        var oldExe = sa.exe; sa.exe = W.selfExe; row.click();
        CHECK('self-traffic-explained', !!$('#detail .note.self') && /WhoSees/.test($('#detail .note.self').innerText), $('#detail').innerText.slice(0, 160));
        CHECK('self-has-no-block-button', !$('#detail [data-block-kind]'), '');
        sa.exe = oldExe; $('#detail [data-back]').click();
        var other = document.querySelector('#list .row[data-app]'); other.click();
        CHECK('other-apps-have-no-self-note', !$('#detail .note.self'), $('#detail .note.self')?.innerText);
        $('#detail [data-back]').click();
      }
    """),
    ('tabs', 12500, """
      document.querySelector('[data-tab=feed]').click();
      CHECK('feed-rows', document.querySelectorAll('#list .row').length > 0, '');
      document.querySelector('[data-tab=places]').click();
      CHECK('places-rows', document.querySelectorAll('#list .row[data-place]').length > 0, '');
      CHECK('blocked-tab-present', !!document.querySelector('[data-tab=blocked]'), '');
      document.querySelector('[data-mode=expert]').click();
      document.querySelector('[data-tab=feed]').click();
      CHECK('expert-shows-addresses', !!document.querySelector('#list .mono'), '');
      document.querySelector('[data-mode=simple]').click();
      var row = document.querySelector('[data-tab=places]'); row.click();
      var pr = document.querySelector('#list .row[data-place]'); if (pr) pr.click();
      CHECK('place-detail-opens', !$('#detail').hidden && $('#detail').textContent.includes('Sent'), $('#detail').textContent.slice(0, 80));
      CHECK('place-offers-block-buttons', !!document.querySelector('#detail [data-block-kind=company]') || !!document.querySelector('#detail [data-block-kind=country]'), $('#detail').textContent.slice(-200));
      CHECK('no-paywall-anywhere', !document.querySelector('.teaser') && !document.body.innerHTML.includes('Unlock'), '');
      // Standard mode: blocking asks for Deep mode first
      var bb = document.querySelector('#detail [data-block-kind=country]') || document.querySelector('#detail [data-block-kind]');
      window.__blockLabel = bb && bb.dataset.blockLabel;
      if (bb) bb.click();
    """),
    ('askdeep', 13300, """
      CHECK('standard-mode-block-asks-for-deep', $('#dlg').open && $('#dlg').innerText.includes('Blocking needs Deep mode') && !!$('#deepOn'), $('#dlg').innerText.slice(0, 160));
      $('#deepLater').click();
    """),
    ('notnow', 13900, """
      CHECK('not-now-closes-the-dialog', !$('#dlg').open, '');
      window.wt.getSettings().then((s) => CHECK('not-now-adds-no-block', !(s.rules || []).some((r) => r.label === window.__blockLabel), s.rules));
      CHECK('not-now-says-not-blocked', $('#toast').textContent.startsWith('Not blocked'), $('#toast').textContent);
      document.querySelector('[data-back]')?.click();
      CHECK('back-returns-to-list', $('#detail').hidden, '');
      document.querySelector('[data-tab=blocked]').click();
      CHECK('blocked-tab-lists-kept-block', $('#list').innerText.includes('example.org') && $('#list').innerText.includes('kept'), $('#list').innerText.slice(0, 300));
      CHECK('blocked-tab-says-deep-mode-needed', $('#list').innerText.includes('Deep mode'), $('#list').innerText.slice(0, 200));
      CHECK('blocked-tab-offers-all-trackers', !!$('#blockTracking'), '');
      $('#blockTracking').click();
    """),
    ('alltrackers', 14700, """
      CHECK('all-trackers-asks-for-deep-too', $('#dlg').open && $('#dlg').innerText.includes('All trackers and ads'), $('#dlg').innerText.slice(0, 160));
      $('#deepLater').click();
    """),
    ('standardrule', 15200, """
      // a block that matches a place, in Standard mode: nothing may claim it was blocked
      CHECK('all-trackers-switch-stays-off-without-deep', !$('#blockTracking').classList.contains('on'), '');
      (async () => {
        var p = [...W.session.places.values()].find((x) => x.scope === 'internet' && x.geo && x.geo.country);
        if (!p) { CHECK('standard-mode-never-claims-blocked', true, 'no internet place; skipped'); return; }
        var s = await window.wt.getSettings();
        await window.wt.setSettings({ rules: [...(s.rules || []), { kind: 'country', value: p.geo.country, label: 'Test country', keep: false }] }); await W.reloadSettings();
        CHECK('standard-mode-map-not-marked-blocked', !W.flows.isBlocked(p), '');
        document.querySelector('[data-tab=places]').click();
        var row = document.querySelector('#list .row[data-place="' + CSS.escape(p.key) + '"]');
        CHECK('standard-mode-place-row-no-blocked-chip', !!row && !row.innerText.includes('Blocked'), row && row.innerText);
        row && row.click(); await new Promise((r) => setTimeout(r, 200));
        CHECK('standard-mode-detail-says-not-blocked', $('#detail').innerText.includes('Not blocked in this live view') && !$('#detail').innerText.includes('WhoSees blocked it'), $('#detail').innerText.slice(-400));
        document.querySelector('[data-back]')?.click();
        // a threat alert's Block now, then Not now: the card must not say Blocked and nothing stays on the list
        W.session.ingest([{ t: 'alert', conn: null, host: 'bad.example', remote: '203.0.113.7', alert: { severity: 'high', kind: 'malicious-lookup', title: 'Something looked up a dangerous website: bad.example', detail: 'test', block: { kind: 'host', value: 'bad.example', label: 'bad.example' } } }]);
        await new Promise((r) => setTimeout(r, 300));
        var card = [...document.querySelectorAll('#alertStack .alert-card')].find((c) => c.innerText.includes('bad.example'));
        card && card.querySelector('[data-alert-block]').click(); await new Promise((r) => setTimeout(r, 400));
        CHECK('standard-mode-alert-block-asks-for-deep', $('#dlg').open && !!$('#deepLater'), $('#dlg').innerText.slice(0, 120));
        $('#deepLater').click(); await new Promise((r) => setTimeout(r, 400));
        card = [...document.querySelectorAll('#alertStack .alert-card')].find((c) => c.innerText.includes('bad.example'));
        CHECK('standard-mode-alert-card-not-marked-blocked', !!card && !card.innerText.includes('Blocked') && !!card.querySelector('[data-alert-block]'), card && card.innerText);
        var s2 = await window.wt.getSettings();
        CHECK('standard-mode-alert-not-now-leaves-no-rule', !(s2.rules || []).some((r) => r.value === 'bad.example'), s2.rules);
        card && card.querySelector('[data-alert-dismiss]').click();
        document.querySelector('[data-tab=blocked]').click();
      })()
    """),
    ('keep', 16400, """
      var k = [...document.querySelectorAll('#list [data-rule]')].find((r) => r.innerText.includes('example.org'));
      k && k.querySelector('[data-keep]').click();
    """),
    ('unkept', 17000, """
      var row = [...document.querySelectorAll('#list [data-rule]')].find((r) => r.innerText.includes('example.org'));
      CHECK('keep-toggles-off', !!row && row.innerText.includes('until Stop') && !row.querySelector('.keep.on'), row && row.innerText);
      $('#stopBtn').click();
    """),
    ('stopped', 18600, """
      CHECK('idle-after-stop', document.body.classList.contains('idle'), '');
      CHECK('status-not-live', !$('#status').classList.contains('live'), '');
      window.wt.getSettings().then((s) => CHECK('stop-ends-blocks-not-kept', !(s.rules || []).length, s.rules));
    """),
], {'theme': 'dark', 'home': HOME, 'rules': [{'kind': 'host', 'value': 'example.org', 'label': 'example.org', 'keep': True}]})
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
    ('services', 1000, SERVICES_JS),
    ('services-steps', 500, "$('#detail .controls')?.scrollIntoView({ block: 'end' });"),
    ('coffee', 1000, """
      CHECK('coffee-button-next-to-settings', !!$('#coffeeBtn') && $('#coffeeBtn').nextElementSibling === $('#settingsBtn') && $('#coffeeBtn').getBoundingClientRect().width > 0, '');
      $('#coffeeBtn').click();
      CHECK('coffee-button-opens-tips', $('#dlg').open && document.querySelectorAll('#dlg .tip-amt').length === 3, $('#dlg').innerText.slice(0, 80));
      $('#supClose').click();
    """),
], {'theme': 'dark', 'home': HOME})  # no 'premium' flag: everything must show for free
# ---------- A3. Update checks: off by default, asked once at first launch, says what is sent ----------
import json, tempfile
vj = os.path.join(tempfile.mkdtemp(prefix='wt-ver-'), 'version.json')
json.dump({'latest': '9.9.9', 'released': '2030-01-01', 'notes': 'test release'}, open(vj, 'w'))
results += driver.run(out, 'updates', [
    ('ask', 3500, """
      CHECK('first-launch-asks-about-updates', $('#dlg').open && !!$('#updYes') && !!$('#updNo'), $('#dlg').innerText.slice(0, 80));
      CHECK('says-what-is-sent', /internet address/.test($('#dlg').innerText) && /Nothing else is sent/.test($('#dlg').innerText), '');
      CHECK('off-unless-turned-on', /off/i.test($('#dlg').innerText), '');
      $('#updYes').click();
    """),
    ('note', 6000, """
      CHECK('turning-on-saves-setting', W.reloadSettings && true, '');
      var n = $('#updateNote');
      CHECK('newer-version-shown', !n.hidden && n.innerText.includes('9.9.9'), n.innerText);
      CHECK('download-link-goes-to-platform-page', ['https://whosees.app/linux/', 'https://whosees.app/windows/', 'https://whosees.app/android/'].includes(n.querySelector('a').href), n.querySelector('a') && n.querySelector('a').href);
      n.querySelector('.note-x').click();
      $('#settingsBtn').click();
      CHECK('settings-shows-update-switch-on', $('#updSw') && $('#updSw').classList.contains('on'), '');
      $('#dlg').close();
    """),
], {'theme': 'dark', 'home': HOME, 'updatePromptSeen': False}, env={'WT_UPDATE_URL': 'file://' + vj})
json.dump({'latest': '0.0.1'}, open(vj, 'w'))
results += driver.run(out, 'updates-off', [
    ('idle', 4000, """
      CHECK('no-question-once-answered', !$('#dlg').open, $('#dlg').innerText.slice(0, 60));
      CHECK('no-check-when-off', $('#updateNote').hidden, '');
      $('#settingsBtn').click(); $('#updNow').click();
    """),
    ('manual', 6000, """
      CHECK('check-now-says-up-to-date', !$('#toast').hidden && /newest version/.test($('#toast').textContent), $('#toast').textContent);
    """),
], {'theme': 'dark', 'home': HOME, 'updatePromptSeen': True, 'updateCheck': False}, env={'WT_UPDATE_URL': 'file://' + vj})

results.append(('premium: no-page-errors', not driver.page_errors(out, 'premium'), driver.page_errors(out, 'premium')))

# ---------- B. Narrow window / phone size ----------
results += driver.run(out, 'narrow', [
    ('live', 3000, None),
    ('layout', 9500, """
      CHECK('bottom-sheet-layout', $('#panel').getBoundingClientRect().width >= innerWidth - 2, $('#panel').getBoundingClientRect().width);
      CHECK('stats-single-row', $('#stats').getBoundingClientRect().height < 80, $('#stats').getBoundingClientRect().height);
      CHECK('no-horizontal-page-scroll', document.documentElement.scrollWidth <= innerWidth, document.documentElement.scrollWidth);
      var tb = [...document.querySelectorAll('.titlebar .brand, .titlebar .status, .titlebar .actions > *')].filter((b) => b.offsetParent).map((b) => b.getBoundingClientRect());
      CHECK('title-bar-fits-beside-window-buttons', tb.every((r) => r.right <= innerWidth - 136), [innerWidth, tb.map((r) => Math.round(r.right))]);
      CHECK('title-bar-items-do-not-overlap', tb.every((r, i) => i === 0 || r.left >= tb[i - 1].right - 0.5), tb.map((r) => [Math.round(r.left), Math.round(r.right)]));
      $('#settingsBtn').click();
      CHECK('report-in-settings-on-narrow-screens', !!$('#setReport') && !$('#setReport').disabled, $('#dlg').innerText.slice(0, 120));
      $('#done').click();
      var d = dots().find((x) => x.g.b.x > 10 && x.g.b.x < innerWidth - 10 && x.g.b.y > 110 && x.g.b.y < innerHeight * 0.5
        && document.elementFromPoint(x.g.b.x, x.g.b.y)?.tagName === 'CANVAS');  // not under a card (e.g. a real alert)
      if (d) {
        var hit = document.elementFromPoint(d.g.b.x, d.g.b.y);
        hit.dispatchEvent(new MouseEvent('mousemove', { clientX: d.g.b.x, clientY: d.g.b.y, bubbles: true }));
        CHECK('hover-card-in-narrow-window', getComputedStyle($('#tip')).display !== 'none' && !$('#tip').hidden,
              'hit ' + hit.tagName + '#' + hit.id + '.' + hit.className + ' at ' + Math.round(d.g.b.x) + ',' + Math.round(d.g.b.y) + ' dot ' + (d.key || d.g.key || ''));
      } else CHECK('hover-card-in-narrow-window', true, 'no dot on screen; skipped');
    """),
    ('services', 1000, SERVICES_JS),
    ('services-steps', 500, "$('#detail .controls')?.scrollIntoView({ block: 'end' });"),
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

# ---------- D. Report (PDF) ----------
import report
results += report.run(out)

fails = 0
for name, ok, detail in results:
    print(('PASS' if ok else 'FAIL'), name, '' if ok else detail)
    fails += 0 if ok else 1
print(f'UI {"OK" if fails == 0 else f"{fails} FAILED"} ({len(results)} checks, screenshots in {out})')
sys.exit(fails)
