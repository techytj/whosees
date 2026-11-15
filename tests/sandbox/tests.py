"""Sandbox regression tests for the Linux agent (Deep mode names, categories, blocking).
Runs inside tests/sandbox/net.sh. Prints PASS/FAIL lines; exit code = number of failures."""
import json, os, socket, ssl, subprocess, sys, threading, time

ROOT = os.environ.get('WT_ROOT') or os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
AGENT = os.path.join(ROOT, 'desktop/agent/target/release/whosees-agent')
ARGS = ['--deep', '--geo', os.path.join(ROOT, 'shared/geo/world.wtgeo'),
        '--categories', os.path.join(ROOT, 'shared/categories/domains.json'), '--interval', '100',
        '--threats', os.path.join(ROOT, 'tests/fixtures/threats')]
fails = 0

def check(name, ok, detail=''):
    global fails
    print(('PASS' if ok else 'FAIL'), name, ('' if ok else detail))
    fails += 0 if ok else 1

def resolve(n):
    return subprocess.run(['dig', '+short', '@10.99.0.2', n], capture_output=True, text=True).stdout.strip()

ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE

def tls(n, ip=None, hold=1.0):
    """Connect with SNI n, send, wait hold, send again and read the echo. True = still working."""
    ip = ip or resolve(n)
    try:
        s = ctx.wrap_socket(socket.create_connection((ip, 443), timeout=3), server_hostname=n)
        s.send(b'hi'); time.sleep(hold); s.send(b'x' * 1000); s.settimeout(2)
        ok = bool(s.recv(10)); s.close(); return ok
    except Exception:
        return False

class Agent:
    def __init__(self, extra=()):
        self.p = subprocess.Popen([AGENT, *ARGS, *extra], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.events = []
        threading.Thread(target=self._read, daemon=True).start()
        self.wait(lambda: any(e['t'] == 'hello' for e in self.events), 5)
    def _read(self):
        for l in self.p.stdout:
            try: self.events.append(json.loads(l))
            except Exception: pass
    def send(self, obj):
        self.p.stdin.write(json.dumps(obj) + '\n'); self.p.stdin.flush()
    def wait(self, cond, t):
        end = time.time() + t
        while time.time() < end:
            if cond(): return True
            time.sleep(0.05)
        return False
    def stop(self):
        try: self.p.stdin.close()
        except Exception: pass
        try: self.p.wait(5); return True
        except Exception: self.p.kill(); return False
    def opens(self):
        return [e for e in self.events if e['t'] == 'open']
    def hosts_for(self, ip):
        """host + category for connections to ip, including names that arrived later"""
        out = []
        for e in self.opens():
            if e['remote'] != ip: continue
            h, c = e.get('host'), e['category']
            for x in self.events:
                if x['t'] == 'host' and x['id'] == e['id']: h, c = x['host'], x.get('category') or c
            out.append((h, c))
        return out

def nft_table():
    return 'whosees' in subprocess.run(['nft', 'list', 'tables'], capture_output=True, text=True).stdout

# ---------- Deep mode: names + categories ----------
a = Agent()
check('agent says deep mode', any(e['t'] == 'hello' and e['mode'] == 'deep' for e in a.events))
for name, ip, want_cat in [('ads.doubleclick.net', '142.250.65.78', 'ads'), ('api.anthropic.com', '160.79.104.10', 'cloud'),
                           ('static.hotjar.com', '52.84.150.1', 'analytics')]:
    tls(name, hold=0.6)
    a.wait(lambda: any(h for h, _ in a.hosts_for(ip)), 3)
    hc = a.hosts_for(ip)
    check(f'hostname learned for {name}', any(h == name for h, _ in hc), hc)
    check(f'category {want_cat} for {name}', any(c == want_cat for h, c in hc if h == name), hc)
# SNI beats DNS name for the same address
tls('stats.g.doubleclick.net', ip='142.250.65.78', hold=0.6)
a.wait(lambda: any(h == 'stats.g.doubleclick.net' for h, _ in a.hosts_for('142.250.65.78')), 3)
check('TLS SNI name reported', any(h == 'stats.g.doubleclick.net' for h, _ in a.hosts_for('142.250.65.78')), a.hosts_for('142.250.65.78'))
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(('160.79.104.10', 443))
went = 0
for _ in range(15):
    try: s.send(b'q' * 1200); went += 1
    except OSError: pass  # nothing listens on UDP here; the kernel reports that back and drops one send
    time.sleep(0.05)
want = went * (1200 + 28)  # payload + IPv4/UDP headers
a.wait(lambda: any(e['t'] in ('update', 'close') and e.get('sent', 0) >= want for e in a.events), 3)
got = max([e.get('sent', 0) for e in a.events if e['t'] in ('update', 'close')] or [0])
check('UDP (QUIC-like) bytes counted exactly', got == want, f'got {got}, expected {want}')
s.close()
check('agent exits when UI closes its input', a.stop())

# ---------- What's being sent (data types) ----------
a = Agent()
h = socket.create_connection(('142.250.65.78', 80), timeout=2)
h.send(b'GET /collect?lat=43.6532&lng=-79.3832&gaid=38400000-8cf0-11bd-b23e-10b96e40000d&q=cheap+flights HTTP/1.1\r\nHost: tracker.test\r\nUser-Agent: TestApp/1.0 (Linux)\r\n\r\n')
time.sleep(0.8)
def seen_kinds(ip):
    ids = {e['id'] for e in a.events if e['t'] == 'open' and e['remote'] == ip}
    k = {d['kind'] for e in a.events if e['t'] == 'open' and e['id'] in ids for d in e.get('data', []) if d['basis'] == 'seen'}
    return k | {d['kind'] for e in a.events if e['t'] == 'data' and e['id'] in ids for d in e['items']}
a.wait(lambda: 'location' in seen_kinds('142.250.65.78'), 3); h.close()
sk = seen_kinds('142.250.65.78')
for k in ['location', 'advertising-id', 'search', 'device', 'browsing']:
    check(f'seen in unencrypted HTTP: {k}', k in sk, sk)
tls('ads.doubleclick.net', hold=0.5)
a.wait(lambda: any(e['t'] == 'open' and e.get('host') == 'ads.doubleclick.net' for e in a.events), 3)
lk = {d['kind'] for e in a.events if e['t'] == 'open' and e.get('host') == 'ads.doubleclick.net' for d in e.get('data', []) if d['basis'] == 'likely'}
check('likely for an ad network: advertising ID', 'advertising-id' in lk, lk)
check('encrypted traffic never claims "seen"', not any(d['basis'] == 'seen' for e in a.events if e['t'] == 'open' and e.get('host') == 'ads.doubleclick.net' for d in e.get('data', [])))
subprocess.run(['dig', '+short', '+time=1', '+tries=1', '@203.0.113.9', 'secret-clinic.example'], capture_output=True)
a.wait(lambda: 'website-names' in seen_kinds('203.0.113.9'), 3)
check('plain DNS lookup seen (website name leaks)', 'website-names' in seen_kinds('203.0.113.9'), seen_kinds('203.0.113.9'))
# v1 ships with blocking off: rules are refused and the firewall is never touched
a.send({'cmd': 'rules', 'rules': [{'kind': 'host', 'value': 'doubleclick.net'}]})
a.wait(lambda: any(e['t'] == 'rules' for e in a.events), 5)
check('blocking off by default: rules refused', any(e['t'] == 'rules' and not e['ok'] for e in a.events))
check('blocking off by default: firewall untouched', not nft_table())
check('blocking off by default: traffic flows', tls('ads.doubleclick.net'))
a.stop()

# ---------- Blocking (future feature, enabled with --blocking) ----------
a = Agent(extra=('--blocking',))
a.send({'cmd': 'rules', 'rules': [{'kind': 'host', 'value': 'doubleclick.net'}, {'kind': 'company', 'value': 'Criteo'}]})
a.wait(lambda: any(e['t'] == 'rules' for e in a.events), 5)
check('rules accepted', any(e['t'] == 'rules' and e['ok'] for e in a.events), [e for e in a.events if e['t'] == 'rules'])
# Blocked websites are looked up in the background; the system resolver can't reach anything in
# this sandbox, so a lookup done inline would stall the agent. Stats must keep coming every second.
n0 = sum(e['t'] == 'stats' for e in a.events); time.sleep(2.2)
check('agent keeps running while blocked-site lookups are pending', sum(e['t'] == 'stats' for e in a.events) - n0 >= 2, sum(e['t'] == 'stats' for e in a.events) - n0)
check('firewall table present while running', nft_table())
time.sleep(0.3)
check('blocked website refused (first try)', not tls('ads.doubleclick.net'))
check('blocked website refused (retry)', not tls('ads.doubleclick.net'))
tls('bidder.criteo.com'); time.sleep(0.3)
check('blocked company refused on retry', not tls('bidder.criteo.com'))
check('unblocked site still works', tls('api.anthropic.com'))
a.send({'cmd': 'rules', 'rules': []}); a.wait(lambda: sum(e['t'] == 'rules' for e in a.events) >= 2, 5); time.sleep(0.3)
check('unblock restores access', tls('ads.doubleclick.net'))
a.stop(); time.sleep(0.3)
check('firewall table removed after stop', not nft_table())

# ---------- Threat alerts ----------
a = Agent()
alerts = lambda: [e for e in a.events if e['t'] == 'alert']
kinds = lambda: {e['alert']['kind'] for e in alerts()}
check('threat lists loaded', any(e['t'] == 'hello' and e.get('threats') == [2, 1] for e in a.events), [e.get('threats') for e in a.events if e['t'] == 'hello'])
resolve('evil-c2.example')
a.wait(lambda: 'malicious-lookup' in kinds(), 3)
check('alert: lookup of a dangerous website', 'malicious-lookup' in kinds(), kinds())
tls('evil-c2.example', hold=0.5)
a.wait(lambda: 'malicious-website' in kinds(), 3)
check('alert: connection to a dangerous website', 'malicious-website' in kinds(), kinds())
mw = next((e for e in alerts() if e['alert']['kind'] == 'malicious-website'), None)
check('alert suggests blocking the website', mw and mw['alert']['block'] == {'kind': 'host', 'value': 'evil-c2.example', 'label': 'evil-c2.example'}, mw)
tls('bidder.criteo.com', ip='185.235.84.1', hold=0.5)
a.wait(lambda: 'malicious-server' in kinds(), 3)
ms = next((e for e in alerts() if e['alert']['kind'] == 'malicious-server'), None)
check('alert: known botnet server, with family name', ms and 'QakBot' in ms['alert']['detail'] and ms['alert']['severity'] == 'high', ms)
c = socket.create_connection(('203.0.113.9', 4444), timeout=2); c.send(b'x'); time.sleep(0.6)
a.wait(lambda: 'suspicious-port' in kinds(), 3); c.close()
check('alert: hacking-tool port 4444', 'suspicious-port' in kinds(), kinds())
tls('xjw7qkv2rtzpl9.com', hold=0.5)
a.wait(lambda: 'random-name' in kinds(), 3)
check('alert: random-looking (generated) website name', 'random-name' in kinds(), kinds())
import shutil
tool = '/tmp/wt-test-downloaded-tool'; shutil.copy('/usr/bin/python3', tool)
subprocess.run([tool, '-I', '-c', "import socket,time;s=socket.create_connection(('203.0.113.9',443));time.sleep(1)"], timeout=10)
a.wait(lambda: 'risky-location' in kinds(), 3); os.remove(tool)
check('alert: program running from a temp folder', 'risky-location' in kinds(), kinds())
s2 = ctx.wrap_socket(socket.create_connection(('203.0.113.9', 443)), server_hostname='upload.test')
for _ in range(22): s2.send(b'u' * (1024 * 1024))
time.sleep(1.2); s2.send(b'u'); time.sleep(0.8)
a.wait(lambda: 'upload' in kinds(), 4); s2.close()
check('alert: heavy one-way upload', 'upload' in kinds(), kinds())
for _ in range(6):
    tls('beacon.test', ip='203.0.113.9', hold=0.4); time.sleep(2.7)
a.wait(lambda: 'beaconing' in kinds(), 3)
check('alert: regular check-ins (beaconing)', 'beaconing' in kinds(), kinds())
before = len(alerts()); tls('api.anthropic.com', hold=0.5); time.sleep(0.5)
check('no alert for a normal site', not [e for e in alerts()[before:] if e.get('host') == 'api.anthropic.com'], alerts()[before:])
check('each alert raised once per app', len(alerts()) == len({(e['alert']['kind'], e['alert']['title'], e.get('host')) for e in alerts()}), [(e['alert']['kind'], e.get('host'), e.get('conn'), e['alert']['title']) for e in alerts()])
a.stop()

print(f'SANDBOX {"OK" if fails == 0 else f"{fails} FAILED"}')
sys.exit(fails)
