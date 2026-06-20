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

Currently **247 tests** across 31 files. Beyond the engine coverage listed in
[qa.md](qa.md), the WinUI seam adds:

- `test_bridge_server.py`, `test_sidecar_lifecycle.py`, `test_sidecar_callbacks.py`,
  `test_sidecar_health.py` — the named-pipe server, the sidecar adapter, the status/target/
  fallback/target-changed callbacks, health, microphone enumeration/normalization, history.

The adapter rule holds: no engine module is modified; the sidecar only wraps them.

### 2. Shell runtime self-test

```powershell
VoiceType.exe --selftest    # writes winui/winui_runtime_report.txt ; "result: N/N passed"
```

Currently **34 checks**. This is the WinUI-side parity gate; it maps onto the §13 migration
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
- **Onboarding:** finish AND skip/X both leave a working offline product; first-run flag set
  only once; a failed save shows feedback and never advances.
- **Tray:** show / start / stop / exit; hide-to-tray vs exit honors the Settings choice.

## Packaging status — NOT yet shippable

The shell builds self-contained (`SelfContained=true`, `win-x64`), **but the engine launch
is dev-only**: `RepoPaths` locates the `src/`+`winui/` repo tree and spawns a `.venv` or
system `python -m hebrew_live_dictation.bridge`. A shipped machine has none of that. Closing
this is the remaining work and is gated on decisions in [§17 of the master plan] — see
"Open packaging decisions" below.

Already in place (reusable, from the prior app): a signed-manifest updater
(`updater.py`, `docs/updater.md`) with `test_updater.py`, `test_sign_release.py`,
`test_verify.py`. The two-artifact model needs the updater extended to update **both** the
shell and the engine atomically.

### Open packaging decisions (block the installer)

1. **Engine bundling** — PyInstaller a standalone `engine.exe` (no Python on target) vs an
   embedded CPython + `src/` vs requiring system Python. Drives `RepoPaths` and installer.
2. **Offline model** — bundle a small Whisper model so the onboarding offline-first default
   truly works out-of-box (bigger installer) vs download-on-first-use vs none.
3. **Package format** — unpackaged self-contained (plan assumption, full Win32 freedom) vs
   MSIX.
4. **Code signing** — sign both artifacts with a real cert now vs ship an unsigned beta.

Until #1 is chosen, `RepoPaths.SidecarStartInfo` must gain a packaged path (locate the
bundled engine next to `VoiceType.exe`) alongside the existing dev path.
