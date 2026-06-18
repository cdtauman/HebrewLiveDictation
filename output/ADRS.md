# ARCHITECTURE DECISION RECORDS — Repo 2 parity program

Format: Status · Context · Decision · Consequences · Alternatives rejected.
All ADRs are **Accepted** (owner-approved 2026-06-18).

---

## ADR-001 — Pursue full dictation-engine parity with Repo 1

**Status:** Accepted.

**Context.** The owner's goal is that a future comparison finds **no** Repo-1 advantage missing from Repo 2. Repo 1's largest real lead is its engine: multiple cloud providers (Deepgram Nova-3, Groq), offline local Whisper (`whisper.rs`), and API→local AutoFallback. Repo 2 is Google STT V2 / Chirp 3 only — so it cannot run offline or without a Google Cloud project, and "local-mode"/"fallback"/"multi-provider" are explicit comparison axes.

**Decision.** Implement full engine parity: add a provider abstraction, local Whisper (`faster-whisper`), Deepgram, Groq, and AutoFallback, all behind the existing `SpeechClient` Protocol.

**Consequences.** Larger surface area and packaging footprint; more network/error paths to test. Mitigated by: feature flags per provider, the tightened phase order (engine before UX), download-on-demand models, and per-phase rollback. The payoff is a superset product — Repo 1's engine breadth **plus** Repo 2's Windows-integration depth.

**Alternatives rejected.** (a) Keep Google-only and argue it as a deliberate product choice — fails the stated parity goal. (b) Merge the two codebases — rejected by the comparison report and by stack incompatibility (Rust/Tauri vs Python/PySide6).

---

## ADR-002 — Google STT V2 / Chirp 3 remains the default provider

**Status:** Accepted.

**Context.** Google V2/Chirp 3 streaming is Repo 2's differentiator and is already production-wired (`google_stt_v2_stream.py`, schema, UI). The owner explicitly listed it as a strength to preserve.

**Decision.** `stt.provider` defaults to `google_v2`. All other providers are opt-in behind the registry. Existing Google behavior, settings, and tests are preserved.

**Consequences.** Zero migration friction for current users; the parity work is purely additive at the default. New providers must conform to the same `SpeechClient`/event contract so switching is config-only.

**Alternatives rejected.** Defaulting to Deepgram (as Repo 1 does) — would change current behavior and discard Repo 2's differentiator for no parity benefit.

---

## ADR-003 — Use `faster-whisper` (CTranslate2) for offline local STT

**Status:** Accepted.

**Context.** Repo 1 uses `whisper-rs` (whisper.cpp FFI). Repo 2 is Python; we need an offline engine with good Hebrew support and acceptable packaging.

**Decision.** Use `faster-whisper` (CTranslate2 backend). Hebrew via `large-v3` and/or ivrit-ai turbo models. Models are **downloaded on demand** (never bundled), verified by SHA256, gated by a RAM preflight.

**Consequences.** Large native wheels (CTranslate2) increase install size; mitigated by CPU-default build and on-demand models. Higher latency than cloud (acceptable for an offline fallback). No C++ build step required (unlike whisper.cpp), which suits the Python toolchain.

**Alternatives rejected.** (a) `openai-whisper` (PyTorch) — much larger, slower, heavier deps. (b) Bind whisper.cpp directly — reintroduces a C++ build and matches Repo 1's complexity without benefit. (c) Bundle models in the installer — bloats the download and complicates rollback.

---

## ADR-004 — Deepgram and Groq as optional providers

**Status:** Accepted.

**Context.** Repo 1 ships both. Deepgram offers low-latency Hebrew streaming; Groq offers a very cheap batch path. Parity requires both be available.

**Decision.** Add `deepgram` (WebSocket streaming + REST batch) and `groq` (REST batch) providers behind the registry. API keys live in keyring (ADR per credentials). Neither changes the default.

**Consequences.** The abstraction must support a **batch/final-only** provider (Groq) and a **streaming** provider (Deepgram) under one interface — already required by `faster-whisper`, so no extra cost. Hebrew quality and latency for each are **validated by the benchmark suite** before being advertised as parity.

**Alternatives rejected.** Adding only one cloud alternative — leaves a "multi-provider" gap vs Repo 1.

---

## ADR-005 — API→local AutoFallback

**Status:** Accepted.

**Context.** Repo 1's `TranscriptionMode::AutoFallback` tries the API and falls back to local on failure — a resilience feature Repo 2 lacks (it only has Google-internal location/model fallback).

**Decision.** Add `FallbackSpeechClient(primary, local)` selected by `stt.mode = api | local | auto_fallback`. On terminal primary errors (auth/network/timeout/quota) it replays the buffered utterance to the local Whisper provider. Default stays conservative until validated.

**Consequences.** Requires a bounded audio buffer + drop policy to avoid memory growth and a clear UX signal ("switched to offline"). Local fallback only works if a local model is installed — surfaced in UI.

**Alternatives rejected.** Cloud-to-cloud fallback only (no offline) — leaves the "works without internet/Google" gap open.

---

## ADR-006 — Custom GitHub-releases updater with a SIGNED MANIFEST now; Authenticode later

**Status:** Accepted (supersedes an earlier "SHA256-only" idea).

**Context.** Repo 1 has a signed Tauri updater (minisign + GitHub `latest.json`). Repo 2 has no auto-update. A naive design that only checks a SHA256 listed in `latest.json` is **insecure** here because the manifest and the installer are hosted in the *same* GitHub release — a tampered/compromised release controls both the binary and its advertised hash.

**Decision.** Build `updater.py` that **verifies an Ed25519/minisign signature over `latest.json` using a public key embedded in the app** before trusting any field; SHA256 is retained only as a corruption check. The private key is a CI secret / kept offline. The signed manifest carries a kill-switch / minimum-version. **Authenticode** code-signing of the installer is added in Phase G when a certificate exists, and the updater then also verifies it. Manual download remains a permanent fallback.

**Consequences.** Introduces key custody as the critical security dependency (see RISK_REGISTER). CI gains a signing step. Users get tamper-evident updates without waiting for a code-signing cert.

**Alternatives rejected.** (a) SHA256-only — insecure (above). (b) WinSparkle — mature but adds a native dependency and less control over the Inno flow. (c) PyUpdater — heavier, less maintained. (d) No auto-update — leaves a real parity gap.

---

## ADR-007 — Freemium token-broker proxy is an R&D track only

**Status:** Accepted.

**Context.** Repo 1 contains a Cloudflare Worker for a freemium tier (free minutes without a user-supplied key) but **does not deploy/ship it** in v2.8.1. Building a managed proxy implies hosting cost, quota, abuse control, and billing.

**Decision.** Capture the proxy/quota design as a documented, gated future phase. Do **not** build it now. Users bring their own credentials or use offline local mode.

**Consequences.** No infra/cost burden; no parity loss vs *shipping* Repo 1 (which also doesn't ship it). If a managed free tier becomes a product priority, the design is ready to execute.

**Alternatives rejected.** Building the proxy now — disproportionate cost for a feature Repo 1 doesn't actually ship.

---

## ADR-008 — TSF/IME stays gated and is never the default

**Status:** Accepted.

**Context.** Repo 2 has a native C++ TSF PoC (`native/tsf_hello_peer/`) with a careful Named-Pipe handshake and a documented risk plan (`docs/v2_tsf_risk_plan.md`). It is a spike, not a production text service, and is gated behind `tsf.experimental_transport_enabled=false`.

**Decision.** Keep TSF/IME as a **gated R&D track**. It remains off by default and **fail-closed** (falls back to the v1 final-only path on any handshake failure). Promotion to default is allowed **only** after it passes the TSF promotion gate in `docs/qa.md` (load, IPC handshake, fallback, compatibility matrix, no duplication/focus-theft/deletion regressions).

**Consequences.** No risk to the production path from R&D work; the experimental transport cannot silently alter system input. Parity is achieved via the v1 injection stack (Word COM/UIA/SendInput/clipboard), which already exceeds Repo 1.

**Alternatives rejected.** Enabling TSF by default to chase "native composition" — premature; the PoC is not production-ready and the owner explicitly requires it stay gated.
