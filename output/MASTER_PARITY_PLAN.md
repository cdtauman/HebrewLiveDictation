# MASTER PARITY PLAN
## Upgrading `cdtauman/HebrewLiveDictation` (Repo 2) to full parity with `aihenryai/hebrew-dictation` (Repo 1)

**Document status:** Approved plan, ready for execution
**Author role:** Principal Systems Architect / QA Director / Product Engineering Planner
**Date:** 2026-06-18
**Companion documents:** `FEATURE_PARITY_MATRIX.md`, `ARCHITECTURE_UPGRADE_PLAN.md`, `ADRS.md`, `EPICS_AND_ISSUES.md`, `QA_ACCEPTANCE_MATRIX.md`, `RISK_REGISTER.md`, `PLAN_AUDIT.md`, `CODEX_HANDOFF_PROMPT.md`, `ANTIGRAVITY_REVIEW_PROMPT.md`, `CLAUDE_EXECUTION_PROMPTS.md`, `FINAL_EXECUTIVE_SUMMARY.md`

---

## 0. Executive intent

The goal is **not** to decide which repository is better today. The goal is to define an exhaustive, evidence-backed program of work so that, after execution, **a future comparison between Repo 1 and Repo 2 finds no meaningful advantage that exists in Repo 1 but is missing from Repo 2** — across product, architecture, UX, packaging, testing, security, dictation-engine, local-mode, fallback, and Windows-integration — **while preserving every unique strength of Repo 2.**

Success is measured concretely in §9 ("Definition of Done").

---

## 1. The two systems (verified against code, not the report)

| | **Repo 1 — parity source** | **Repo 2 — target to upgrade** |
|---|---|---|
| GitHub | `aihenryai/hebrew-dictation` | `cdtauman/HebrewLiveDictation` |
| Local path | `../hebrew-dictation-main` | current dir `HebrewLiveDictation` |
| Version | v2.8.1 | v1.0.0-beta |
| Stack | Tauri v2 / Rust / React 19 / TypeScript / Vite | Python 3.12 / PySide6 |
| Engine | Deepgram Nova-3, Groq Whisper Turbo, **local whisper-rs**, **AutoFallback** | **Google STT V2 / Chirp 3 only** |
| Credentials | OS keyring (Windows Credential Manager) | Google SA-JSON path in plaintext `settings.json` / ADC |
| Updater | **Signed auto-updater** (minisign + GitHub `latest.json`) | None (Inno Setup installer only) |
| Windows integration | Basic text injection (`enigo`) | **Word COM, UIA, Unicode SendInput, clipboard, target tracking** |
| CI/CD | **None** (manual release) | **GitHub Actions** w/ gated test job + `release_audit.py` |
| Editing | History + DOCX/TXT export | **Session editing** (delete/undo/replace/send), **command packs** he/en/ar/ru/fr/es |
| Experimental | Cloudflare freemium worker (not deployed) | TSF/IME C++ PoC (gated off) |

**Critical doctrine:** the two repos are **different stacks**. The comparison report and the code both make clear that the correct strategy is **not to merge or port code**, but to **re-implement each Repo-1 advantage as a native Python/PySide6 equivalent** inside Repo 2.

### Evidence (files inspected)
- Repo 2 engine seam: [stt_factory.py](../src/hebrew_live_dictation/stt_factory.py) (Google hardcoded), [interfaces.py](../src/hebrew_live_dictation/interfaces.py) (`SpeechClient` Protocol — the abstraction seam already exists).
- Repo 2 engine: [google_stt_v2_stream.py](../src/hebrew_live_dictation/google_stt_v2_stream.py).
- Repo 2 injection/Windows: [text_injector.py](../src/hebrew_live_dictation/text_injector.py), [editing_backend.py](../src/hebrew_live_dictation/editing_backend.py).
- Repo 2 editing/commands: [language_packs.py](../src/hebrew_live_dictation/language_packs.py), [dictation_controller.py](../src/hebrew_live_dictation/dictation_controller.py).
- Repo 2 config/credentials: [config.py](../src/hebrew_live_dictation/config.py), [settings.example.json](../settings.example.json).
- Repo 2 packaging/CI/QA: [HebrewLiveDictation.spec](../HebrewLiveDictation.spec), [build_app.ps1](../build_app.ps1), [setup_script.iss](../setup_script.iss), [app.manifest](../app.manifest), `.github/workflows/build-release.yml`, [scripts/release_audit.py](../scripts/release_audit.py), `docs/architecture.md`, `docs/qa.md`, `docs/v2_tsf_risk_plan.md`.
- Repo 1: `src-tauri/tauri.conf.json` (updater + NSIS), `src-tauri/Cargo.toml`, `src-tauri/src/{lib.rs,whisper.rs,model.rs,api_transcribe.rs,streaming.rs,secure_keys.rs,settings.rs,export.rs}`, `benchmark/`, `cloudflare-worker/`.
- The comparison report `.docx` (read in full).

### Corrections to the comparison report (code wins)
1. **No large binary is committed.** The report/early analysis implied a committed zip. Verified: `.gitignore` line 71 ignores `*.zip`; `git ls-files` shows **no** tracked zip/exe; tree is clean. This "repo hygiene" gap is **dropped**.
2. **Repo 2 leads on CI/CD.** Repo 2 has a working CI pipeline with a gated test job and a release-audit secret/artifact gate; **Repo 1 has no CI at all**. The report under-credited this.
3. **Neither app is code-signed.** SmartScreen friction is a *shared* gap, relevant to the updater/installer trust track — not a Repo-1 advantage.

---

## 2. Locked scope decisions (owner-approved)

1. **Full engine parity.** Add offline local Whisper (`faster-whisper`) + Deepgram + Groq + API→local AutoFallback, behind the existing `SpeechClient` abstraction. **Google STT V2 / Chirp 3 remains the default provider.**
2. **Freemium token-broker (Cloudflare-style) = R&D track only.** Design documented; not built (no hosting/cost/abuse-control burden now).
3. **Auto-update = custom GitHub-releases updater with a SIGNED manifest.** The in-app checker verifies an Ed25519/minisign signature over `latest.json` (public key embedded in the app) **before** trusting it; SHA256 is a corruption check only; Authenticode is added later when a certificate exists.

---

## 3. Parity gap summary

See `FEATURE_PARITY_MATRIX.md` for the exhaustive row-by-row table with evidence. The must-have parity gaps (exist in Repo 1, missing/weaker in Repo 2):

| # | Capability | Repo 2 today | Target (Python equivalent) | Pri |
|---|---|---|---|---|
| 1 | Multi-provider abstraction | Google hardcoded; `SpeechClient` Protocol exists | `stt/` package + `ProviderRegistry`; config dispatch | P0 |
| 2 | Offline local STT | none | `faster-whisper` provider | P1 |
| 3 | API→local AutoFallback | none (Google-internal only) | `FallbackSpeechClient` wrapper | P1 |
| 4 | OS keyring credentials | plaintext JSON / ADC | `keyring` + non-destructive migration | P0 |
| 5 | Signed auto-updater | none | GitHub `latest.json` + signed manifest | P1 |
| 6 | Floating toolbar + idle button | overlay only | PySide6 frameless draggable widgets | P2 |
| 7 | History + TXT/DOCX export | session-only | history store + `python-docx` | P2 |
| 8 | Audio-feedback tones + volume | none (confirm) | `QSoundEffect` | P3 |
| 9 | Pause/resume mid-recording | toggle only | pause/resume state + hotkey | P2 |
| 10 | Local model management UI | none | `models.py` + download/RAM/SHA256 + UI | P2 |
| 11 | Onboarding provider selection + key test | Google-centric | provider cards + test buttons | P2 |
| 12 | Benchmark/WER suite | none | Python WER harness | P3 |

**Nice-to-have beyond Repo 1 (production maturity, where Repo 1 also lacks it):** `SECURITY.md`, `CHANGELOG.md`, dependency pinning + lockfile, SCA in CI (bandit/safety/Dependabot), **code signing**, release checksums/signatures, automated GUI smoke tests, coverage reporting, pre-commit hooks.

**R&D track (gated, not default):** TSF/IME promotion; freemium proxy design doc.

---

## 4. Strengths of Repo 2 that MUST be preserved (do not regress)

Per the owner's explicit instruction, these are competitive advantages of Repo 2 and must survive the upgrade intact:

- **Google STT V2 / Chirp 3 streaming path** (remains the default engine).
- **Command packs** (multi-language: he/en/ar/ru/fr/es) — [language_packs.py](../src/hebrew_live_dictation/language_packs.py).
- **Session editing** — delete last word/sentence, undo (20-deep), clear, replace/delete phrase, send (Enter), next field (Tab), stop.
- **Windows target awareness** — HWND/process tracking, profile-based backend selection, Z-order fallback, 30-second freshness window — [editing_backend.py](../src/hebrew_live_dictation/editing_backend.py).
- **UI Automation / Word COM integration** — [text_injector.py](../src/hebrew_live_dictation/text_injector.py).
- **QA matrix and TSF risk plan** — `docs/qa.md`, `docs/v2_tsf_risk_plan.md`.
- **Future TSF/IME path** — kept as a **gated R&D track** (`tsf.experimental_transport_enabled=false`); never default until it passes the promotion gate.
- **CI test gate + release audit** — `.github/workflows/build-release.yml`, [scripts/release_audit.py](../scripts/release_audit.py).
- **Schema-versioned config + migrations** — [config.py](../src/hebrew_live_dictation/config.py).
- **Privacy-by-default logging** — transcript redaction unless `debug_log_transcripts=true`.

Every issue in `EPICS_AND_ISSUES.md` carries a "must not regress" acceptance clause that re-checks the relevant strength.

---

## 5. Strategy: re-implement, never port

Because the stacks differ, each Repo-1 capability maps to a Python equivalent, chosen for fit, packaging cost, and maintainability:

| Repo-1 mechanism (Rust/Tauri) | Repo-2 equivalent (Python/PySide6) |
|---|---|
| `whisper-rs` (whisper.cpp FFI) local STT | `faster-whisper` (CTranslate2) — pip-installable, no C++ build |
| Deepgram WebSocket (`tokio-tungstenite`) | `websockets`/SDK streaming client |
| Groq REST (`reqwest`) | `requests`/`httpx` batch client |
| `keyring` crate (Windows Cred Manager) | Python `keyring` (same OS backend) |
| Tauri updater plugin (minisign + `latest.json`) | `updater.py` with embedded-pubkey manifest verification |
| `docx-rs` history export | `python-docx` RTL export |
| Tauri toolbar window | PySide6 frameless always-on-top draggable widget |
| `enigo` text injection | **already exceeded** by Repo 2's Word COM/UIA/SendInput stack |
| Tauri global-shortcut plugin | **already present** via `pynput`/low-level hook |

The provider abstraction is **low-risk** because [interfaces.py](../src/hebrew_live_dictation/interfaces.py) already defines `SpeechClient`, `TextCommitter`, and `CompositionCommitter` Protocols — the seams exist.

---

## 6. Provider capability matrix

The abstraction must accommodate both streaming and batch/final-only providers under a uniform cancellation + timeout contract. Hebrew-quality and latency/packaging rows are **hypotheses to validate** (via the benchmark suite, gap #12) before declaring parity — not assumptions.

| Capability | Google STT V2 / Chirp 3 (default) | faster-whisper (local) | Deepgram Nova-3 | Groq Whisper Turbo |
|---|---|---|---|---|
| Streaming | Yes (bidirectional) | No (segment / near-real-time) | Yes (WebSocket) | No (REST only) |
| Batch | Yes | Yes | Yes (prerecorded) | Yes |
| Interim results | Yes | No (final-only; emulation optional) | Yes | No |
| Offline | No | **Yes** | No | No |
| Cancellation | Yes (close stream) | Yes (stop decode) | Yes (close WS) | Limited (abort HTTP) |
| Timeout behavior | 285 s stream cap + auto-restart | Compute-bound → per-chunk timeout + RAM preflight | WS keepalive + net timeout | Per-request HTTP timeout |
| Fallback eligibility | Primary (needs creds) | **Local fallback target** | Primary cloud | Batch fallback or primary |
| Hebrew quality (validate) | High (iw-IL, Chirp 3) baseline | Model-dependent (large-v3 / ivrit-ai turbo) | High (per report) | Good, expected < Deepgram |
| Expected latency | Low | High (CPU; GPU optional) | Low | Medium (batch RTT; cheapest) |
| Packaging impact | Med (grpc/protobuf — already present) | **High** (CTranslate2 + models → download-on-demand) | Low (REST/WS) | Low (REST) |

---

## 7. Architecture changes (summary; full detail in `ARCHITECTURE_UPGRADE_PLAN.md`)

- **STT provider layer:** new `src/hebrew_live_dictation/stt/` (`base.py`, `google_v2.py`, `whisper_local.py`, `deepgram.py`, `groq.py`, `registry.py`). `stt_factory.create_stt_stream` dispatches on `config["stt.provider"]` (default `google_v2`). `FallbackSpeechClient` composes primary + local fallback via `stt.mode = api|local|auto_fallback`.
- **Credentials:** `secrets_store.py` over `keyring`; non-destructive JSON→keyring migration; UI exposes booleans + test buttons only.
- **Settings:** schema-version bump + migration; new keys `stt.*`, `providers.*`, `updater.*`, `audio.feedback_*`, `toolbar.*`, `history.*`, `models.*` — reusing the existing migration pattern in [config.py](../src/hebrew_live_dictation/config.py).
- **Local models:** `models.py` — download + SHA256 + RAM preflight (`psutil`), storage under `%APPDATA%\VoiceType\models`.
- **Updater:** `updater.py` — signed-manifest verification (embedded pubkey) → download → SHA256 corruption check → prompt + relaunch; remote `latest.json` kill-switch.
- **History/Export:** `history.py` + `export.py` (`python-docx` RTL, txt).
- **UI:** draggable frameless toolbar + idle circle; onboarding provider selection + key test; pause/resume controls; model-management page; history view.
- **Injection backends:** preserved unchanged; documented `InjectionBackend` selection keeps engine and injection decoupled.
- **Packaging/QA:** `signtool` signing (post-cert) + checksums in CI; dep pinning + lockfile; bandit/safety; coverage; extended `release_audit.py`; automated GUI smoke.

---

## 8. Implementation order (tightened) and roadmap

**Hard rule: engine stability before UI expansion.** UX parity is Phase F, after the engine is proven. Each phase ships behind a feature flag and must keep the existing 10 unittests + CI test gate green.

| Phase | Scope | Gap items | Day window |
|---|---|---|---|
| **0** | Non-engine maturity (parallel, no UI expansion): keyring + migration; updater foundation w/ signed manifest; crash handling; `SECURITY.md`; dep lockfile + SCA; compatibility smoke matrix | #4, #5 | 0–30 |
| **A** | Provider abstraction ONLY (`stt/` + registry + base); no behavior change | #1 | 0–30 |
| **B** | Move Google into the abstraction; prove ZERO regression; retire legacy path | #1 | ~30 |
| **C** | Local Whisper (`faster-whisper`) + model download-on-demand + RAM preflight + model-mgmt UI | #2, #10 | 30–60 |
| **D** | AutoFallback (`FallbackSpeechClient`) behind `stt.mode` | #3 | 30–60 |
| **E** | Deepgram (streaming+batch) + Groq (batch) + minimal provider-config UI + key test | #1, #11 | 60–90 |
| **F** | UX parity: floating toolbar + idle button, history + export, audio feedback, pause/resume | #6, #7, #8, #9 | 90–180 |
| **G** | Hardening + R&D (gated): code signing + Authenticode + checksums; GUI smoke; coverage; benchmark/WER; TSF promotion-gate work; freemium design doc | #12 + maturity | 180+ |

### Rollback plans (per risky phase)
- **A:** behind default `stt.provider=google_v2`; legacy path kept until B proves parity; revert = remove registry import.
- **B:** parity tests gate the merge; revert = `git revert` the move commit.
- **Keyring (0):** non-destructive — read keyring, fall back to JSON; never delete JSON until verified write.
- **Local Whisper (C):** download-on-demand, never bundle model; behind `providers.whisper.enabled`; revert = disable flag → cloud-only unaffected.
- **AutoFallback (D):** behind `stt.mode`; revert = `stt.mode=api`.
- **Deepgram/Groq (E):** additive; revert = remove from registry/UI list.
- **Updater (0/F):** opt-in + remote kill-switch; manual download always available.
- **Signing (G):** CI-side only; unsigned build still works; manifest signing independent of Authenticode.

---

## 9. Definition of Done (parity acceptance)

Parity is declared when **all** of the following hold:

1. Every **must-have-parity** row in `FEATURE_PARITY_MATRIX.md` is marked "have" with passing acceptance tests.
2. The app **runs offline** (no Google credentials) using the local Whisper provider.
3. **Provider switching is config-only** (no code change) across Google / local / Deepgram / Groq, with AutoFallback validated.
4. **No secret is stored in plaintext**; keyring round-trip + migration tests pass; `release_audit.py` confirms no plaintext credentials.
5. The **updater rejects** tampered/unsigned/wrong-key manifests and honors the kill-switch; a manual end-to-end upgrade succeeds.
6. The **Windows compatibility matrix** (Notepad/Word/Gmail/WhatsApp/Telegram/VS Code, 100%/150% DPI) passes per `QA_ACCEPTANCE_MATRIX.md`.
7. **No Repo-2 strength regressed** (Windows integration, command packs, session editing, CI/audit, privacy logging, gated TSF) — verified by the per-issue regression clauses.
8. **Re-running the Repo-1 ↔ Repo-2 comparison finds no Repo-1 advantage missing from Repo 2.**

---

## 10. How to use these documents

- **Owner / decision-maker:** read `FINAL_EXECUTIVE_SUMMARY.md` (Hebrew) and this file.
- **Engineering planning:** `FEATURE_PARITY_MATRIX.md` + `ARCHITECTURE_UPGRADE_PLAN.md` + `ADRS.md`.
- **Project tracking:** `EPICS_AND_ISSUES.md` (paste into GitHub) + `QA_ACCEPTANCE_MATRIX.md` + `RISK_REGISTER.md`.
- **Agent execution:** `CLAUDE_EXECUTION_PROMPTS.md` (Claude Code, phase by phase), `CODEX_HANDOFF_PROMPT.md` (Codex), `ANTIGRAVITY_REVIEW_PROMPT.md` (independent review).
- **Self-critique before committing budget:** `PLAN_AUDIT.md`.
