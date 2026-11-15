#!/usr/bin/env bash
# Build the offline world map shared/map/world-z6.pmtiles (zoom 0-6) from the latest Protomaps daily build
# (OpenStreetMap data, ODbL). Downloads the pmtiles tool if it isn't installed.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"; tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
PM=$(command -v pmtiles || true)
if [ -z "$PM" ]; then
  v=1.31.2
  curl -fsSL "https://github.com/protomaps/go-pmtiles/releases/download/v$v/go-pmtiles_${v}_Linux_x86_64.tar.gz" | tar -xz -C "$tmp" pmtiles
  PM="$tmp/pmtiles"
fi
build=$(curl -fsSL https://build-metadata.protomaps.dev/builds.json | python3 -c "import json,sys; print(json.load(sys.stdin)[-1]['key'])")
echo "map build: $build"
"$PM" extract "https://build.protomaps.com/$build" "$here/world-z6.pmtiles" --maxzoom=6
ls -la "$here/world-z6.pmtiles"
