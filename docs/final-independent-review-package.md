# VoiceType Final Independent Review Package

Status: prepared at Phase 19 of the controlled 0-19 completion program.

Branch: `feature/winui-redesign-migration`

Review packet branch tip: see the Phase 19 report and `git rev-parse HEAD`.

Baseline before the 20-phase program: `05eebc7`

This packet is for fresh Codex and Claude review. It is not public beta
approval, not release approval, and not a claim that every manual Windows or
paid-provider gate has passed.

## Current Verdict

- Offline dictation path: automated local gates pass; final manual artifact
  target matrix still required.
- Google STT V2: probe and runtime WAV path were previously proven for the
  protected combo, but full packaged-app R3 manual proof remains required.
- Deepgram and Groq: product flows and mocked tests are present; real provider
  PASS requires user keys and live service proof.
- Public beta: not approved.
- Release: not approved.
- Artifact: fresh CI artifact must be generated from this branch tip before
  manual R3/P5 testing.

## Phase Commits

| Phase | Commit | Purpose |
| --- | --- | --- |
| 0 | `d74c90c` | Completion ledger |
| 1 | `36375f4` | Golden dictation safety harness |
| 2 | `4b21a99` | Docs/UI truth reset |
| 3 | `8431a50` | Provider control plane |
| 4 | `011714b` | Credentials/keyring completion |
| 5 | `53afb7b` | Deepgram productization |
| 6 | `e12db44` | Groq productization |
| 7 | `9a78a39` | Smart Auto / AutoFallback UX |
| 8 | `ffb0a78` | Offline model manager v2 |
| 9 | `d5df10b` | Audio/VAD Advanced room |
| 10 | `00ebc72` | True pause/resume |
| 11 | `a30fbb8` | Audio feedback tones |
| 12 | `e6404dc` | Remote/toolbar/idle parity |
| 13 | `65cfed3` | Commands/custom phrases |
| 14 | `811105f` | Live typing Labs / TSF gate |
| 15 | `3e953d6` | History/privacy completion |
| 16 | `c8fdce5` | Updater/install/versioning |
| 17 | `d490434` | Diagnostics/selftest expansion |
| 18 | `d3d2b81` | Packaging/dependency/security hardening |
| 19 | this document's commit | Final QA/review package |

## Changed Areas Since Baseline

- WinUI shell: Home, Engine, Dictation, Controls, History, Settings, onboarding,
  HUD, Remote, tray, runtime selftest, shell logs.
- Engine sidecar: provider control plane, Google status/verification, provider
  credentials, fallback routing, diagnostics snapshot, history/privacy,
  model manager, pause/resume state.
- STT providers: Google stabilization, Deepgram, Groq, local fallback,
  provider registry and verification.
- Text and insertion: final-only default, no duplicate insertion, target
  reassurance, Labs gate for live typing and TSF.
- Packaging and QA: PyInstaller spec, unsigned beta workflow, packaged verify
  scripts, packaging audit, release audit.
- Docs: architecture truth rules, beta checklist, updater docs, final completion
  ledger.

## Automated Proof To Re-run

Run these from the repository root before asking for independent review:

```powershell
$env:PYTHONPATH='src'
.venv\Scripts\python.exe scripts\packaging_audit.py
.venv\Scripts\python.exe scripts\release_audit.py
.venv\Scripts\python.exe -m unittest discover -s tests
dotnet build winui\VoiceType.App\VoiceType.App.csproj -c Release
& 'winui\VoiceType.App\bin\Release\net9.0-windows10.0.19041.0\win-x64\VoiceType.exe' --selftest
```

Expected local proof at packet creation:

- Packaging audit: pass.
- Release audit: pass.
- Python tests: pass.
- WinUI Release build: pass.
- WinUI runtime selftest: pass.

## CI And Artifact Gate

The intended manual-test artifact is the GitHub Actions artifact named
`VoiceType-winui-beta-unsigned` from `.github/workflows/winui-beta.yml`.

The artifact must be generated from the Phase 19 branch tip, and testers should
record the run URL and SHA in `docs/winui-beta-test-checklist.md`.

The artifact is unsigned. It is a manual-test artifact only.

Do not tag a release, do not approve public beta, and do not describe the
artifact as a release candidate until the manual gates below are actually
passed.

## Manual Or External Proof Still Required

- Google full app R3 against the packaged artifact:
  `latest_long / eu / iw-IL / _`, active config line matches, engine log matches,
  HUD/Remote interims only if the model emits interims, Notepad stays empty while
  speaking, Stop inserts final once, History matches.
- Full P5 Windows target matrix against the CI artifact: Notepad, Word, browser
  fields, messaging apps, VS Code, target-changed case, no self-target, no focus
  steal, no duplicate final insertion.
- Real Deepgram transcription with a user key.
- Real Groq transcription with a user key.
- Authenticode signing with a real certificate.
- Real updater end-to-end against a staged signed manifest/installer endpoint.

## Fresh Codex Review Prompt

Review this branch as a skeptical code and release-safety reviewer. Focus on:

- provider/runtime config truth
- Google STT V2 request construction and no-text failure behavior
- fallback and final insertion duplication risk
- Windows focus/target safety
- credential and secret storage/redaction
- packaging hidden imports and audit gates
- tests that overclaim behavior they do not prove
- docs or UI copy that implies release readiness too early

Classify every finding as blocker, must-fix, should-fix, or document.

## Fresh Claude Review Prompt

Review this branch as a skeptical product/parity reviewer. Focus on:

- whether the WinUI product honestly replaces the prior working app
- whether Engine/Dictation/Controls/History/Settings surfaces are coherent
- whether Google, Deepgram, Groq, Smart Auto, and Offline are described honestly
- whether manual QA can be run without guessing
- whether Labs/future features are clearly separated from stable behavior
- whether beta copy, docs, and onboarding overclaim readiness

Classify every finding as blocker, must-fix, should-fix, or document.

## Do Not Do

- Do not approve public beta from automated tests alone.
- Do not treat Google Test Connection as dictation proof.
- Do not treat a CI artifact as a signed release.
- Do not commit credentials, private WAV files, crash dumps, logs, or local
  build output.
- Do not enable live target typing outside Labs.
- Do not mark Google full app R3 PASS until the packaged manual test passes.
