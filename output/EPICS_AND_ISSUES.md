# EPICS & ISSUES — GitHub-ready backlog

Paste epics/issues into GitHub. Labels are suggested; adjust to the repo's scheme.
**Global guardrails (apply to every issue):** do not merge the two codebases; preserve Repo-2 strengths; keep TSF gated (`tsf.experimental_transport_enabled=false`); each PR keeps the existing 10 unittests + CI test gate green; ship behind a feature flag; include the issue's acceptance tests.

**Label set:** `epic` · `parity-must` · `beyond` · `rnd` · `preserve` · `engine` · `ux` · `security` · `packaging` · `qa` · `docs` · `P0`/`P1`/`P2`/`P3` · `risk:low|med|high`

**Dependency graph (high level):**
`E1 (abstraction) → E2 (move Google) → {E3 local, E4 deepgram/groq} → E5 fallback → E8 UX`. `E6 keyring` and `E7 updater` are parallel/early. `E9 packaging/QA` and `E10 docs/maturity` are cross-cutting. `E11 R&D` is gated/last.

---

## EPIC E0 — Phase 0 foundation (no UI expansion) `epic`
**Goal:** raise production maturity and de-risk before engine work. **Depends on:** none.

### E0.1 Global crash/exception handling + diagnostics `P0` `qa`
- Install a top-level `sys.excepthook` + Qt message handler; write to the redacted log under `%APPDATA%`; show a non-leaking error dialog.
- **Acceptance:** an injected unhandled exception is logged (no transcript/secret leakage) and surfaces a user dialog; app does not silently die. Existing tests green.

### E0.2 SECURITY.md + vuln-disclosure `P2` `beyond` `docs`
- Add `SECURITY.md` (contact, scope, coordinated disclosure, supported versions).
- **Acceptance:** file present; linked from README.

### E0.3 Dependency pinning + lockfile `P2` `beyond` `packaging`
- Introduce a lockfile (pip-tools/`uv`); pin runtime deps; document update cadence.
- **Acceptance:** clean install from lockfile reproduces the environment; CI uses it.

### E0.4 SCA in CI `P2` `beyond` `security`
- Add `bandit -r src/`, `pip-audit`/`safety`, enable Dependabot.
- **Acceptance:** CI runs SCA; findings visible; no high-severity unaddressed.

### E0.5 Formalize Windows compatibility smoke matrix `P1` `qa`
- Turn `docs/qa.md` targets into a tracked checklist (Notepad/Word/Gmail/WhatsApp/Telegram/VS Code, 100%/150% DPI).
- **Acceptance:** matrix doc exists; release gate references it.

---

## EPIC E1 — STT provider abstraction (Phase A) `epic` `parity-must` `engine` `P0`
**Goal:** introduce `stt/` + registry + `SpeechClientBase` with **zero behavior change**. **Depends on:** E0 (parallel ok). **Gap #1.**

### E1.1 Create `stt/base.py` `SpeechClientBase` `P0` `risk:med`
- Uniform `start/stop/restart_stream/cancel`, `capabilities`, event emission; conforms to `interfaces.SpeechClient`.
- **Acceptance:** unit tests for the base contract (start/stop/cancel/timeout, event shape).

### E1.2 Create `stt/registry.py` + capability metadata `P0`
- `ProviderRegistry` maps name → (factory, capabilities).
- **Acceptance:** registry returns the Google provider for `google_v2`; unknown name raises a clear error.

### E1.3 Wrap existing Google class as `google_v2` (no move yet) `P0` `preserve`
- Feature-flag `stt.provider` (default `google_v2`); legacy `stt_factory` path retained.
- **Acceptance:** with default config, behavior byte-identical to today; `tests/test_google_stt_v2_stream.py` green.

---

## EPIC E2 — Move Google into the abstraction; prove zero regression (Phase B) `epic` `parity-must` `engine` `P0`
**Goal:** relocate `google_stt_v2_stream.py` → `stt/google_v2.py`, subclass base, retire legacy path. **Depends on:** E1. **Gap #1.**

### E2.1 Relocate + subclass `SpeechClientBase` `P0` `risk:med`
- **Acceptance:** behavioral-parity test (recorded audio fixture → identical interim/final event sequence vs pre-move baseline).

### E2.2 Retire legacy direct-factory path `P0`
- **Acceptance:** only the registry path remains; all existing tests + CI green; **rollback** documented (`git revert`).

---

## EPIC E3 — Local Whisper provider + model management (Phase C) `epic` `parity-must` `engine` `P1`
**Goal:** offline STT via `faster-whisper`. **Depends on:** E2. **Gaps #2, #10.** ADR-003.

### E3.1 `models.py` download + SHA256 + RAM preflight `P1` `risk:med`
- Model registry; download-on-demand; reject hash mismatch; `psutil` RAM check; storage under `%APPDATA%\VoiceType\models`.
- **Acceptance:** corrupt download rejected; low-RAM machine gets a clear refusal/warning, not a crash.

### E3.2 `stt/whisper_local.py` provider `P1` `risk:med`
- Buffer between endpoints; per-chunk timeout; emit final-only; `capabilities.offline=True, interim=False`.
- **Acceptance:** transcribe a Hebrew fixture offline (no network) end-to-end; cancellation stops promptly.

### E3.3 Model-management UI page `P2` `ux`
- Download/delete/status, active-model selector, RAM warning.
- **Acceptance:** UI reflects model state; selecting a model switches the provider config only.

---

## EPIC E4 — Deepgram + Groq providers (Phase E) `epic` `parity-must` `engine` `P1`
**Goal:** cloud multi-provider. **Depends on:** E2 (and E6 keyring). **Gap #1.** ADR-004.

### E4.1 `stt/deepgram.py` (WebSocket streaming + REST batch) `P1` `risk:med`
- Interim+final via WS; key from keyring; maps errors to terminal/non-terminal for fallback.
- **Acceptance:** streaming Hebrew transcription works; invalid key → clear error event (no crash).

### E4.2 `stt/groq.py` (REST batch, final-only) `P1`
- Buffer utterance → POST → final; `capabilities.streaming=False, interim=False`.
- **Acceptance:** batch Hebrew transcription works; timeout handled.

### E4.3 Provider-config UI + "Test key" (Phase E, gap #11) `P2` `ux`
- Provider cards; "Test key/credentials" pings provider; never displays the secret.
- **Acceptance:** test button reports success/failure; switching provider is config-only.

---

## EPIC E5 — AutoFallback (Phase D) `epic` `parity-must` `engine` `P1`
**Goal:** `FallbackSpeechClient` primary→local. **Depends on:** E3 (local target). **Gap #3.** ADR-005.

### E5.1 `stt/fallback.py` + `stt.mode` `P1` `risk:med`
- Bounded buffer + drop policy; on terminal primary error, replay to local; emit `status: falling_back`.
- **Acceptance:** simulated primary outage → output continues via local; buffer bounded; UI shows offline switch; revert via `stt.mode=api`.

---

## EPIC E6 — Keyring credentials + migration (Phase 0) `epic` `parity-must` `security` `P0`
**Goal:** no plaintext secrets. **Depends on:** none (parallel). **Gap #4.** 

### E6.1 `secrets_store.py` (keyring wrapper) `P0` `risk:low`
- Per-provider entries; `get/set/delete/has`; fall back to JSON read if keyring unavailable.
- **Acceptance:** keyring round-trip test; UI shows booleans only.

### E6.2 Non-destructive JSON→keyring migration `P0`
- Import on load; **do not delete JSON until verified keyring read-back**; migration toggle + banner.
- **Acceptance:** migration test (JSON secret → keyring; JSON cleared only after verify); rollback re-enables JSON read.

### E6.3 Extend `release_audit.py` secret scanning `P1` `security`
- Add Deepgram/Groq key patterns; assert no plaintext secrets.
- **Acceptance:** audit fails on a planted fake key; passes clean tree.

---

## EPIC E7 — Signed-manifest auto-updater (Phase 0/F) `epic` `parity-must` `security` `packaging` `P1`
**Goal:** tamper-evident updates. **Depends on:** CI release flow. **Gap #5.** ADR-006.

### E7.1 CI signs `latest.json` + publishes signature `P1` `risk:med`
- Ed25519/minisign; private key as CI secret/offline; publish `latest.json` + `.sig` + installer + SHA256SUMS.
- **Acceptance:** release artifacts include signed manifest; key never in repo.

### E7.2 `updater.py` verify→download→install `P1` `risk:med`
- Embed pubkey; verify signature first; version compare; SHA256 corruption check; prompt + relaunch; honor kill-switch; manual fallback.
- **Acceptance:** rejects unsigned/tampered/wrong-key manifest; honors `disabled`; happy-path upgrade succeeds.

---

## EPIC E8 — UX parity (Phase F) `epic` `parity-must` `ux` `P2`
**Goal:** match Repo-1 UX. **Depends on:** E2+ (engine stable). **Gaps #6–#9, #11.**

### E8.1 Floating toolbar + idle button (gap #6) `P2` `risk:low`
- Frameless, on-top, **no focus steal** (`WA_ShowWithoutActivating`); draggable; persisted position; recording bar + idle circle; invariant with main window.
- **Acceptance:** dictation continues while toolbar visible (focus not stolen); position persists; idle click starts.

### E8.2 History + TXT/DOCX export (gap #7) `P2`
- `history.py` store + `export.py` RTL DOCX/TXT.
- **Acceptance:** finalized session appears in history; DOCX opens RTL-correct in Word.

### E8.3 Audio-feedback tones (gap #8) `P3`
- `QSoundEffect` start/stop; volume setting.
- **Acceptance:** tones play when enabled, silent when disabled.

### E8.4 Pause/resume + pause hotkey (gap #9) `P2`
- Controller `pause()/resume()`; optional pause hotkey.
- **Acceptance:** pause holds capture without finalizing; resume continues same session.

---

## EPIC E9 — Packaging, signing, QA automation (Phase G) `epic` `beyond`/`parity-must` `packaging` `qa` `P2`
**Goal:** release maturity. **Depends on:** E7.

### E9.1 Code signing (Authenticode) `P2` `risk:med`
- Acquire OV/EV cert; `signtool` in CI; updater verifies Authenticode.
- **Acceptance:** installer signed; SmartScreen friction reduced; updater checks signature.

### E9.2 Release checksums/signatures `P2`
- Publish SHA256SUMS + signed manifest (with E7).
- **Acceptance:** checksums match; documented verification steps.

### E9.3 Automated GUI smoke + coverage `P2` `qa`
- pyautogui/uiautomation smoke (Notepad/Chrome + DPI); coverage reporting.
- **Acceptance:** smoke runs in CI/where feasible; coverage published.

---

## EPIC E10 — Benchmark/WER suite + docs (cross-cutting) `epic` `parity-must`/`docs` `P3`
**Goal:** validate provider/model Hebrew quality; document. **Gap #12.**

### E10.1 Python WER harness `P3`
- Compare Google/Deepgram/Groq/whisper models on Hebrew samples; output table + recommendation.
- **Acceptance:** harness produces WER per provider; results feed default-model guidance (mirrors Repo 1 `benchmark/`).

### E10.2 Docs refresh `P2` `docs`
- InjectionBackend contract; updated architecture/QA; CHANGELOG; link ADRs.
- **Acceptance:** docs current; CHANGELOG started.

---

## EPIC E11 — R&D (gated) `epic` `rnd` `P3`
**Goal:** advance gated tracks without affecting production. ADR-007, ADR-008.

### E11.1 TSF/IME promotion-gate work `P3` `risk:high` `preserve`
- Execute the `docs/qa.md` TSF gate; keep `experimental_transport_enabled=false`; fail-closed.
- **Acceptance:** gate checklist recorded; no regression to v1 path; remains off by default.

### E11.2 Freemium proxy design doc `P3` `rnd`
- Document quota/abuse/billing design; no build.
- **Acceptance:** design doc exists; explicitly not shipped.

---

## Suggested milestones
- **M1 (0–30d):** E0, E1, E6, E7.1. 
- **M2 (30–60d):** E2, E3, E5.
- **M3 (60–90d):** E4 (+E6 wired), E7.2.
- **M4 (90–180d):** E8.
- **M5 (180+d):** E9, E10, E11.
