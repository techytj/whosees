# Reading what apps actually send (Linux) — options

**Status:** exploration / decision doc. Nothing here is built yet.
**Question:** today WhoSees shows *who* data went to and *what each receiver is built to collect* ("Likely"). Can the Linux app be enhanced to read the *actual* data an app sends to a site?

---

## Start here: this reverses a promise we made on purpose

`desktop/agent/src/sniff.rs` says, in its own header: *"Payload contents are never stored or reported."* Deep mode reads only packet **headers** (SNI, DNS answers, HTTP Host, byte counts). That was a deliberate privacy line.

Reading payloads crosses it. The moment WhoSees can read request bodies, **WhoSees itself becomes the thing that sees everything** — the exact risk the app is meant to expose. That is not a reason to refuse; it is the reason the design around it has to be stricter than anything else in the app:

- **Off by default**, behind its own explicit per-session consent, separate from Deep mode's toggle.
- **In memory only.** Plaintext is never written to disk, never put in the saved PDF, never in logs.
- **The report shows *kinds*, not bodies.** We run matchers over the plaintext and report "an email address, your coarse location, a session cookie went to X" — we do not quote the raw request. Raw plaintext lives only in the live view, only while it runs.
- **On-demand only**, like the rest of the app. Ends at Stop; buffers wiped.
- **No new third party.** FOSS, local, same as everything else.

Everything below assumes these guardrails.

---

## The physics: you can only get plaintext at one of three points

HTTPS is encrypted end to end, so to read it you must be *inside* one of the ends:

1. **Before it's encrypted, inside the app** — hook the TLS library's write/read calls (eBPF uprobes), or run inside the browser (extension).
2. **With the session keys** — let the app hand you its TLS secrets (`SSLKEYLOGFILE`), then decrypt your own capture. We already capture the packets in Deep mode.
3. **By becoming one of the ends** — terminate TLS yourself with a local root CA (MITM proxy).

Four real options come out of that, plus "don't."

---

## Option comparison

| Option | Covers | Needs root? | Needs a CA? | Alters traffic? | Effort | First-party page context |
|---|---|---|---|---|---|---|
| **1. eBPF uprobes** (eCapture-style) | any app using a known TLS lib | yes (Deep already is) + CAP_BPF | no | no (read-only) | high | no |
| **2. `SSLKEYLOGFILE` + decrypt our capture** | apps **we launch** (great for browsers) | only what Deep already uses | no | no (read-only) | medium | no |
| **3. Browser extension** | that browser only | no | no | no | medium | **yes** |
| **4. MITM proxy + local CA** | apps that trust our CA | yes | **yes** | **yes (rewrites)** | high | no |
| 5. Don't — enrich inference | — | no | no | no | low | no |

---

### Option 1 — eBPF uprobes on the TLS library (the eCapture approach)

Attach eBPF uprobes to `SSL_write` / `SSL_read` (and the GnuTLS / NSS / BoringSSL / Go equivalents) and copy the plaintext buffer *before* it is encrypted / *after* it is decrypted, in the app's own process. This is exactly what [gojue/ecapture](https://github.com/gojue/ecapture) does (Apache-2.0 — we can study or port it).

- **Coverage:** OpenSSL/LibreSSL (most CLI tools, many apps), **BoringSSL** (Chrome, Chromium, Brave, Electron apps), **NSS** (Firefox), GnuTLS, and Go's own TLS. Rustls (statically linked, no stable symbols) and stripped static builds are the hard cases.
- **Privilege:** root + `CAP_BPF`/`CAP_PERFMON`, kernel ≥ 4.18 (x86_64). **Deep mode already runs as root**, so this is an increment, not a new ask.
- **Why it fits us:** no CA, read-only, doesn't touch the wire, and it sees *already-running* apps. It's the "observe, never interfere" philosophy the agent already follows.
- **Costs:** per-library, per-version **struct offsets** — the real maintenance tax. BoringSSL is statically linked into Chrome, so offsets must be detected per build (eCapture ships a `boringssl-offset` tool for exactly this). We'd ship a compiled eBPF object (libbpf/CO-RE). Biggest engineering lift of the realistic options.
- **Verdict:** the **strategic** choice — the only one that reads *every* app system-wide with no CA. Phase 2.

### Option 2 — `SSLKEYLOGFILE` + decrypt the capture we already take

Launch the target app with `SSLKEYLOGFILE` pointing at a WhoSees-owned path. The app writes its TLS session secrets there; Deep mode already captures the packets; we decrypt them with those secrets — the same mechanism Wireshark uses.

- **Coverage:** anything that honours `SSLKEYLOGFILE` **and that we start** — Chrome/Chromium/Brave/Edge, Firefox, curl/OpenSSL. You can't retrofit an already-running process, so this is naturally a **"Launch a monitored browser"** feature — which is precisely the browser use-case you care about.
- **Privilege:** nothing beyond what Deep mode already has. **No CA, no eBPF, no uprobes.** Lowest new attack surface by far.
- **Decrypts:** TLS 1.2/1.3, and QUIC/HTTP-3 on Chrome 89+ (QUIC decryption is fiddlier). Simplest path to full coverage: launch the browser with HTTP/3 disabled (`--disable-quic`) so everything falls back to TLS-over-TCP, which decrypts cleanly today; add QUIC later.
- **Costs:** Deep capture is header-only now — extend it to buffer full payloads for monitored flows; add a TLS record decryptor (port one, don't invent). Only covers apps we launch.
- **Verdict:** **best first step and best browser fit** — low risk, leans entirely on machinery we already have. Phase 1.

### Option 3 — a WhoSees browser extension

A small extension using `webRequest` (+ native messaging back to the agent) sees requests *inside* the browser, before TLS.

- **Unique value:** it's the only option that knows **page context** — "you opened nytimes.com; that one page fired 42 requests; here are the first-party ones and the third-party trackers that rode along, with their URLs." The network layer physically cannot separate the site you typed from the trackers it pulls in; the browser can. This is the truest answer to "which sites did I visit and what did they request."
- **Privilege:** none. Cross-platform.
- **Costs:** browser-only, per-browser work, needs a store listing or sideload, and Chrome's MV3 restricts request/response **body** visibility (Firefox is more capable). Doesn't see non-browser apps.
- **Verdict:** **complementary** — the right tool for per-page first-party/third-party attribution, pairs well with 1 or 2. Optional track.

### Option 4 — local MITM proxy with a WhoSees root CA

Redirect outbound 443 (via nftables — we already do nftables) to a local proxy that decrypts, logs, and re-encrypts.

- **Why not:** it means **installing a universal interception root CA** into the system and browser trust stores. A privacy tool minting a key that can impersonate every website is a direct contradiction of the product's promise, and if that key ever leaks the user is fully exposed. It also **rewrites** traffic (not read-only), **breaks certificate-pinned apps**, and QUIC/UDP slips past it unless separately intercepted.
- **Verdict:** **recommend against.** Listed only so the decision is on record.

### Option 5 — don't read payloads; sharpen inference

Keep the current model and improve it (SNI, DNS, ECH where visible, better per-service profiles). Honest, zero risk — but it does not answer "read the actual data," so it's the fallback, not the goal.

---

## Recommendation (phased)

1. **Phase 1 — `SSLKEYLOGFILE`, browser-first (Option 2).** Ship "Launch a monitored browser." Extend Deep capture to buffer payloads for those flows, decrypt TLS, run kind-matchers, report *kinds* of data per site. Low risk, no CA, reuses existing capture. Directly serves the browser report you asked for — and turns its "Likely" line into *observed* for the launched browser.
2. **Phase 2 — eBPF uprobes (Option 1).** System-wide, any app, no launch step, still no CA. The bigger build, worth it once Phase 1 proves the UX and the guardrails.
3. **Optional parallel — browser extension (Option 3)** if true per-page first-party/third-party attribution becomes a priority.
4. **Rejected — MITM/CA (Option 4).**

## How this changes the report

- Where a flow was decrypted, the "What it sent" section shows **observed** kinds (an email, a precise location, a device ID, a session cookie) instead of only **Likely**, with a clear per-row marker so the reader sees which is which.
- Everything still obeys the guardrails up top: kinds not bodies, memory not disk, nothing in the saved PDF beyond the kinds.

## Sources

- eCapture (eBPF TLS capture, library coverage, BoringSSL offset tooling): https://github.com/gojue/ecapture
- eBPF SSL/TLS inspection overview: https://oneuptime.com/blog/post/2026-01-07-ebpf-ssl-tls-inspection/view
- `SSLKEYLOGFILE` + Wireshark TLS/QUIC decryption (SharkFest, Wireshark authors): https://sharkfest.wireshark.org/retrospective/sfus/presentations24/02.pdf
- Decrypting TLS with `SSLKEYLOGFILE`: https://oneuptime.com/blog/post/2026-03-20-decrypt-tls-wireshark-sslkeylog/markdown
