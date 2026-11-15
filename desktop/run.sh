#!/usr/bin/env bash
# Launch the WhoSees desktop app from source (Linux).
here="$(cd "$(dirname "$0")" && pwd)"
[ -x "$here/agent/target/release/whosees-agent" ] || (cd "$here/agent" && ~/.cargo/bin/cargo build --release)
exec "$here/app/node_modules/electron/dist/electron" "$here/app" "$@"
