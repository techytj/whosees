#!/usr/bin/env bash
# Build the Windows installer in the win11 VM and copy it back to desktop/app/dist/.
set -euo pipefail
[ -f "$(dirname "$0")/local.env" ] && . "$(dirname "$0")/local.env"  # your machines; see tools/local.env.example
: "${VM:?set VM (user@windows-vm) in tools/local.env}"
here="$(cd "$(dirname "$0")" && pwd)"
"$here/vm-build.sh"
cd "$here/../desktop"
tar -czf - --exclude=node_modules --exclude=dist app | ssh -o BatchMode=yes "$VM" "tar -xzf - -C C:/wiretrace/desktop"
tar -czf - -C "$here/.." shared/categories/domains.json shared/threats/domains.txt shared/threats/ips.txt tests/fixtures | ssh -o BatchMode=yes "$VM" "tar -xzf - -C C:/wiretrace"
ssh -o BatchMode=yes "$VM" "set PATH=C:\Program Files\nodejs;%PATH% && cd /d C:\wiretrace\desktop\app && npx electron-builder --win nsis 2>&1" | grep -E "⨯|rror|target=nsis" || true
mkdir -p "$here/../desktop/app/dist"
scp -q -o BatchMode=yes "$VM:C:/wiretrace/desktop/app/dist/WhoSees Setup *.exe" "$here/../desktop/app/dist/"
ls -la "$here/../desktop/app/dist/"*.exe
