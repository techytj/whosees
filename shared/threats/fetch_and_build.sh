#!/usr/bin/env bash
# Build the offline threat lists used for alerts:
#   domains.txt  one malicious domain per line (Hagezi Threat Intelligence Feed, medium; GPL-3.0)
#   ips.txt      "ip<TAB>label<TAB>source" (abuse.ch Feodo Tracker + SSL Blacklist, CC0; Hagezi TIF IPs, GPL-3.0)
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"; tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
H=https://raw.githubusercontent.com/hagezi/dns-blocklists/main
curl -fsSL -o "$tmp/dom" "$H/wildcard/tif.medium-onlydomains.txt"
curl -fsSL -o "$tmp/hip" "$H/ips/tif.txt"
curl -fsSL -o "$tmp/feodo.json" https://feodotracker.abuse.ch/downloads/ipblocklist.json
curl -fsSL -o "$tmp/sslbl.csv" https://sslbl.abuse.ch/blacklist/sslipblacklist.csv
python3 -I - "$tmp" "$here" <<'PY'
import json, sys, ipaddress, datetime
tmp, here = sys.argv[1], sys.argv[2]
doms = sorted({l.strip().lower().lstrip('*.') for l in open(f'{tmp}/dom') if l.strip() and not l.startswith('#')})
with open(f'{here}/domains.txt', 'w') as f:
    f.write(f'# Malicious domains: Hagezi Threat Intelligence Feed (medium), GPL-3.0. Built {datetime.date.today()}\n')
    f.write('\n'.join(doms) + '\n')
ips = {}
def add(ip, label, src):
    try: ipaddress.ip_address(ip)
    except ValueError: return
    if ip not in ips or ips[ip][1] == 'hagezi': ips[ip] = (label, src)
for l in open(f'{tmp}/hip'):
    l = l.strip()
    if l and not l.startswith('#'): add(l, 'Known malicious server', 'hagezi')
for e in json.load(open(f'{tmp}/feodo.json')):
    add(e['ip_address'], f"{e.get('malware') or 'Botnet'} botnet control server", 'feodo')
for l in open(f'{tmp}/sslbl.csv'):
    if l.startswith('#') or not l.strip(): continue
    p = l.strip().split(',')
    if len(p) >= 2: add(p[1], 'Botnet control server (SSL Blacklist)', 'sslbl')
with open(f'{here}/ips.txt', 'w') as f:
    f.write(f'# Malicious addresses: abuse.ch Feodo Tracker + SSL Blacklist (CC0), Hagezi TIF IPs (GPL-3.0). Built {datetime.date.today()}\n')
    for ip, (label, src) in sorted(ips.items()): f.write(f'{ip}\t{label}\t{src}\n')
print(f'{len(doms)} domains, {len(ips)} addresses')
PY
ls -la "$here"/domains.txt "$here"/ips.txt
