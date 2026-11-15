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
      CHECK('v1-alert-has-no-block-button', !!card && !card.querySelector('[data-alert-block]'), '');
      var got = card && card.querySelector('[data-alert-trust]');
      CHECK('alert-offers-got-it', !!got && got.textContent.includes('Got it'), card && card.innerHTML.slice(0, 200));
      if (got) got.click();
    """),
    ('afterblock', 16500, """
      CHECK('got-it-marks-alert-noted', W.session.alerts.some((a) => a.status === 'trusted'), W.session.alerts.map((a) => a.kind + ':' + a.status));
      var p = [...W.session.places.values()].find((x) => x.alerts > 0);
      CHECK('place-flagged-on-map', !!p, '');
      document.querySelector('[data-tab=alerts]').click();
      CHECK('alerts-tab-lists-them', document.querySelectorAll('#list .alert-card').length >= 1, $('#list').innerText.slice(0, 120));
      document.querySelector('[data-tab=apps]').click();
    """),
    ('check', 17500, """
      CHECK('mode-deep', W.session.mode === 'deep', W.session.mode);
      CHECK('blocking-off-in-v1', W.session.blocking === false, W.session.blocking);
      CHECK('status-says-deep', $('#statusText').textContent.includes('Deep'), $('#statusText').textContent);
      var sites = new Set(); W.session.places.forEach((p) => p.sites.forEach((_, k) => sites.add(k)));
      CHECK('website-names-shown', sites.has('Hotjar') && sites.has('Claude'), [...sites]);
      CHECK('tracking-count', +$('#sTrack').textContent >= 3, $('#sTrack').textContent);
      CHECK('no-blocked-tab', !document.querySelector('[data-tab=blocked]'), '');
      var g = [...W.session.places.values()].find((p) => p.sites.has('Google Marketing'));
      CHECK('ad-network-place-exists', !!g, '');
      if (g) {
        document.querySelector('[data-tab=places]').click();
        document.querySelector('#list .row[data-place="' + CSS.escape(g.key) + '"]').click();
        CHECK('premium-shows-seen-location', $('#detail .dchip.seen') && $('#detail').textContent.includes('Your location'), $('#detail').textContent.slice(0, 300));
        CHECK('premium-shows-likely-advertising-id', $('#detail').textContent.includes('Advertising ID'), $('#detail').textContent.slice(0, 300));
        CHECK('no-block-buttons', !document.querySelector('[data-block-kind]'), '');
      }
    """),
], {'theme': 'dark', 'home': HOME, 'deep': True, 'deepExplained': True,
    },
    env={'WT_DEEP_DIRECT': '1', 'WT_THREATS_DIR': os.path.join(driver.ROOT, 'tests/fixtures/threats')}, args=('--no-sandbox',), timeout=120)
stop.set()
results.append(('deep: no-page-errors', not driver.page_errors(out, 'deep'), driver.page_errors(out, 'deep')))
fails = 0
for name, ok, detail in results:
    print(('PASS' if ok else 'FAIL'), name, '' if ok else detail)
    fails += 0 if ok else 1
print(f'UI-DEEP {"OK" if fails == 0 else f"{fails} FAILED"} ({len(results)} checks)')
sys.exit(fails)
