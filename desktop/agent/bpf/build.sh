#!/usr/bin/env bash
# Regenerate the committed eBPF object desktop/agent/src/sslcap.bpf.o.
# Needs: nightly rust + rust-src + bpf-linker (NO root). Run after editing
# bpf/sslcap-ebpf/src/main.rs or bpf/event.rs.
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.cargo/bin:$PATH"
cargo +nightly build --release -p objbuild
OBJ="$(find target -path '*/build/objbuild/*/out/sslcap' -printf '%T@ %p\n' | sort -n | tail -1 | cut -d' ' -f2-)"
[ -n "$OBJ" ] || { echo "object not found"; exit 1; }
cp "$OBJ" ../src/sslcap.bpf.o
ls -l ../src/sslcap.bpf.o
echo "wrote desktop/agent/src/sslcap.bpf.o"
