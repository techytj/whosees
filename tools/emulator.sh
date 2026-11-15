#!/usr/bin/env bash
# Start the headless Android test emulator (wiretrace-test) if it isn't running, and wait for boot.
set -u
SDK=~/Android/Sdk; ADB="$SDK/platform-tools/adb -s emulator-5560"
# "stop": shut it down again (idle, it still uses several CPU cores and slows everything else)
if [ "${1:-}" = stop ]; then $ADB emu kill >/dev/null 2>&1; for i in $(seq 1 20); do $ADB get-state >/dev/null 2>&1 || break; sleep 1; done; echo "emulator stopped"; exit 0; fi
if [ "$($ADB shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" != "1" ]; then
  if ! $ADB get-state >/dev/null 2>&1; then
    ANDROID_HOME=$SDK ANDROID_AVD_HOME=$HOME/.android/avd QT_QPA_PLATFORM=offscreen setsid nohup "$SDK/emulator/emulator" \
      -avd wiretrace-test -no-window -no-audio -no-boot-anim -no-snapshot -gpu swangle_indirect -memory 4096 -port 5560 >/tmp/wt-emulator.log 2>&1 &
  fi
  for i in $(seq 1 150); do [ "$($ADB shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1" ] && break; sleep 2; done
fi
[ "$($ADB shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1" ] && echo "emulator ready" || { echo "emulator failed to boot"; exit 1; }
