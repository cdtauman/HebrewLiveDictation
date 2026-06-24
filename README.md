# VoiceType — Hebrew Live Dictation (WinUI)

VoiceType (repository: `HebrewLiveDictation`) is a Hebrew-first Windows dictation
app. You focus any text field, press a hotkey (default **F8**), speak Hebrew, press
the hotkey again, and the **final** transcript is written once into the active
window.

This branch (`feature/winui-redesign-migration`) is the current product: a **WinUI 3
shell** plus a **Python engine sidecar**. The two communicate over a per-launch
named-pipe JSON-RPC bridge. The engine owns audio, speech-to-text, insertion,
config, and history; the shell owns the rooms, overlays, tray, and diagnostics.

> **Status: unsigned manual-test build. Not a public beta, not a release.**
> The only intended test artifact is the GitHub Actions artifact
> **`VoiceType-winui-beta-unsigned`** (workflow `.github/workflows/winui-beta.yml`).
> It is unsigned — Windows SmartScreen will warn on first launch
> (*More info → Run anyway*). Public-beta and release approval are separate gates
> that have **not** been granted. See `docs/final-independent-review-package.md`.

## What the product does today

- **Final-only insertion by default.** Live/interim words are shown in VoiceType's
  own HUD and floating Remote; the target app receives the committed final once,
  after you stop. True IME-style live composition in the target is **not** part of
  the stable path (see *Labs*, below).
- **Six rooms:** Home, Dictation, Engine, Controls, History, Settings, plus a
  first-run onboarding flow.
- **Hebrew-first UI**, RTL throughout, with spoken-punctuation and editing command
  packs.

## Engines (honest status)

| Engine | What it is | Status |
| --- | --- | --- |
| **Offline (Whisper)** | Local `faster-whisper`. Private, works without internet **after** you download a model. | Recommended for this beta. Offline is **not "ready"** until a model is downloaded in the Engine room. |
| **Google STT V2** | Cloud. The regression-protected combo is `latest_long / eu / iw-IL / recognizer _`. | Requires your Google Cloud project + credentials. **Test Connection verifies the recognizer path — it is not proof of dictation.** A model/region/language/recognizer combo is only "proven" once a real streaming session (or `tools/google_stt_probe.py`) returns non-empty Hebrew text. |
| **Deepgram** | Cloud, live streaming. | Requires **your** Deepgram API key (stored in Windows Credential Manager) and Test Connection. Real transcription is unproven without a user key. |
| **Groq** | Cloud, final-only Whisper batch. | Requires **your** Groq API key and Test Connection. Final-only (no live words). Real transcription is unproven without a user key. |
| **Smart Auto / AutoFallback** | Picks a configured provider; can fall back to Offline. | Experimental; **not** the public-beta default. Offline backup is only available when a local model is installed. |

Cloud keys are stored in the OS keyring (Windows Credential Manager), never in
plaintext settings. Changing a provider's model/language/key returns its status to
"not verified" and routes dictation to Offline until you re-test.

## Labs / not in the stable path

- **Labs live insert (append)** — an **opt-in** Labs mode (off by default) that inserts each
  *completed segment* into the target **during** dictation instead of only after Stop. It is
  append-only via the safe commit path (no interim backspacing) and is **not** true
  word-by-word typing — offline inserts **per segment** (after each pause); cloud providers
  insert each streamed final. Final-only stays the stable default. Enable it in
  Settings → Advanced with the warning shown there.
- **Live target typing into other apps (interim rewrite)** — locked in the WinUI build (the
  Settings toggle is disabled; the engine force-normalizes to final-only). This is the
  experimental backspace/retype path; it requires a TSF/IME composition layer to be safe in
  RTL fields.
- **TSF/IME composition transport** — gated off.
- **Unattended auto-update install** — the updater only checks a signed manifest and
  offers a verified release URL; installation stays manual. See `docs/updater.md`.

## Requirements

- Windows 10 19041+ / Windows 11, x64.
- For building the shell: .NET 9 SDK + the Windows App SDK / WinUI 3 workload.
- For the engine: Python 3.11+ (a packaged engine is produced by the build; you do
  not need Python to run the CI artifact).

## Run it (testers)

1. Download and unzip the **`VoiceType-winui-beta-unsigned`** artifact from the
   GitHub Actions run into a clean folder.
2. Run `VoiceType.exe` (accept the SmartScreen warning — the build is unsigned).
3. Complete or skip onboarding. If you skip, install an Offline model in the Engine
   room before dictating — a fresh machine has no model yet.
4. Follow `docs/winui-beta-test-checklist.md` and record **PASS / FAIL / SKIP**
   honestly.

## Build from source (developers)

```powershell
# Python engine deps
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements.txt

# Build the WinUI shell (Release)
dotnet build winui\VoiceType.App\VoiceType.App.csproj -c Release

# Runtime self-test of the shell
& 'winui\VoiceType.App\bin\Release\net9.0-windows10.0.19041.0\win-x64\VoiceType.exe' --selftest
```

The packaged engine + shell artifact is produced by the `winui-beta` GitHub Actions
workflow (PyInstaller for the engine, `dotnet publish` for the shell).

> **Legacy note.** A previous PySide/Qt app still exists in the tree (`main.py`,
> `src/hebrew_live_dictation/qt_app.py`) as historical source evidence. It is **not**
> the current product and `python main.py` does **not** launch VoiceType. Use the
> WinUI shell described above.

## Tests and audits

```powershell
$env:PYTHONPATH='src'
.venv\Scripts\python.exe -m unittest discover -s tests
.venv\Scripts\python.exe scripts\packaging_audit.py
.venv\Scripts\python.exe scripts\release_audit.py
```

## Privacy

- Cloud API keys live in the OS keyring, never in `settings.json`.
- Credential paths and provider/API tokens are redacted from logs, error messages,
  and diagnostics.
- Transcript text is redacted in logs unless debug transcript logging is explicitly
  enabled.
- History is local-only and can be disabled or cleared in the app.

## More documentation

- [Architecture](docs/architecture.md)
- [Final product completion ledger](docs/final-product-completion-plan.md)
- [Independent review package](docs/final-independent-review-package.md)
- [Manual beta test checklist](docs/winui-beta-test-checklist.md)
- [Updater guide](docs/updater.md)
- [Pause/resume note](docs/future_pause_resume.md)
