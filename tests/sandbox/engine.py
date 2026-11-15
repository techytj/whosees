"""Android engine regression tests on Linux: the engine runs on a tun device exactly like Android's
VpnService fd, inside the sandbox network (net.sh). Apps' traffic -> tun -> engine -> real sockets."""
import json, os, socket, ssl, subprocess, sys, threading, time

ROOT = os.environ.get('WT_ROOT') or os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
HARNESS = os.path.join(ROOT, 'android/engine/target/release/examples/linux_harness')
fails = 0
def check(name, ok, detail=''):
    global fails
    print(('PASS' if ok else 'FAIL'), 'engine:', name, '' if ok else detail)
    fails += 0 if ok else 1

# phones report odd DNS entries too (link-local IPv6, junk): they must not break anything
cfg = {'geo': f'{ROOT}/shared/geo/world.wtgeo', 'categories': f'{ROOT}/shared/categories/domains.json',
       'threats': f'{ROOT}/tests/fixtures/threats', 'upstream_dns': ['fe80::1%wlan0', 'not-an-ip', '10.99.0.2'], 'virtual_dns': '10.66.0.53', 'bind_device': 'wta'}
p = subprocess.Popen([HARNESS, 'wt0', json.dumps(cfg)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
events = []
def reader():
    for l in p.stdout:
        try: events.append(json.loads(l))
        except Exception: pass
threading.Thread(target=reader, daemon=True).start()
def wait(cond, t=4):
    end = time.time() + t
    while time.time() < end:
        if cond(): return True
        time.sleep(0.05)
    return False
check('tun device created', wait(lambda: any(e.get('t') == 'harness' for e in events)))
# route everything through the "VPN"; the engine's own sockets stay on wta (like Android excluding our app)
for c in ['ip addr add 10.66.0.1/24 dev wt0', 'ip link set wt0 up', 'ip route del default',
          'ip route add default dev wt0 metric 10', 'ip route add default via 10.99.0.2 dev wta metric 100']:
    subprocess.run(c.split(), check=True)
check('engine says hello (vpn mode, blocking)', wait(lambda: any(e.get('t') == 'hello' and e['mode'] == 'vpn' and e['blocking'] for e in events)))

def dig(n, server='10.66.0.53'):
    return subprocess.run(['dig', '+short', '+time=2', '+tries=1', f'@{server}', n], capture_output=True, text=True).stdout.strip()
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
def tls(n, ip, hold=0.6):
    try:
        s = ctx.wrap_socket(socket.create_connection((ip, 443), timeout=3), server_hostname=n)
        s.send(b'hi'); time.sleep(hold); s.send(b'x' * 5000); s.settimeout(2); ok = bool(s.recv(10))
        # finish like a normal app: say we're done, read the rest of the reply, then close (closing with unread
        # data makes Linux reset the connection, which can cut off bytes still on their way)
        try:
            s.shutdown(socket.SHUT_WR)
            while s.recv(65536): pass
        except Exception: pass
        s.close(); return ok
    except Exception:
        return False
opens = lambda: [e for e in events if e.get('t') == 'open']

ip = dig('ads.doubleclick.net')
check('DNS through the VPN reaches the real DNS server', ip == '142.250.65.78', ip)
check('odd DNS entries (link-local, junk) do not break the config', bool(ip) and any(e.get('t') == 'hello' and e.get('geo') for e in events))
tip = subprocess.run(['dig', '+short', '+tcp', '+time=2', '+tries=1', '@10.66.0.53', 'api.anthropic.com'], capture_output=True, text=True).stdout.strip()
check('DNS over TCP through the VPN works', tip == '160.79.104.10', tip)
t0 = time.time()
try:
    socket.create_connection(('10.66.0.53', 853), timeout=3).recv(1)
except Exception: pass
check('Private DNS probe answered at once (Android falls back fast)', time.time() - t0 < 1.5, time.time() - t0)
check('connection through the VPN works', tls('ads.doubleclick.net', ip))
# An app that uploads and then closes at once (very common) must have every byte delivered.
def upload(n):
    try:
        c = socket.create_connection(('142.250.65.78', 4445), timeout=5); c.sendall(b'u' * n); c.shutdown(socket.SHUT_WR)
        got = b''
        while True:
            d = c.recv(64)
            if not d: break
            got += d
        c.close(); return int(got or b'-1')
    except Exception as e: return repr(e)
res = [upload(n) for n in (5000, 70000, 300000) * 4]
check('upload then close: every byte reaches the server', res == [5000, 70000, 300000] * 4, res)
wait(lambda: any(o['remote'] == ip for o in opens()))
o = next((o for o in opens() if o['remote'] == ip), {})
check('website name from TLS', o.get('host') == 'ads.doubleclick.net', o.get('host'))
check('category ads', o.get('category') == 'ads', o.get('category'))
check('owning app reported', o.get('app', {}).get('name') == 'Test App', o.get('app'))
check('geo looked up', o.get('geo', {}).get('country') == 'US', o.get('geo'))
wait(lambda: any(e.get('t') in ('update', 'close') and e.get('id') == o.get('id') and e.get('sent', 0) >= 5002 for e in events))
check('bytes counted', any(e.get('t') in ('update', 'close') and e.get('id') == o.get('id') and e.get('sent', 0) >= 5002 for e in events),
      [e for e in events if e.get('id') == o.get('id')])
u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); u.connect(('160.79.104.10', 443))
for _ in range(5): u.send(b'q' * 900); time.sleep(0.05)
wait(lambda: any(x['proto'] == 'udp' and x['remote'] == '160.79.104.10' for x in opens()))
check('UDP (QUIC-like) flow seen', any(x['proto'] == 'udp' and x['remote'] == '160.79.104.10' for x in opens()))
# data types through the VPN
hc = socket.create_connection(('142.250.65.78', 80), timeout=3)
hc.send(b'GET /p?latitude=51.5&longitude=-0.12&email=jane%40example.com HTTP/1.1\r\nHost: x.test\r\nUser-Agent: Phone/1\r\n\r\n'); time.sleep(0.8); hc.close()
wait(lambda: any(x['remote'] == '142.250.65.78' and x['rport'] == 80 for x in opens()))
ho = next((x for x in opens() if x['remote'] == '142.250.65.78' and x['rport'] == 80), {})
hk = {d['kind'] for d in ho.get('data', []) if d['basis'] == 'seen'}
check('data seen through the VPN: location, email, device', {'location', 'email', 'device'} <= hk, hk)
check('likely data for ad network (TLS)', any(d['kind'] == 'advertising-id' and d['basis'] == 'likely' for d in o.get('data', [])), o.get('data'))
check('app permissions passed to the UI', o.get('app', {}).get('perms') == ['location'], o.get('app'))
# threat alerts
eip = dig('evil-c2.example')
wait(lambda: any(e.get('t') == 'alert' and e['alert']['kind'] == 'malicious-lookup' for e in events))
check('alert: dangerous lookup', any(e.get('t') == 'alert' and e['alert']['kind'] == 'malicious-lookup' for e in events))
tls('evil-c2.example', eip)
wait(lambda: any(e.get('t') == 'alert' and e['alert']['kind'] == 'malicious-website' for e in events))
mw = next((e for e in events if e.get('t') == 'alert' and e['alert']['kind'] == 'malicious-website'), None)
check('alert: dangerous website, names the app', mw and 'Test App' in mw['alert']['title'], mw)
# blocking
p.stdin.write(json.dumps({'cmd': 'rules', 'rules': [{'kind': 'host', 'value': 'doubleclick.net'}]}) + '\n'); p.stdin.flush()
wait(lambda: any(e.get('t') == 'rules' for e in events))
t0 = time.time(); ok = tls('ads.doubleclick.net', ip)
check('blocked website refused', not ok)
check('blocked connection fails fast (no hang)', time.time() - t0 < 3, time.time() - t0)
check('other site still works', tls('api.anthropic.com', dig('api.anthropic.com')))
p.stdin.write(json.dumps({'cmd': 'rules', 'rules': [{'kind': 'uid', 'value': '10123'}]}) + '\n'); p.stdin.flush()
time.sleep(0.3)
check('blocking the whole app works', not tls('api.anthropic.com', '160.79.104.10'))
p.stdin.write(json.dumps({'cmd': 'rules', 'rules': []}) + '\n'); p.stdin.flush(); time.sleep(0.3)
check('unblock restores access', tls('ads.doubleclick.net', ip))
# a connection that sits idle longer than a minute must survive (streaming / push / chat apps)
idle = ctx.wrap_socket(socket.create_connection(('160.79.104.10', 443), timeout=3), server_hostname='api.anthropic.com')
idle.send(b'hi'); idle.settimeout(3); idle.recv(10)
time.sleep(75)
try: idle.send(b'still there?'); ok = bool(idle.recv(10))
except Exception: ok = False
check('idle connection survives 75 s', ok)
p.stdin.close(); p.wait(5)
print(f'ENGINE {"OK" if fails == 0 else f"{fails} FAILED"}')
sys.exit(fails)
