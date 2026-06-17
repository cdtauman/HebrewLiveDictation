# Hebrew Live Dictation v1 Beta

Hebrew Live Dictation is a Hebrew-first Windows dictation app that brings the closest practical Google Gboard-style dictation workflow to Windows without pretending to be Android Gboard.

v1 Beta is intentionally conservative: it uses Google Speech-to-Text V2 with Chirp 3, keeps live interim text in the app/overlay, and commits only final text into the active Windows application. True Gboard-level live composition requires a Windows TSF/IME layer and is planned separately for v2.

## What Is Supported

- Modern PySide6 Windows UI with onboarding, settings, overlay, and tray controls.
- Google Speech-to-Text V2 only.
- Stable default model id: `chirp_3`.
- Stable default region: `eu`; fallback region: `us`.
- Advanced speech mode for additional Google V2 model and region presets, with compatibility warnings.
- Primary Hebrew locale: `iw-IL`.
- `LINEAR16`, mono, `16 kHz`, `100 ms` audio frames.
- Microphones that do not support 16 kHz directly are opened at their Windows default sample rate and resampled to 16 kHz for Google.
- Google voice activity events when available; automatic stop after silence is optional and off by default.
- Optional local VAD with pre-roll and speech padding.
- Final-only external text insertion by default.
- Experimental live interim typing for users who prefer text while speaking and accept weaker RTL stability.
- Hebrew spoken punctuation and emoji phrases through local command packs.
- Session commands: delete last word, delete last sentence, clear, undo, send, next field, replace phrase, delete phrase, stop.
- Runtime settings and logs under `%APPDATA%\VoiceType`.
- Redacted logs by default; transcript content is logged only when debug transcript logging is explicitly enabled.
- Dictation stays active until the user presses stop by default. Users can enable automatic stop after silence in Audio settings.

## What Is Not Supported in v1

- Full Android Gboard or Pixel advanced voice typing parity.
- Stable TSF/IME composition-string behavior.
- Reliable arbitrary phrase selection across all Windows apps.
- Google Speech-to-Text V1.
- Untested model/language/region combinations outside Advanced mode.

## Models and Languages

The stable default remains Google Speech-to-Text V2 `chirp_3`, Hebrew `iw-IL`, and `eu/us` regions. Advanced mode exposes additional V2 model and region presets for local validation, but each language/model/region combination must be tested before release use.

The language dropdown contains tested presets. For any Google-supported BCP-47 language code that is not in the dropdown, use the custom language code field. Before a language becomes a first-class preset, it should get command-pack and QA coverage.

## Install for Development

Python 3.11+ is recommended.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements.txt
```

## Run

```powershell
python main.py
```

The app creates local settings at:

```text
%APPDATA%\VoiceType\settings.json
```

The repository includes `settings.example.json` only. Do not commit personal settings or credentials.

## Google Cloud Setup

1. Create or choose a Google Cloud project.
2. Enable Speech-to-Text API.
3. Create a service account with Speech-to-Text permissions, or configure Application Default Credentials.
4. In the app, set:
   - Project ID: your Google Cloud project id.
   - Location: `eu`.
   - Recognizer ID: `_`.
   - Model: `chirp_3`.
   - Credentials mode: `service_account_json` or `adc`.
5. If using service account JSON, choose the JSON file in the UI. The path is stored only in `%APPDATA%\VoiceType\settings.json`.

The app does not use simple API keys.

## Voice Commands

Supported command groups:

- Punctuation: period, comma, question mark, exclamation mark, colon, semicolon, new line, new paragraph.
- Emoji phrases: smile, heart, laugh, fire, check.
- Editing/navigation: delete last word, delete last sentence, clear all, undo, send, next field.
- Session phrase edits: replace phrase and delete phrase inside the current dictation session.
- v2 TSF path: select last word/sentence is available only when a verified TSF composition scope is active.
- Stop dictation.

Unsupported commands such as arbitrary phrase selection are intentionally not exposed in v1.

## Build

```powershell
.\build_app.ps1
```

Output:

```text
dist\HebrewLiveDictation
```

If the build is not code-signed, publish it as an unsigned beta.
If Visual Studio CMake tools are installed, the build also compiles and packages the v2 Native TSF peer and DLL under `native\tsf`.

## Test and Release Gate

```powershell
python -m unittest discover -s tests
python scripts\release_audit.py
```

Before publishing, verify a fresh build in Notepad, Word, Chrome/Gmail textarea, WhatsApp Web or Telegram Web, VS Code/Electron, and short search/input fields. Include mixed Hebrew-English-number text and 100%/150% DPI checks.

More detail:

- [Architecture](docs/architecture.md)
- [QA Matrix](docs/qa.md)
- [v2 TSF Risk Plan](docs/v2_tsf_risk_plan.md)

## Privacy

- Credentials paths are redacted in logs.
- Transcript text is redacted unless debug transcript logging is enabled.
- Logs rotate under `%APPDATA%\VoiceType`.
- The release audit blocks local settings, logs, bytecode caches, legacy files, and common secret patterns.

## Troubleshooting

- Missing credentials: choose a Service Account JSON file or configure ADC with `gcloud auth application-default login`.
- No recognition responses: check project id, Speech-to-Text API status, region, model, recognizer id, microphone, and network access.
- Text appears in the wrong app: click the target input field before starting dictation.
- Duplicated text: switch back to final-only mode and verify tests pass.
- Poor recognition: use a better microphone, reduce background noise, and add custom phrases.

## Sources Checked

- [Gboard advanced voice typing](https://support.google.com/gboard/answer/11197787)
- [Google Cloud Chirp 3](https://docs.cloud.google.com/speech-to-text/docs/models/chirp-3)
- [Google STT best practices](https://docs.cloud.google.com/speech-to-text/docs/best-practices)
- [Google STT quotas and streaming limits](https://docs.cloud.google.com/speech-to-text/docs/quotas)
- [Google STT voice activity events](https://docs.cloud.google.com/speech-to-text/docs/voice-activity-events)
- [Microsoft Text Services Framework](https://learn.microsoft.com/en-us/windows/win32/tsf/text-services-framework)
- [Microsoft extended window styles](https://learn.microsoft.com/en-us/windows/win32/winmsg/extended-window-styles)
