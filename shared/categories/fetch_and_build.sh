#!/usr/bin/env bash
# Refresh domains.json from AdGuard companiesdb (CC BY-SA 4.0).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"; tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
base=https://raw.githubusercontent.com/AdguardTeam/companiesdb/main/dist
curl -fSL -o "$tmp/trackers.json" "$base/trackers.json"
curl -fSL -o "$tmp/companies.json" "$base/companies.json"
python3 -I "$here/build_categories.py" "$tmp/trackers.json" "$tmp/companies.json" "$here/domains.json"
