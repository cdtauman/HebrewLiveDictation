# WinUI Release QA & Packaging Readiness

This supersedes the build/release sections of [qa.md](qa.md) for the WinUI shell. The
Python engine and its own gates (config migration, STT providers, text injection, updater,
release signing) are unchanged and still covered by [qa.md](qa.md) and the Python suite.

The product now ships as **two processes**: the WinUI 3 shell (`VoiceType.exe`) and the
headless Python engine sidecar, connected over a per-launch named-pipe JSON-RPC seam. QA
must therefore cover the seam and the shell-side native surfaces, not only the engine.

## Automated gates

Both must be green before any release build.

### 1. Engine suite (the durable asset)

```powershell
$env:PYTHONPATH="src"; python -m unittest discover -s tests -t . -p "test_*.py"
```

Currently **255 tests** across 31 files. Beyond the engine coverage listed in
[qa.md](qa.md), the WinUI seam adds:

- `test_bridge_server.py`, `test_sidecar_lifecycle.py`, `test_sidecar_callbacks.py`,
  `test_sidecar_health.py` — the named-pipe server, the sidecar adapter, the status/target/
  fallback/target-changed callbacks, health, microphone enumeration/normalization, history.

The adapter rule holds: no engine module is modified; the sidecar only wraps them.

### 2. Shell runtime self-test

```powershell
VoiceType.exe --selftest    # writes winui/winui_runtime_report.txt ; "result: N/N passed"
```

Currently **36 checks**. This is the WinUI-side parity gate; it maps onto the §13 migration
risk register:

| Self-test checks | §13 risk verified |
| --- | --- |
| `bridge.spawn/connect/ping/getStatus/event.stream/client/disconnect` | #1,#10,#11 IPC seam replaces AppBridge; clean reconnect |
| `bridge.settings.boundary`, `bridge.engine.config` | #11 engine is the single config writer (round-trip) |
| `bridge.getCommands/getTranscripts/listMicrophones/clearHistory.guard` | #9,#12 mic + history + commands over IPC |
| `focus.no_steal`, `hud.surface.no_steal` | **#7 focus-safety — the highest-priority invariant** |
| `hud.style.noactivate/clickthrough`, `hud.surface.noactivate`, `remote.style.noactivate`, `remote.not.clickthrough` | #5,#6 no-activate / click-through interop windows |
| `dpi.permonitor`, `monitors.enumerate` | #13,#14 multi-monitor + per-monitor DPI |
| `tray.shell_notifyicon/health_icon/instance` | #3 tray (no native WinUI tray) |
| `hud.starts_hidden/surface.states/words.preserved` | overlay lifecycle + state morphing |
| `hud.target.reassurance/safe_state/changed`, `hud.fallback.notice` | §10 state model surfaced honestly from real engine signals |
| `onboarding.navigation/engine_map/flag_after_baseline` | §6 first-run wizard: nav, offline-safe engine map, flag ordering |

## Manual QA (cannot be automated)

The focus-safety gate (§16) is the release blocker. For each target: place the cursor in a
real field, trigger with the hotkey, dictate Hebrew, use a punctuation command, stop, and
confirm the text lands **once** and that the shell/HUD/Remote **never** take foreground.

| Target | Checks |
| --- | --- |
| Notepad | Hebrew RTL, punctuation, no self-injection |
| Microsoft Word | COM insertion path, mixed he/en, paragraph break |
| Chrome / Gmail | UIA path, final-only commit, send only when intended |
| WhatsApp / Telegram desktop | message text, emoji phrase, send boundary |
| VS Code / Electron | target identity, no stale target after app switch |

Plus the shell surfaces:

- **§10 states on real hardware:** target reassurance shows the true app; unknown/unsafe →
  "יעד לא זוהה" (never a wrong claim); mid-session target detach → amber "target changed";
  `auto_fallback` drop → amber "offline backup active".
- **RTL** on every room + onboarding; mixed LTR tokens (model names) read correctly.
- **DPI/monitors:** 100% and 150%, 2+ monitors mixed scaling — HUD/Remote placement.
- **Onboarding:** finish AND skip/X both leave the app in a working *configuration* (a valid
  offline engine selected), but offline **dictation** requires the Whisper model — which is
  downloaded on first offline use or pre-fetched from the app. The wizard states this and
  never claims offline is ready before the model is present. First-run flag set only once; a
  failed save shows feedback and never advances.
- **Tray:** show / start / stop / exit; hide-to-tray vs exit honors the Settings choice.

## Packaging status — NOT yet shippable

The shell builds self-contained (`SelfContained=true`, `win-x64`), **but the engine launch
is dev-only**: `RepoPaths` locates the `src/`+`winui/` repo tree and spawns a `.venv` or
system `python -m hebrew_live_dictation.bridge`. A shipped machine has none of that. Closing
this is the remaining work.

Already in place (reusable, from the prior app): a signed-manifest updater
(`updater.py`, `docs/updater.md`) with `test_updater.py`, `test_sign_release.py`,
`test_verify.py`. The two-artifact model needs the updater extended to update **both** the
shell and the engine atomically.

### Packaging decisions (agreed)

These are settled, not open:

1. **Engine bundling — PyInstaller `engine.exe`.** The sidecar is frozen into a standalone
   executable (no Python required on the target). `RepoPaths.SidecarStartInfo` gains a
   packaged path (locate `engine.exe` next to `VoiceType.exe`) with the existing dev
   `python -m` path as fallback.
2. **Offline model — hybrid, honest.** No model is bundled blindly. During setup/first-run
   the user is offered a one-time download of a small Hebrew-capable Whisper model (default:
   yes). If they decline, offline is **not** silently promised — it is reported as not-ready
   and the model can be fetched later from the app. Readiness is the real on-disk completion
   signal (see "Honest offline readiness" below), never a config flag.
3. **Package format — unpackaged self-contained.** A conventional installer dropping
   `VoiceType.exe` + `engine.exe` + the WindowsAppRuntime; full Win32 freedom, simplest
   sidecar lifecycle, and compatible with the existing updater.
4. **Code signing — unsigned beta first.** The first packaged build ships unsigned to
   validate the end-to-end flow. **Unsigned binaries trigger a Windows SmartScreen "unknown
   publisher" warning** (and possible AV friction); release notes must say so plainly.
   Real signing is wired once a certificate is available — `test_sign_release.py` /
   `test_verify.py` infrastructure already exists.

### Honest offline readiness (authoritative completion signal)

`models.is_downloaded()` reports a model ready **only** when a matching cache dir contains
ALL of: the authoritative `COMPLETE_MARKER` (`.vt_complete`, written by `download_model` as
the last step of a successful download), a non-trivially-sized `model.bin`, AND a
config/vocabulary file the runtime needs to load it. The marker alone is **not** enough. An
empty cache, a marker without weights, a partial download (`*.incomplete` blobs only), or a
zero-byte `model.bin` all report not-ready. `getModelStatus` and `compute_health`
(offline.ready / offline.model_ready) derive from this, and `downloadModel` re-validates with
the same check after the download returns — emitting `done` only if the model is genuinely
usable, otherwise `error`. The UI never claims offline works before a model is actually,
completely present.
