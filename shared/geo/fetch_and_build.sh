#!/usr/bin/env bash
# Download the current DB-IP Lite CSVs (CC BY 4.0) and build shared/geo/world.wtgeo
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
work="${1:-$here/.cache}"; mkdir -p "$work"
m="$(date +%Y-%m)"
for kind in city asn; do
  f="$work/dbip-$kind-lite-$m.csv.gz"
  [ -s "$f" ] || curl -fSL -o "$f" "https://download.db-ip.com/free/dbip-$kind-lite-$m.csv.gz"
done
python3 -I "$here/build_geo.py" "$work/dbip-city-lite-$m.csv.gz" "$work/dbip-asn-lite-$m.csv.gz" "$here/world.wtgeo"
ls -la "$here/world.wtgeo"
