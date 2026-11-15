#!/usr/bin/env python3
"""Build desktop/app/renderer/notices.txt: licence texts of every third-party component shipped in WhoSees
(Rust crates in the agent and the Android engine, bundled JavaScript, fonts, data, the AndroidX library).
Identical licence texts are printed once with the list of components that use them.
Run after changing dependencies:  python3 tools/notices.py"""
import collections, glob, hashlib, json, os, re, subprocess, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
OUT = os.path.join(ROOT, 'desktop/app/renderer/notices.txt')
CARGO = os.path.expanduser('~/.cargo/bin/cargo')
LIC_FILE = re.compile(r'^(LICEN[CS]E|COPYING|NOTICE|UNLICENSE)', re.I)
OWN = {'whosees-agent', 'wtengine'}

def crate_set(project):
    """Crates linked into the shipped binary (normal dependencies, every target)."""
    out = subprocess.run([CARGO, 'tree', '-e', 'normal', '--target', 'all', '--prefix', 'none', '-f', '{p}'],
                         cwd=os.path.join(ROOT, project), capture_output=True, text=True, check=True).stdout
    return {tuple(l.split()[:2]) for l in out.splitlines() if l.strip()}

def cargo_meta(project):
    m = json.loads(subprocess.run([CARGO, 'metadata', '--format-version', '1'], cwd=os.path.join(ROOT, project),
                                  capture_output=True, text=True, check=True).stdout)
    return {(p['name'], 'v' + p['version']): p for p in m['packages']}

def texts_in(d):
    files = sorted(f for f in os.listdir(d) if LIC_FILE.match(f) and os.path.isfile(os.path.join(d, f)))
    return [open(os.path.join(d, f), errors='replace').read().strip() for f in files]

components = []  # (label, licence id, [texts])
fallback = {}
for project in ('desktop/agent', 'android/engine'):
    meta = cargo_meta(project)
    for key in sorted(crate_set(project)):
        p = meta.get(key)
        if not p or p['name'] in OWN: continue
        texts = texts_in(os.path.dirname(p['manifest_path']))
        components.append((f"{p['name']} {p['version']} (Rust)", p.get('license') or '?', texts))
        for t in texts:
            if t.startswith('Apache License') and 'Version 2.0' in t[:200]: fallback.setdefault('Apache-2.0', t)
            if 'Permission is hereby granted, free of charge' in t: fallback.setdefault('MIT', t)
components = list({c[0]: c for c in components}.values())  # crates used by both projects: once

NM = os.path.join(ROOT, 'desktop/app/node_modules')
BSD3 = """Copyright (c) {who}
Redistribution and use in source and binary forms, with or without modification, are permitted provided that the
following conditions are met:
1. Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following
   disclaimer in the documentation and/or other materials provided with the distribution.
3. Neither the name of the copyright holder nor the names of its contributors may be used to endorse or promote products
   derived from this software without specific prior written permission.
THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES,
INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE."""
for name in ('maplibre-gl', 'pmtiles', 'fflate', '@protomaps/basemaps'):
    d = os.path.join(NM, name); pj = json.load(open(os.path.join(d, 'package.json')))
    texts = texts_in(d)
    if not texts and pj.get('license') == 'BSD-3-Clause':
        texts = [BSD3.format(who=pj.get('author') or 'the ' + name + ' authors')]
    components.append((f"{name} {pj['version']} (JavaScript{', font' if 'font' in name else ''})", pj.get('license'), texts))
components.append(('Archivo (font)', 'OFL-1.1', [open(os.path.join(ROOT, 'desktop/app/renderer/fonts/LICENSE-Archivo.txt')).read().strip()]))
components.append(('IBM Plex Mono (font)', 'OFL-1.1', [open(os.path.join(ROOT, 'desktop/app/renderer/fonts/LICENSE-IBM-Plex-Mono.txt')).read().strip()]))
components.append(('Noto Sans map glyphs (font)', 'OFL-1.1', [open(os.path.join(ROOT, 'shared/map/fonts/LICENSE-Noto.txt')).read().strip()]))
components.append(('androidx.webkit 1.18.0 (Android)', 'Apache-2.0',
                   ['Copyright The Android Open Source Project\n\n' + fallback['Apache-2.0']]))

missing = [c for c in components if not c[2]]
for label, lic, texts in missing:  # no licence file shipped in the package: use the standard text of its licence
    ids = re.findall(r'[A-Za-z0-9.-]+', lic or '')
    pick = next((i for i in ids if i in fallback), None)
    if not pick: sys.exit(f'no licence text for {label} ({lic})')
    texts.append(fallback[pick])

groups = collections.OrderedDict()
for label, lic, texts in sorted(components, key=lambda c: c[0].lower()):
    body = '\n\n'.join(texts)
    groups.setdefault(hashlib.sha1(body.encode()).hexdigest(), (body, []))[1].append(f'{label} [{lic}]')

data = """DATA
- IP location: DB-IP.com IP to City Lite / ASN Lite, licensed CC BY 4.0 (https://db-ip.com, https://creativecommons.org/licenses/by/4.0/).
- Tracker and company list: AdGuard companiesdb, derived from WhoTracks.me, licensed CC BY-SA 4.0
  (https://github.com/AdguardTeam/companiesdb, https://creativecommons.org/licenses/by-sa/4.0/).
- Threat lists: Hagezi Threat Intelligence Feeds, GPL-3.0 (https://github.com/hagezi/dns-blocklists);
  abuse.ch Feodo Tracker and SSL Blacklist, CC0 (https://abuse.ch).
- Map: (c) OpenStreetMap contributors, ODbL (https://www.openstreetmap.org/copyright); Protomaps basemap (https://protomaps.com).
"""
with open(OUT, 'w') as f:
    f.write('WhoSees: open-source software and data it includes\n' + '=' * 52 + '\n\n'
            'WhoSees is free software under the GNU General Public License v3.0 or later.\n'
            'It includes the components below, each under its own licence.\n\n' + data + '\n')
    for body, labels in groups.values():
        f.write('-' * 78 + '\n' + '\n'.join(labels) + '\n\n' + body + '\n\n')
print(f'{len(components)} components, {len(groups)} distinct licence texts -> {os.path.relpath(OUT, ROOT)} '
      f'({os.path.getsize(OUT) // 1024} KB); {len(missing)} used a standard licence text')
