# QA and Release Gates

> **WinUI shell:** the build, packaging, and shell-side runtime gates have moved to
> [winui-release-qa.md](winui-release-qa.md). The "Release Gate" and "Build Smoke Test"
> sections below describe the legacy PySide/PyInstaller flow (`build_app.ps1`,
> `dist\HebrewLiveDictation.exe`) and do not apply to the WinUI two-process build. The
> engine test areas and manual injection matrix here remain valid.

## Automated Tests

Run from the repository root:

```powershell
python -m unittest discover -s tests
python scripts\release_audit.py
```

Core coverage areas:

- Config migration to schema v4.
- Google V2-only normalization.
- Speech frame defaults, endpointing settings, and automatic-stop default.
- Hebrew and English command packs.
- Removal of unsupported select commands.
- Text dedupe and sentence accumulation.
- Optional local VAD behavior.
- STT chunk bounding, voice activity settings, and optional silence timeout.
- Duplicate-final prevention.
- Redacted logging.

## Manual QA Matrix

For each target, place the cursor in a real input field, start dictation with the hotkey, dictate Hebrew text, use at least one punctuation command, stop, and verify that final text is committed once.

| Target | Required checks |
| --- | --- |
| Notepad | Hebrew RTL text, punctuation, delete last word, undo |
| Microsoft Word | Word insertion path, Hebrew/English mixed text, paragraph break |
| Chrome/Gmail textarea | final-only commit, send command only when appropriate |
| WhatsApp Web or Telegram Web | message text, emoji phrase, send command |
| VS Code/Electron | focus handling, no app window self-injection |
| Search/input fields | short phrase, next field/tab |
| Mixed RTL text | Hebrew + English + numbers, no duplicated finals |

Also test one microphone that exposes a Windows default sample rate other than 16 kHz, and confirm the app starts recording without `Invalid sample rate`.

## UI QA

Verify:

- Hebrew and English UI.
- Light and dark theme.
- 100% and 150% DPI.
- Multi-monitor overlay placement.
- Overlay does not steal focus.
- Tray show/hide/start/stop/exit.
- First-run onboarding.
- Missing credentials error.
- ADC missing error.
- Engine room shows the exact runtime provider/model/location/language/recognizer/auth tuple.
- Google status distinguishes connection verified from real dictation proven.
- Live words are display-only unless a Labs target-typing gate is explicitly enabled.

## Release Gate

Before publishing a beta archive:

1. Start from a clean checkout or a copy without local runtime artifacts.
2. Confirm only `settings.example.json` is included, never `settings.json`.
3. Confirm logs are not included.
4. Run `python -m unittest discover -s tests`.
5. Run `python scripts\release_audit.py`.
6. Install dependencies into a fresh environment.
7. Run `.\build_app.ps1`.
8. Launch `dist\HebrewLiveDictation\HebrewLiveDictation.exe`.
9. Complete a smoke test in Notepad and Chrome.
10. Mark the release notes as unsigned beta unless a code-signing certificate is used.

## Build Smoke Test

Expected:

- App launches without console.
- `%APPDATA%\VoiceType\settings.json` is created on first run.
- `%APPDATA%\VoiceType\hebrew_live_dictation.log` is created.
- No credential path is written in full to the log.
- Google settings page accepts `service_account_json` or `adc`.
- Dictation starts only after Google config and microphone are usable.

## Known v1 Limitations

- No TSF/IME composition layer.
- External live interim typing is experimental; final-only remains the recommended default.
- Session-scoped editing only; arbitrary editing outside the current dictation session depends on target app behavior.
- Recognition quality depends on the selected provider, microphone quality, network latency, project entitlements,
  and the exact language/model/location/recognizer combination.

## v2 TSF Spike Gate

Before any TSF/IME behavior can become user-visible outside an experimental build, complete the spike defined in [v2 TSF Risk Plan](v2_tsf_risk_plan.md).

Required checks:

- TSF/native load does not affect v1 startup, final-only dictation, tray, overlay, or shutdown.
- Native build completes from a Visual Studio Developer PowerShell using `native\tsf_hello_peer\build_local.ps1`.
- Native outputs include both `VoiceTypeTsfHelloPeer.exe` and `VoiceTypeTsfTextService.dll`.
- `VoiceTypeTsfHelloPeer.exe --register-tsf` is a dry run and reports `changed_system_state=false`.
- Explicit register and unregister are tested as a pair on a disposable development machine.
- No language profile is made default and the Windows language bar is not changed automatically.
- IPC handshake succeeds or fails within 50-150 ms and falls back to v1 final-only on failure.
- Protected targets that reject IPC are marked `tsf_unavailable` without retries that freeze the app.
- Focus loss, `EndComposition`, target change, and late Google final events do not commit text to the wrong target.
- Advanced editing commands operate only inside verified session scope and become no-ops when scope is ambiguous.
- `ActiveWorkerCount`, `ActiveThreadMgrActivations`, and `ActiveFocusAssociations` return to zero after deactivate/unregister smoke tests.
- update/commit composition work is tested only after the registration/focus isolation gates above pass.

Compatibility matrix:

| Target | Required v2 spike checks |
| --- | --- |
| Notepad | TSF load, handshake, focus loss, fallback |
| Microsoft Word | TSF/Word backend selection, range verification, fallback |
| Chrome/Gmail | sandbox behavior, IPC failure handling, no wrong-target commit |
| WhatsApp Web or Telegram Web | send boundary closes editable scope |
| VS Code/Electron | target identity changes, no stale composition |
| UWP/Store app | AppContainer fallback, no blocking IPC |

Promotion blockers:

- Any duplicate final text.
- Any text committed after target mismatch.
- Any command that edits outside verified session scope.
- Any focus theft or app freeze during IPC.
- Any regression in v1 final-only mode.
