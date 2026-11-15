"""Windows regression tests, run from Linux against the win11 VM over SSH (admin session).
Exit code = number of failures."""
import json, os, subprocess, sys

def _local(name):  # your machines live in tools/local.env (not in the repo); see tools/local.env.example
    if name in os.environ: return os.environ[name]
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'tools', 'local.env')
    for l in open(p) if os.path.exists(p) else []:
        k, _, v = l.strip().partition('=')
        if k == name: return v.strip().strip('"\'')
    sys.exit(f'set {name} in tools/local.env')
VM = _local('VM')
HERE = os.path.dirname(os.path.abspath(__file__))
fails = 0

def check(name, ok, detail=''):
    global fails
    print(('PASS' if ok else 'FAIL'), 'windows:', name, '' if ok else detail)
    fails += 0 if ok else 1

def ssh(cmd, timeout=180):
    return subprocess.run(['ssh', '-o', 'BatchMode=yes', VM, cmd], capture_output=True, text=True, timeout=timeout).stdout

def ps(script, timeout=180):
    subprocess.run(['scp', '-q', '-o', 'BatchMode=yes', os.path.join(HERE, script), f'{VM}:C:/wiretrace/{script}'], check=True)
    return ssh(f'powershell -NoProfile -ExecutionPolicy Bypass -File C:\\wiretrace\\{script}', timeout)

def events(text):
    out = []
    for l in text.splitlines():
        try: out.append(json.loads(l))
        except Exception: pass
    return out

def named(ev):
    """open events with names that arrived later folded in"""
    opens = {e['id']: dict(e) for e in ev if e['t'] == 'open' and not e.get('existing')}
    for e in ev:
        if e['t'] == 'host' and e['id'] in opens: opens[e['id']]['host'] = e['host']
        if e['t'] == 'close' and e['id'] in opens: opens[e['id']]['final_recv'] = e.get('recv', 0)
    return list(opens.values())

# build
b = subprocess.run([os.path.join(HERE, '..', '..', 'tools', 'vm-build.sh')], capture_output=True, text=True, timeout=900)
check('agent builds on Windows', 'Finished' in b.stdout and 'error' not in b.stdout, b.stdout[-400:])

# Standard mode (no admin features): socket table + DNS cache names
ssh('ipconfig /flushdns')
ev = events(ps('standard.ps1'))
hello = next((e for e in ev if e['t'] == 'hello'), {})
check('standard: reports standard mode', hello.get('mode') == 'standard', hello)
o = named(ev)
dl = [x for x in o if x['app'].get('name') == 'The curl executable']
check('standard: long downloads seen with app name', len(dl) >= 2, [(x['remote'], x['app'].get('name')) for x in o])
check('standard: website names from DNS cache', any(x.get('host') for x in dl), [(x['remote'], x.get('host')) for x in dl])
check('standard: geo + owner', all(x['geo'].get('country') for x in dl) and dl != [], '')

# Deep mode (ETW): short TCP + UDP + names + byte counts
ssh('ipconfig /flushdns')
ev = events(ps('deep.ps1'))
hello = next((e for e in ev if e['t'] == 'hello'), {})
check('deep: reports deep mode', hello.get('mode') == 'deep', hello)
o = named(ev)
wiki = [x for x in o if x.get('host') == 'www.wikipedia.org']
check('deep: short TCP connection caught with name', bool(wiki), [(x['remote'], x.get('host')) for x in o])
check('deep: short-lived app named (curl)', any(x['app'].get('name') == 'The curl executable' for x in wiki), [x['app'].get('name') for x in wiki])
check('deep: byte counts for short connection', any(x.get('final_recv', 0) > 10000 for x in wiki), [x.get('final_recv') for x in wiki])
check('deep: UDP flow caught', any(x['proto'] == 'udp' and x['remote'] == '1.1.1.1' for x in o), [(x['proto'], x['remote']) for x in o])
check('deep: multicast not reported as internet', not any(x['remote'].startswith('224.') and x['scope'] == 'internet' for x in o), '')

# Blocking
r = ps('block.ps1')
res = {l.split(' ', 1)[1].rsplit(' ', 1)[0]: l.rsplit(' ', 1)[1] for l in r.splitlines() if l.startswith('RESULT ') and (l.endswith(' WORKS') or l.endswith(' BLOCKED'))}
check('block: website blocked', res.get('powershell->wikipedia (host blocked)') == 'BLOCKED', res)
check('block: app blocked', res.get('curl->github (app blocked)') == 'BLOCKED', res)
check('block: other traffic unaffected', res.get('powershell->github (allowed)') == 'WORKS', res)
check('block: rules present while running', 'during-run WhoSees rules: 0' not in r, r[-300:])
check('block: no rules left after stop', 'after-stop WhoSees rules: 0' in r, r[-300:])

# Threat alerts (test lists only)
ssh('ipconfig /flushdns')
ev = events(ps('alerts.ps1'))
al = [e for e in ev if e['t'] == 'alert']
k = {e['alert']['kind'] for e in al}
check('alerts: dangerous website (by name)', 'malicious-website' in k or 'malicious-lookup' in k, k)
check('alerts: known malicious server (UDP)', any(e['alert']['kind'] == 'malicious-server' and 'TEST botnet' in e['alert']['detail'] for e in al), k)
risky = [e for e in al if e['alert']['kind'] == 'risky-location']
check('alerts: program in Downloads', bool(risky), k)
check('alerts: Downloads program -> block whole app', bool(risky) and risky[0]['alert']['block']['kind'] == 'app', risky[:1])

# UAC connect-back transport
subprocess.run(['scp', '-q', '-o', 'BatchMode=yes', os.path.join(HERE, 'elevate.js'), f'{VM}:C:/wiretrace/elevate.js'], check=True)
r = ssh('"C:\\Program Files\\nodejs\\node.exe" C:\\wiretrace\\elevate.js', 60)
check('elevate: token accepted', 'token ok: true' in r, r)
check('elevate: agent in deep mode', 'hello mode=deep' in r, r)
check('elevate: agent disconnects on stop', 'agent disconnected' in r, r)
left = ssh('tasklist /fi "imagename eq whosees-agent.exe"')
check('elevate: no agent left running', 'whosees-agent.exe' not in left, left)

print(f'WINDOWS {"OK" if fails == 0 else f"{fails} FAILED"}')
sys.exit(fails)
