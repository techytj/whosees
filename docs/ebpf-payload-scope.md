# eBPF payload reading in Deep mode — build scope

**Decision:** read the actual data apps send to sites, on Linux, with **eBPF uprobes on TLS libraries** (eCapture approach), built into **Deep mode**. Rejected the MITM/CA proxy. See [linux-payload-reading.md](linux-payload-reading.md) for the why.

**Status:** scope only. Not started.

---

## Why this fits the existing agent

Three things are already in place, which is what makes this an extension rather than a new subsystem:

1. **Deep mode already runs as root** — `desktop/app/main.js` launches the Linux agent with `pkexec … whosees-agent --deep`. eBPF needs root/`CAP_BPF`; we already have the escalation path and the user consent prompt (the pkexec dialog).
2. **The capture point already exists** — `desktop/agent/src/sniff.rs` is the privileged Deep-mode capture loop. The new uprobe capture lives beside it, gated the same way.
3. **The data pipeline already carries "what was sent"** — the agent emits `{"t":"data","id":<conn>,"items":[{kind,label,basis,detail?}]}` (see `src/datatypes.rs`, consumed in `model.js`). `basis` is already `"seen"` vs `"likely"`, and the report already has a **"Seen in readable traffic"** section. So decrypted findings flow through the pipeline that exists — **little to no UI/report change**.

The whole job is: get plaintext → match it to a connection → run matchers → emit `data` events with `basis:"seen"`. Raw bytes never leave the agent.

---

## Architecture

```
TLS lib (SSL_write/SSL_read, in the app's process)
   │  eBPF uprobe copies the plaintext buffer + (pid, fd, direction)
   ▼
eBPF ring buffer ──▶ agent (root, Deep mode)
   │  join (pid,fd) → the connection the agent already tracks (remote IP, SNI/host)
   │  run matchers over the plaintext  → DataItem{ basis:"seen", … }
   │  drop the plaintext
   ▼
emit {"t":"data","id":<conn>,"items":[…]}  →  model.js  →  report "Seen" section
```

### New module: `src/sslcap.rs` (Linux only)
- Owns the eBPF program, the ring-buffer reader, the (pid,fd)→conn join, and the matcher calls.
- Started only in Deep mode **and** only when payload reading is switched on (see guardrails). Attaches nothing otherwise.

### eBPF toolchain: **aya** (pure-Rust)
- Prefer **aya** over libbpf-rs: no `libbpf`/`clang` needed at build or runtime, which keeps the static AppImage and the rpm simple. CO-RE via the kernel's BTF (`/sys/kernel/btf/vmlinux`, present on current Fedora/Ubuntu).
- Risk to validate in M0: aya uprobe + ring-buffer maturity for our targets. Fallback is libbpf-rs + a bundled `.bpf.o` built in CI.
- Kernel floor: x86_64 ≥ 5.8 (ring buffer). Below that, payload reading is unavailable and we say so; normal Deep mode still works.

### Uprobe targets (by TLS library)
| Library | Used by | Symbols | Linking | Difficulty |
|---|---|---|---|---|
| OpenSSL / LibreSSL | curl, many apps, some Electron | `SSL_write`, `SSL_read` | dynamic `libssl.so` | easy (symbol uprobe) |
| NSS / NSPR | **Firefox** | `PR_Write`/`PR_Read` or `SSL_*` | dynamic | easy |
| BoringSSL | **Chrome/Chromium/Brave, Electron** | `SSL_write`/`SSL_read` | **static in the binary** | hard — per-binary offset detection (port eCapture's `boringssl-offset`) |
| Go crypto/tls | Go CLIs/apps | `crypto/tls.(*Conn).writeRecord` etc. | static | medium (symbol scan) |

**v1 covers OpenSSL + NSS** (Firefox, curl, OpenSSL apps) — the browser case you care about, at the easy end. BoringSSL (Chrome) and Go come after.

### The correlation problem (the real engineering risk)
`SSL_write(ssl, buf, n)` gives plaintext but not the peer. We need to tie it to a connection so the report can say *which site*:
- In the uprobe, also read the socket **fd** for that `SSL*` (via `SSL_get_fd`, or by walking the `SSL`→`BIO`→fd at a known offset), and capture `(pid, fd, direction, bytes)` with the data.
- The agent already maps **(pid, fd) → remote IP → SNI/host** (`procs.rs` + `diag.rs` + `sniff.rs`). Join on `(pid, fd)` to get the existing `conn.id`.
- Where the join fails (fd not yet mapped, UDP/QUIC), hold briefly then drop; never guess a host.

---

## Matchers — kinds, not bodies (`src/datatypes.rs`)
Extend the existing `seen(kind,label,detail)` model. Scan decrypted HTTP(S): request line + query, headers (`Cookie`, `Authorization`, `User-Agent`, `Referer`), and JSON/form bodies. Emit labels a normal person understands, with detail **masked or omitted**:
- `email` → "An email address"
- `location` → "Your precise location (GPS)"
- `phone` → "A phone number"
- `advertising-id` → "An advertising ID" (GAID/IDFA patterns)
- `auth` → "A login token or session cookie"
- `name`, `address` → only if unambiguous
- `search` → "What you typed in a search box"

All emitted as `basis:"seen"`. The report already renders these; it will now show *observed* data where a connection was read, next to *Likely* for the rest.

---

## Guardrails (hard requirements)
- **Off by default.** A separate switch from Deep mode, with its own plain-language consent ("WhoSees will read the contents your apps send, to show what's inside. It stays on your computer and is never saved.").
- **In memory only.** Plaintext is matched and dropped. Never written to disk, the report PDF, or logs.
- **Kinds, not bodies.** Only DataItem labels leave the agent; detail is masked/truncated.
- **On-demand.** Ends at Stop; buffers and uprobes torn down.
- Because the agent now reads every watched app's plaintext as root, this module is the highest-sensitivity code in the project and needs a tight review and minimal retention.

---

## UI / report changes (small)
- A consent toggle + state in the control panel and the `hello`/settings path (`main.js` args, e.g. `--read-payloads`).
- Report: mostly free (the "Seen" path exists). Add a one-line note when payload reading was on, and keep the Seen/Likely marker per row (the redesign already distinguishes them).

## Testing
- Unit tests for matchers (sample payloads → expected kinds), in the existing `unit` suite.
- A sandbox test: local `openssl s_server` + `curl` with a known body, assert the right kind is reported on the right host. Add an `sslcap` stage to `tools/regress.sh`, skipped where unprivileged / no BTF.

## Milestones
- **M0 — spike (feasibility):** aya uprobe on `libssl SSL_write`, ring buffer to userspace, print byte counts for `curl`. Confirms aya + packaging. Go/no-go on aya vs libbpf-rs.
- **M1 — browser v1:** OpenSSL + NSS (Firefox); `(pid,fd)→conn` join; matchers v1; emit `data` seen items; consent toggle; off by default; unit + sandbox tests.
- **M2 — Chrome: SCOPED OUT (2026-11-17).** Chromium/Brave/Electron statically link BoringSSL and ship *stripped* binaries — no exported `SSL_write`, no DWARF, nothing on debuginfod, and byte signatures drift per build. The capture itself is ABI-identical to OpenSSL and would work *given* the function offset; the blocker is sourcing that offset. The only tool that does it (eCapture) ships a hand-maintained per-Chrome-version offset table plus an online fetch, which breaks WhoSees's offline/FOSS/low-maintenance values. Decision: Chromium-family payload reading is **out of scope** for eBPF. If ever wanted, cover it via the `SSLKEYLOGFILE` "monitored browser" path (which is also the Windows/Android path), not eBPF.
- **M3 — reach:** QUIC/HTTP-3 (separate crypto path — not covered by `SSL_write`), Go crypto/tls, aarch64.

## Open risks
1. BoringSSL offset maintenance across Chrome versions (M2).
2. QUIC needs different hooks than `SSL_write` — HTTP/3 traffic is invisible to v1 (note it; Chrome can be launched with `--disable-quic` to force TLS for testing).
3. aya uprobe/ring-buffer maturity (validated in M0).
4. Correlation accuracy on busy processes.
5. Performance on high-throughput flows (ring-buffer pressure) — sample/cap if needed.
6. Security of handling root-read plaintext — the central non-negotiable.

## Rough effort
M0 ≈ 2–3 days. M1 ≈ 1.5–2 weeks. M2 ≈ 1 week + ongoing. M3 ≈ 1–2 weeks. v1 (M0+M1) is the meaningful first release.
