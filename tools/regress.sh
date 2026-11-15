#!/usr/bin/env bash
# Full regression suite. Run after every change; nothing is committed unless it passes.
#   tools/regress.sh            everything (unit, Linux sandbox, UI, Windows VM, packaging)
#   tools/regress.sh --quick    skip packaging
set -u
root="$(cd "$(dirname "$0")/.." && pwd)"; cd "$root"
out="${WT_REGRESS_OUT:-/tmp/wt-regress-$(date +%Y%m%d-%H%M%S)}"; mkdir -p "$out"
[ -f tools/local.env ] && set -a && . tools/local.env && set +a  # your machines; see tools/local.env.example
export PATH="$HOME/.local/node/bin:$HOME/.cargo/bin:$PATH" WT_ROOT="$root"
declare -A result
run() { # name, command...
  local name=$1; shift
  echo "=== $name"; "$@" 2>&1 | tee "$out/$name.log" | grep -E "^(PASS|FAIL)|OK|FAILED|error" | grep -v "^PASS" ; local rc=${PIPESTATUS[0]}
  local pass=$(grep -c "^PASS" "$out/$name.log"); local fail=$(grep -c "^FAIL" "$out/$name.log")
  result[$name]="$([ "$rc" = 0 ] && echo PASS || echo FAIL)  ($pass passed, $fail failed)"
}
run unit        bash -c 'cd desktop/agent && cargo build --release -q && cargo test --release -q 2>&1 | sed "s/^test result: ok.*/PASS unit tests &/; s/^test result: FAILED.*/FAIL unit tests &/"; s=${PIPESTATUS[0]}; cd ../.. && node tests/report/run.mjs && exit $s'
run sandbox     unshare -rn bash tests/sandbox/net.sh
run engine      bash -c 'cd android/engine && cargo build --release -q --example linux_harness && cd ../.. && TESTPY=$PWD/tests/sandbox/engine.py unshare -rn bash tests/sandbox/net.sh'
run ui          python3 -I tests/ui/tests.py "$out/ui"
run ui-deep     env WT_OUT="$out/ui" TESTPY="$root/tests/sandbox/ui_deep.py" unshare -rn bash tests/sandbox/net.sh
run windows     python3 -I tests/windows/run.py
run android     bash -c 'tools/emulator.sh && WT_OUT="'"$out"'/android" python3 -I tests/android/run.py; rc=$?; tools/emulator.sh stop; exit $rc'
[ "${1:-}" = "--quick" ] || run packaging python3 -I tests/packaging/run.py
# hidden test screens from the UI stages: close them so nothing keeps running afterwards
pkill -f "kwin_wayland --virtual .*--socket wt-" 2>/dev/null
echo; echo "================ REGRESSION SUMMARY ($out)"
rc=0
for k in unit sandbox engine ui ui-deep windows android packaging; do
  [ -n "${result[$k]:-}" ] || continue
  printf "  %-10s %s\n" "$k" "${result[$k]}"
  [[ "${result[$k]}" == PASS* ]] || rc=1
done
exit $rc
