"""Deep mode + blocking, end to end through the real UI, inside the sandbox network (net.sh).
Fake ad/tracker servers at real-looking addresses; the app runs its agent directly (already root here)."""
import os, socket, ssl, subprocess, sys, threading, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'ui'))
import driver

out = os.environ.get('WT_OUT') or '/tmp/wt-ui-deep'
os.makedirs(out, exist_ok=True)
HOME = {'city': 'Toronto', 'region': 'Ontario', 'country': 'CA', 'lat': 43.65, 'lon': -79.38}
NAMES = ['ads.doubleclick.net', 'www.google-analytics.com', 'connect.facebook.net', 'bidder.criteo.com',
         'static.hotjar.com', 'api.anthropic.com', 'sb.scorecardresearch.com', 'www.youtube.com', 'evil-c2.example']
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE

def traffic(stop):
    time.sleep(7)  # app boots, Start is pressed at 3s
    socks = []
    for rnd in range(2):  # twice: a lookup made while Deep mode is still starting can be missed the first time
        # a botnet control server that no rule blocks (185.235.84.1 is on the list too, but shares Criteo's blocked address)
        try: socks.append(socket.create_connection(('45.155.205.233', 443), timeout=2))
        except Exception: pass
        for n in NAMES:
            ip = subprocess.run(['dig', '+short', '@10.99.0.2', n], capture_output=True, text=True).stdout.strip()
            try: socks.append(ctx.wrap_socket(socket.create_connection((ip, 443), timeout=2), server_hostname=n))
            except Exception: pass
            time.sleep(0.15)
    try:  # plain HTTP to the ad network's address, carrying a location: should show as "seen"
        h = socket.create_connection(('142.250.65.78', 80), timeout=2)
        h.send(b'GET /px?lat=43.65&lng=-79.38 HTTP/1.1\r\nHost: ads.doubleclick.net\r\n\r\n'); socks.append(h)
    except Exception: pass
    while not stop.is_set():
        for s in list(socks):
            try: s.send(b'x' * 3000)
            except Exception: socks.remove(s)
        time.sleep(0.3)

stop = threading.Event()
threading.Thread(target=traffic, args=(stop,), daemon=True).start()
results = driver.run(out, 'deep', [
    ('live', 3000, None),
    ('alerts', 15500, """
      var cards = [...document.querySelectorAll('#alertStack .alert-card.high')];
      CHECK('alert-card-shown', cards.length > 0, $('#alertStack').innerText.slice(0, 120));
      // the screen shows at most 2 cards (newest); check the full list for the botnet alert
      CHECK('botnet-alert-names-family', W.session.alerts.some((a) => (a.detail || '').includes('QakBot')), W.session.alerts.map((a) => a.title));
      var card = cards.find((c) => c.innerText.includes('dangerous website'));
      CHECK('dangerous-website-alert-in-plain-words', !!card, $('#alertStack').innerText.slice(0, 300));
      CHECK('alert-badge-visible', !$('#alertBadge').hidden, '');
      var btn = card && card.querySelector('[data-alert-block]');
      CHECK('alert-offers-block-now', !!btn, card && card.innerHTML.slice(0, 200));
      if (btn) btn.click();
    """),
    ('afterblock', 16500, """
      CHECK('block-now-blocks-the-site', (W.session.alerts.find((a) => a.kind === 'malicious-website') || {}).status === 'blocked', W.session.alerts.map((a) => a.kind + ':' + a.status));
      var p = [...W.session.places.values()].find((x) => x.alerts > 0);
      CHECK('place-flagged-on-map', !!p, '');
      document.querySelector('[data-tab=alerts]').click();
      CHECK('alerts-tab-lists-them', document.querySelectorAll('#list .alert-card').length >= 1, $('#list').innerText.slice(0, 120));
      document.querySelector('[data-tab=apps]').click();
    """),
    ('check', 17500, """
      CHECK('mode-deep', W.session.mode === 'deep', W.session.mode);
      CHECK('blocking-available', W.session.blocking === true, W.session.blocking);
      CHECK('status-says-deep', $('#statusText').textContent.includes('Deep'), $('#statusText').textContent);
      var sites = new Set(); W.session.places.forEach((p) => p.sites.forEach((_, k) => sites.add(k)));
      CHECK('website-names-shown', sites.has('Hotjar') && sites.has('Claude'), [...sites]);
      CHECK('tracking-count', +$('#sTrack').textContent >= 3, $('#sTrack').textContent);
      var crit = [...W.session.places.values()].find((p) => [...p.owners.keys()].some((o) => /criteo/i.test(o)));
      // blocked from its very first lookup, so no connection ever opened: the place still shows, with the attempts stopped
      CHECK('criteo-place-exists', !!crit, [...W.session.places.values()].map((p) => [...p.owners.keys()].join('/')));
      CHECK('criteo-shown-blocked', !!crit && W.flows.isBlocked(crit), '');
      CHECK('criteo-attempts-stopped-by-firewall', !!crit && W.session.stoppedAt(crit) > 0, W.session.blockedHits);
      CHECK('criteo-never-connected', !!crit && [...crit.conns].every((id) => !(W.session.conns.get(id) || {}).sent), crit && [...crit.conns].map((id) => W.session.conns.get(id)));
      var anth = [...W.session.places.values()].find((p) => p.sites.has('Claude'));
      if (anth) CHECK('unblocked-place-not-marked', !W.flows.isBlocked(anth), '');
      document.querySelector('[data-tab=blocked]').click();
      CHECK('blocked-tab-lists-rules', document.querySelectorAll('#list [data-rule]').length === 3 && $('#list').innerText.includes('evil-c2.example'), $('#list').innerText.slice(0, 200));
      CHECK('blocking-on-note', $('#list').innerText.includes('Blocking is on'), $('#list').innerText.slice(0, 120));
      CHECK('alert-block-marked-kept', [...document.querySelectorAll('#list [data-rule]')].some((r) => r.innerText.includes('evil-c2.example') && r.innerText.includes('kept')), $('#list').innerText.slice(0, 300));
      var g = [...W.session.places.values()].find((p) => p.sites.has('Google Marketing'));
      CHECK('ad-network-place-exists', !!g, '');
      if (g) {
        document.querySelector('[data-tab=places]').click();
        document.querySelector('#list .row[data-place="' + CSS.escape(g.key) + '"]').click();
        CHECK('premium-shows-seen-location', $('#detail .dchip.seen') && $('#detail').textContent.includes('Your location'), $('#detail').textContent.slice(0, 300));
        // a known ad service: Google's documented list (which includes the advertising ID) replaces the generic guess
        var svc = [...document.querySelectorAll('#detail .svc')].find((x) => x.innerText.includes('Google advertising'));
        CHECK('premium-shows-known-ad-service', !!svc && /advertising ID/i.test(svc.innerText), $('#detail').innerText.slice(0, 600));
        CHECK('ad-service-offers-steps', /My Ad Center/.test(($('#detail .controls') || {}).innerText || ''), '');
        CHECK('place-offers-block-all-trackers', !!document.querySelector('#detail [data-block-kind=category]'), '');
      }
    """),
    ('stopped', 18500, """
      // a place reached only by attempts the firewall stopped: no app, no connection, no data
      var crit = [...W.session.places.values()].find((p) => [...p.owners.keys()].some((o) => /criteo/i.test(o)));
      document.querySelector('[data-tab=places]').click();
      var row = crit && document.querySelector('#list .row[data-place="' + CSS.escape(crit.key) + '"]');
      CHECK('stopped-place-listed-as-blocked', !!row && /blocked/i.test(row.innerText) && !/undefined|NaN/.test(row.innerText), row && row.innerText);
      if (row) row.click();
    """),
    ('stopped-detail', 19300, """
      var t = $('#detail').innerText;
      CHECK('stopped-place-detail-in-plain-words', t.includes('An app tried to reach Criteo') && t.includes('stopped it before it could connect'), t.slice(0, 300));
      CHECK('stopped-place-detail-clean', !/undefined|NaN|-1 other|Apps talking to it/i.test(t) && /Attempts stopped/i.test(t), t.slice(0, 500));
      CHECK('stopped-place-detail-no-empty-fields', [...document.querySelectorAll('#detail dd')].every((d) => d.innerText.trim()), [...document.querySelectorAll('#detail dt')].map((d) => d.innerText));
    """),
], {'theme': 'dark', 'home': HOME, 'deep': True, 'deepExplained': True,
    'rules': [{'kind': 'company', 'value': 'Criteo', 'label': 'Criteo', 'keep': True}, {'kind': 'host', 'value': 'scorecardresearch.com', 'label': 'scorecardresearch.com', 'keep': True}]},
    env={'WT_DEEP_DIRECT': '1', 'WT_THREATS_DIR': os.path.join(driver.ROOT, 'tests/fixtures/threats')}, args=('--no-sandbox',), timeout=120)
stop.set()
results.append(('deep: no-page-errors', not driver.page_errors(out, 'deep'), driver.page_errors(out, 'deep')))
fails = 0
for name, ok, detail in results:
    print(('PASS' if ok else 'FAIL'), name, '' if ok else detail)
    fails += 0 if ok else 1
print(f'UI-DEEP {"OK" if fails == 0 else f"{fails} FAILED"} ({len(results)} checks)')
sys.exit(fails)
