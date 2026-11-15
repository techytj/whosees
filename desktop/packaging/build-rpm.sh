#!/usr/bin/env bash
# Build dist/wiretrace-<ver>.x86_64.rpm from electron-builder's linux-unpacked dir (no fpm needed).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"; app="$here/../app"
ver=$(python3 -c "import json;print(json.load(open('$app/package.json'))['version'])")
top="$(mktemp -d)"; trap 'rm -rf "$top"' EXIT
rpmbuild -bb "$here/whosees.spec" --define "_topdir $top" --define "wt_version $ver" \
  --define "wt_src $app/dist/linux-unpacked" --define "wt_icon $app/build/icon.png" --define "wt_policy $here/io.github.techytj.whosees.policy" >/dev/null
cp "$top"/RPMS/*/*.rpm "$app/dist/"
ls -la "$app"/dist/*.rpm
