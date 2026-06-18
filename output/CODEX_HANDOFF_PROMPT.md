# CODEX HANDOFF PROMPT

Paste the block below into OpenAI Codex (or a Codex-style coding agent). It is self-contained. Replace `<REPO_ROOT>` with the absolute path to `cdtauman/HebrewLiveDictation`.

---

```
You are implementing a parity-upgrade program for a Windows Hebrew dictation app.

REPOSITORY (the ONLY repo you modify): <REPO_ROOT>  (cdtauman/HebrewLiveDictation)
STACK: Python 3.12 + PySide6. Tests: `python -m unittest discover -s tests` with PYTHONPATH=src.

DO NOT:
- Do not merge or import code from the other repo (aihenryai/hebrew-dictation, a Tauri/Rust app). Re-implement equivalents in Python only.
- Do not enable or default the TSF/IME path. It MUST stay gated: tsf.experimental_transport_enabled=false, fail-closed to the v1 final-only path.
- Do not regress Repo-2 strengths: Word COM / UI Automation / Unicode SendInput / clipboard injection, target tracking (HWND/process/Z-order/30s freshness), multi-language command packs (he/en/ar/ru/fr/es), session editing (delete word/sentence, undo-20, replace/delete phrase, send, next field, stop), schema-versioned config + migrations, privacy-by-default logging, the GitHub Actions CI test gate, and scripts/release_audit.py.
- Do not store secrets in plaintext or print them in logs.
- Do not bundle Whisper models into the installer.

GOAL: Reach full parity with the Tauri app's dictation-engine, credentials, updater, and UX advantages, while keeping Google STT V2/Chirp 3 as the DEFAULT provider.

GROUND TRUTH SEAMS (already in the code):
- src/hebrew_live_dictation/interfaces.py defines Protocols: SpeechClient, AudioSource, TextCommitter, CompositionCommitter, CommandParser.
- src/hebrew_live_dictation/stt_factory.py currently hardcodes Google (google_stt_v2_stream.py).
- src/hebrew_live_dictation/config.py is schema-versioned with migrations (reuse this pattern).
- text_injector.py / editing_backend.py own injection — keep engine and injection decoupled; do not touch these during engine phases.

IMPLEMENT IN THIS STRICT ORDER (one PR per phase; each PR must keep all existing tests + CI green and ship behind a feature flag):

PHASE 0 (parallel, no UI expansion):
- secrets_store.py over the `keyring` library (service "HebrewLiveDictation"), per-provider entries (deepgram, groq; Google SA-JSON or ADC). Non-destructive JSON->keyring migration: import on load, delete the JSON secret ONLY after a verified keyring read-back; fall back to JSON read if keyring is unavailable. UI exposes booleans + "Test" buttons only.
- updater.py: poll GitHub releases latest.json, VERIFY an Ed25519/minisign signature over the manifest using a PUBLIC KEY EMBEDDED IN THE APP before trusting any field (SHA256 is a corruption check only, because manifest and installer are co-hosted). Compare versions, download the signed Inno installer, SHA256-check, prompt, relaunch. Honor a signed kill-switch / min-version. Manual download must remain possible. Add CI step to sign the manifest (private key as CI secret).
- Global crash handling (sys.excepthook + Qt handler) writing to the redacted log. Add SECURITY.md. Add a dependency lockfile + bandit/pip-audit in CI. Extend release_audit.py with Deepgram/Groq key patterns.

PHASE A — provider abstraction ONLY (no behavior change):
- Create package src/hebrew_live_dictation/stt/ with base.py (SpeechClientBase: uniform start/stop/restart_stream/cancel, a per-op timeout, capabilities {streaming, batch, interim, offline, fallback_target}, and an error taxonomy {terminal, retryable}), and registry.py (ProviderRegistry: name -> (factory, capabilities)).
- Wrap the EXISTING Google class as provider "google_v2". stt_factory.create_stt_stream dispatches on config["stt.provider"] (default "google_v2"). Keep the legacy path importable.

PHASE B — move Google into the abstraction, prove ZERO regression:
- Relocate google_stt_v2_stream.py to stt/google_v2.py and subclass SpeechClientBase.
- Add a behavioral-parity test: a recorded Hebrew audio fixture must produce an IDENTICAL interim/final event sequence vs the pre-move baseline. Only then remove the legacy path.

PHASE C — local Whisper:
- models.py: model registry, download-on-demand with SHA256 verification, RAM preflight via psutil, storage under %APPDATA%\VoiceType\models, delete/status APIs.
- stt/whisper_local.py: faster-whisper provider; buffer audio between endpoints; per-chunk timeout; emit FINAL ONLY (capabilities.interim=False, offline=True, fallback_target=True). Must transcribe a Hebrew fixture with the network disabled and no Google credentials.

PHASE D — AutoFallback:
- stt/fallback.py FallbackSpeechClient(primary, local), selected by config stt.mode in {api, local, auto_fallback}. Bounded audio buffer + drop policy. On a TERMINAL primary error, emit status "falling_back" and replay the buffered utterance to local. Default stt.mode conservative until validated.

PHASE E — Deepgram + Groq:
- stt/deepgram.py: WebSocket streaming + REST batch (interim+final). stt/groq.py: REST batch, final-only.
- Keys from secrets_store. Add provider-selection UI + "Test key/credentials" (engine config only).

PHASE F — UX parity (only after engine is stable):
- Floating toolbar + idle button: PySide6 frameless, always-on-top, MUST NOT steal focus (set Qt.WA_ShowWithoutActivating and Qt.Tool|Qt.FramelessWindowHint). Draggable; persist position. Recording bar + idle circle; mutually exclusive with main window.
- history.py + export.py: persistent transcription history + TXT and RTL-correct DOCX export (python-docx with bidi/RTL run direction).
- Audio-feedback tones (QSoundEffect) + volume setting.
- Pause/resume in the controller state machine + optional pause hotkey (hotkeys.py).

CONFIG: bump the config schema version and add a migration for new keys: stt.provider, stt.mode, providers.*, models.*, updater.*, audio.feedback_*, toolbar.*, history.*. Preserve all existing keys/defaults.

ACCEPTANCE (per phase): add tests proving the phase's behavior AND a regression check that the relevant Repo-2 strength is intact. Specifically:
- Provider switch is config-only across google_v2/whisper_local/deepgram/groq.
- App runs offline with whisper_local (no network, no Google creds).
- Keyring round-trip + non-destructive migration.
- Updater rejects tampered/unsigned/wrong-key manifests and honors the kill-switch.
- Word COM / UIA / SendInput / clipboard injection, command packs, and session editing still pass.
- TSF remains gated and fails closed.

WORKFLOW: small PRs, conventional commits, never skip hooks. After each phase run the full test suite and report results honestly. If a phase risks regression, STOP and surface it rather than forcing the change. Provide a rollback note per PR (feature flag to disable, or git revert target).
```
