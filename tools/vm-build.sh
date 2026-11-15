#!/usr/bin/env bash
# Sync the agent source to the win11 VM and build it there (GNU toolchain + WinLibs dlltool).
set -euo pipefail
[ -f "$(dirname "$0")/local.env" ] && . "$(dirname "$0")/local.env"  # your machines; see tools/local.env.example
: "${VM:?set VM (user@windows-vm) in tools/local.env}"
cd "$(dirname "$0")/../desktop"
tar -czf - agent/src agent/Cargo.toml agent/Cargo.lock | ssh -o BatchMode=yes "$VM" "tar -xzf - -C C:/wiretrace/desktop"
tar -czf - -C .. tests/fixtures | ssh -o BatchMode=yes "$VM" "tar -xzf - -C C:/wiretrace"
: "${WT_MINGW:?set WT_MINGW (WinLibs mingw64\\bin folder in the VM) in tools/local.env}"; M="$WT_MINGW"
ssh -o BatchMode=yes "$VM" "set PATH=%USERPROFILE%\.cargo\bin;$M;%PATH% && cd /d C:\wiretrace\desktop\agent && cargo build --release 2>&1" | grep -E "^(warning|error)|-->|Finished" || true
