# VoiceType Final Product Completion Ledger

Status: Phase 0 source-discovery and scope ledger.
Branch under work: `feature/winui-redesign-migration`.
Branch tip at Phase 0 start: `05eebc738942264cd19efa8428ec3dfe8838372b`.
Date: 2026-06-23.

This document is the controlling ledger for the controlled 20-phase
"best of all worlds" completion program. It is not a beta-cleanup note and it
does not approve a release.

## Continue Protocol

Execution proceeds one phase at a time.

1. Complete the current phase.
2. Commit only that phase's changes.
3. Report the phase summary and stop.
4. Wait for the user to reply exactly `Continue`.
5. Start the next phase immediately after `Continue`.

Do not advance to the next phase without `Continue`.

## Protected Working Behavior

The following behavior is already known to work and must not regress:

- Google R3 path:
  - provider: Google STT V2
  - model: `latest_long`
  - location: `eu`
  - language: `iw-IL`
  - recognizer: `_`
- Google probe returns non-empty Hebrew transcript.
- Google runtime WAV path returns non-empty Hebrew transcript.
- Packaged app manual Google test passed.
- Offline dictation works in user testing.
- HUD and Remote live words work with Google.
- Target application receives final text only after Stop by default.
- Final text inserts once.
- No wrong-window insertion observed.
- No self-insertion observed.
- History matches inserted text.
- GitHub Actions unsigned artifact pipeline works.

Any phase that touches these paths must add or run targeted regression tests.

## Source Discovery

Phase 0 inspected the available local branches, tags, history, old planning
artifacts, and the sibling research repository.

### Current Product Baseline

- Branch: `feature/winui-redesign-migration`
- Commit: `05eebc738942264cd19efa8428ec3dfe8838372b`
- Type: current product baseline
- Contains:
  - WinUI shell and named-pipe Python sidecar
  - Google R3 rescue fixes
  - `tools/google_stt_probe.py`
  - STT provider registry and provider modules
  - Offline Whisper provider and model-management UI
  - Deepgram/Groq backend modules
  - AutoFallback/Smart Auto backend concepts
  - HUD and Remote live words
  - final-only insertion safety
  - History and TXT/DOCX export
  - diagnostics and packaged self-test
  - PyInstaller engine packaging and WinUI artifact workflow
- Why it matters:
  - It is the only branch with the current WinUI shell, packaging flow,
    Google proof path, and artifact pipeline.

### Original v1 Beta Baseline

- Tag: `v1.0.0-beta.2`
- Commit: `08ac2aed18d4a76a1703652b25a64eb2bc84f38c`
- Type: original product and engine baseline
- Contains:
  - original PySide app
  - Google STT V2 / Chirp-era setup
  - Windows insertion stack
  - TSF/IME gated R&D path
  - Inno setup / early release flow
  - initial QA and architecture docs
- Why it matters:
  - It is the earliest real "old app" product baseline and protects the
    original Windows insertion and Hebrew-first behavior.

### Best Old Python Product Baseline

- Branch: `feature/parity-upgrade`
- Tag: `v1.1.0`
- Commit: `c2424bd4cec02baa83ae66e581660fdb4c15d65c`
- Type: old product and engine capability baseline
- Contains:
  - STT provider abstraction
  - Google unified through abstraction
  - OS keyring credential handling
  - offline Whisper
  - Deepgram and Groq providers
  - AutoFallback and Smart Auto
  - model-management UI
  - history and TXT/DOCX export
  - audio start/stop tones
  - floating toolbar and idle quick-start button
  - pause hotkey
  - signed-manifest updater backend and signing helper
  - WER benchmark harness
- Why it matters:
  - It is the richest old Python app baseline. The final WinUI branch should
    keep the current shell while recovering the valuable old capabilities.

### Planning Baseline

- Branch: `main`
- Commit: `218f7662b31ebfb82ae34d8d013d17e06abb57ea`
- Type: docs and planning baseline
- Contains:
  - `output/MASTER_PARITY_PLAN.md`
  - `output/FEATURE_PARITY_MATRIX.md`
  - `output/ARCHITECTURE_UPGRADE_PLAN.md`
  - `output/EPICS_AND_ISSUES.md`
  - `output/QA_ACCEPTANCE_MATRIX.md`
  - `output/RISK_REGISTER.md`
  - ADRs and handoff/review prompts
- Why it matters:
  - It captured the broad parity/product vision before the WinUI migration.
    It is useful evidence, but it is stale because the current WinUI branch
    has already implemented many items it listed as gaps.

### Research Source

- Path: `..\hebrew-dictation-main`
- Upstream reference: `aihenryai/hebrew-dictation`
- Type: research and product-source repository
- Contains:
  - Tauri/Rust/React app
  - Deepgram and Groq provider UX
  - keyring-backed provider API keys
  - Deepgram streaming with interims
  - Groq final-only batch transcription
  - true pause/resume
  - VAD and recording-duration controls
  - floating toolbar and idle button
  - updater product flow
  - model-download UX and Hebrew model thinking
- Why it matters:
  - It contributes product-shape ideas. It should not be copied wholesale
    because the current VoiceType branch has stronger Windows insertion safety.

## Correct Baseline Conclusion

There is no single old baseline.

The final product branch must combine:

1. The original product safety and Windows insertion depth from `v1.0.0-beta.2`.
2. The richer old Python capability set from `feature/parity-upgrade` / `v1.1.0`.
3. The broad parity planning from `main` and `output/`.
4. The current WinUI shell, packaging, HUD/Remote, Google rescue, diagnostics,
   and safety work from `feature/winui-redesign-migration`.
5. The product UX lessons from `..\hebrew-dictation-main`.

## Current Capability Map

Already present in the current WinUI branch:

- Google STT V2 provider with proven `latest_long/eu/iw-IL/_` path.
- Google diagnostic probe.
- Google active config display and verification signature.
- Google no-transcript failure surfacing.
- Latest-model request-shape fix for unsupported punctuation.
- Offline Whisper provider.
- Offline model catalog, selected-model download/delete, incomplete-cache recovery,
  active-download state, and readiness checks.
- Controls-room audio/VAD advanced settings for frame length, endpointing,
  auto-stop timing, local VAD, and final-only segment silence.
- Optional start/stop audio feedback tones with Controls-room enable/volume,
  cached generated WAV tones, and WinUI runtime playback.
- Session-preserving pause/resume with a dedicated optional hotkey, paused UI
  state, generation-guarded provider events, and stop-from-paused final flush.
- STT registry with Google, Whisper, Deepgram, Groq, and fallback modules.
- AutoFallback and Smart Auto backend behavior plus Engine-room routing status.
- WinUI Home, Dictation, Engine, Controls, History, and Settings rooms.
- HUD and Remote overlay surfaces.
- Floating Remote visibility policy for always-on mode and hidden-console idle
  quick-start mode.
- final-only target insertion default.
- Word COM, UI Automation, clipboard, and Unicode insertion backends.
- Target tracking, shell self-target blocking, and target-changed handling.
- History persistence and TXT/DOCX export.
- Diagnostics and packaged self-test.
- PyInstaller engine packaging and GitHub unsigned artifact workflow.
- Keyring wrapper and signed-updater backend code.

Partially present or hidden:

- Deepgram backend and setup UX exist; real service PASS still requires a user key.
- Groq backend and final-only setup UX exist; real service PASS still requires a user key.
- Keyring-backed provider credential UX/migration exists for keyed cloud providers.
- Updater backend exists, but WinUI update check/install UX is incomplete.
- Advanced VAD/custom phrase settings exist, but product UI is incomplete.
- Live target typing exists in engine tests/config but is forced off in the WinUI
  beta path for safety.

## Final Feature Inventory

The completion program includes these feature groups:

- Core dictation: toggle, push-to-talk, F8, Copilot/F23, configurable hotkeys,
  true pause/resume, stop while processing, cancel, target capture and
  target-change handling, no wrong-window insertion, no self-target insertion,
  no focus stealing, final-only default insertion, Labs live target typing,
  long sessions, and short sessions.
- Windows insertion: clipboard paste, Unicode keyboard fallback, Word COM,
  UI Automation, browser fields, VS Code/Electron fields, WhatsApp/Telegram,
  File Explorer safety, RTL handling, punctuation/newline commands, duplicate
  prevention, and target recovery.
- STT provider system: Google STT V2, Chirp/latest models, Offline Whisper,
  Deepgram, Groq, provider abstraction, provider UI, provider credentials,
  provider testing, provider diagnostics, fallback, Smart Auto, provider
  priority/status, and keyring.
- Google complete path: project ID, service account JSON, ADC, `_` recognizer,
  custom recognizer, model/location/language controls, verification marker,
  probe, real streaming dictation, interims/finals, no-transcript failure,
  punctuation feature gating, docs, and UI honesty.
- Offline Whisper: model catalog, small/medium/large, Hebrew quality guidance,
  download/progress/cancel/resume/retry, delete, corrupt/incomplete recovery,
  local-only privacy, packaging dependencies, and Hebrew-specialized model
  investigation.
- Audio: microphone selection, device errors, sample rate and resampling,
  channels, VAD and silence controls, start/stop tones, volume, recording
  state, latency, and logging.
- Surfaces: HUD live words, Remote live words/start/stop, no activate, no
  focus steal, click-through where appropriate, old floating toolbar parity,
  idle quick-start button, status states, placement, and multi-monitor behavior.
- Hebrew UX: punctuation commands, newline/new paragraph, delete/editing
  commands, command packs, spoken punctuation and emoji, phrase boost, custom
  phrases, `iw-IL` / `he-IL` clarity, and RTL UI.
- History/privacy: persistence, search/filter, delete item, clear all, privacy
  mode, TXT and DOCX export, RTL correctness, timestamps, provider metadata,
  and redaction.
- Settings/config: schema and migrations, reset/recovery, stale config safety,
  Advanced/Labs, user-friendly settings, old PySide settings parity where
  useful, and secrets redaction.
- Diagnostics/QA: engine log, shell log, copy diagnostics, crash dumps,
  selftest, packaged verify, Google probe, provider diagnostics, model
  diagnostics, target diagnostics, and QA checklist.
- Packaging/install: PyInstaller engine, WinUI packaging, hidden imports,
  Google/grpc/protobuf, Whisper/faster-whisper dependencies, unsigned artifact,
  signed-manifest updater, Authenticode hook, install/uninstall flow,
  SmartScreen limitation, and autostart/tray startup.
- Product UI/docs: onboarding, Home, Dictation, Engine, Controls, History,
  Settings, Advanced, Labs, Remote, HUD, tray, Hebrew-first copy, and honest
  limitations.

## Labs-Only Features

These may be implemented during the program, but must stay disabled by default
and must never be described as stable unless they pass the promotion gate:

- Live target typing into external apps.
- TSF/IME composition transport.
- Advanced Google model/location/language combinations beyond proven combos.
- Custom phrase boost if it changes cloud request shape.
- GPU/CUDA local Whisper.
- Hebrew-specialized / ivrit models until licensing, packaging, and quality are
  proven.
- Smart Auto as a default.
- Unattended auto-update install.

## Not-Now Items With Hard Justification

The following are not implementation targets for this program unless their
external constraint changes:

- Stable live target typing across all Windows apps:
  - Plain text injection cannot behave like a real IME composition string
    safely in every RTL field. Stable promotion requires TSF/IME proof.
- Authenticode-signed public release:
  - Requires an OV/EV code-signing certificate. Hooks and docs can be added;
    a signed artifact cannot be produced without the certificate.
- Freemium/token-broker cloud proxy:
  - Requires hosted infrastructure plus product, billing, abuse-prevention,
    security, and legal decisions. A design/interface note is acceptable; a
    shipped proxy is not.
- Real Deepgram/Groq service PASS without user keys:
  - Code can be tested with mocks and optional probes. Real PASS requires
    external provider credentials/accounts.

## Phase List

The approved execution program contains exactly 20 phases:

0. Completion ledger
1. Golden safety harness
2. Docs/UI truth reset
3. Provider control plane
4. Credentials/keyring completion
5. Deepgram productization
6. Groq productization
7. Smart Auto / AutoFallback UX
8. Offline model manager v2
9. Audio/VAD Advanced room
10. True pause/resume
11. Audio feedback tones
12. Remote/toolbar/idle parity
13. Commands/custom phrases
14. Live typing Labs / TSF gate
15. History/privacy completion
16. Updater/install/versioning
17. Diagnostics/selftest expansion
18. Packaging/dependency/security hardening
19. Final QA, CI, artifact, review prep

## Phase Commit Boundaries

Each phase should commit only its own logical work. If a phase uncovers a bug in
its own layer, fix it inside that phase. If it uncovers a future-phase gap, add a
note to this ledger or the phase report and leave implementation for that future
phase.

Suggested commit names:

- Phase 0: `docs: add final product completion ledger`
- Phase 1: `tests: add golden dictation safety harness`
- Phase 2: `docs-ui: reset product claims for final WinUI branch`
- Phase 3: `engine: add provider capability and status control plane`
- Phase 4: `security: complete provider credential keyring flow`
- Phase 5: `providers: productize Deepgram setup and diagnostics`
- Phase 6: `providers: productize Groq setup and final-only flow`
- Phase 7: `fallback: productize smart auto and offline backup status`
- Phase 8: `offline: harden model downloads and model catalog`
- Phase 9: `audio: add advanced VAD and recording controls`
- Phase 10: `dictation: add true pause and resume`
- Phase 11: `controls: restore optional audio feedback tones`
- Phase 12: `surfaces: add toolbar idle quick-start without focus steal`
- Phase 13: `language: add custom phrase and command controls`
- Phase 14: `labs: gate experimental live target typing`
- Phase 15: `history: add search delete metadata and privacy controls`
- Phase 16: `updater: add signed update check product flow`
- Phase 17: `diagnostics: expand provider target and package selftests`
- Phase 18: `packaging: harden dependencies and security gates`
- Phase 19: `docs: prepare final independent review package`

## Test Strategy

Automated tests to grow over the program:

- Python unit and integration suite.
- Provider registry/factory tests.
- Google request and response tests.
- Offline model readiness/interruption tests.
- Deepgram/Groq mocked provider tests.
- Fallback tests.
- Dictation controller pause/resume tests.
- Text injector no-duplicate and final-only default tests.
- History/export tests.
- Keyring and redaction tests.
- Updater manifest tests.
- Release audit.
- WinUI build.
- Packaged verify.

Manual or external proof required later:

- Real Deepgram transcription with user key.
- Real Groq transcription with user key.
- Authenticode signing with a real certificate.
- Final Windows target matrix across real apps.
- Real updater end-to-end against a staged or release endpoint.

## Final Review Strategy

After Phase 19:

1. Produce a review packet with branch tip, commits, files changed, tests run,
   proof logs, known limitations, and artifact link.
2. Send the packet to a fresh Codex thread for code-level review:
   - safety
   - packaging
   - secrets
   - Windows insertion
   - regressions
3. Send the packet to a fresh Claude thread for product-level review:
   - parity
   - UX honesty
   - docs
   - provider flow
   - completeness
4. Classify findings as blocker, must-fix, should-fix, or document.
5. Do not approve public beta or final release until blockers are closed.

## Phase 0 Acceptance

Phase 0 is complete when:

- This ledger exists in the current WinUI branch.
- It records all inspected baselines and why each matters.
- It records the protected behavior.
- It records the full 20-phase plan.
- It classifies Labs-only and not-now items with explicit justification.
- It does not trigger CI or build an artifact.
