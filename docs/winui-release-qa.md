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

Currently **267 tests** across 31 files. Beyond the engine coverage listed in
[qa.md](qa.md), the WinUI seam adds:

- `test_bridge_server.py`, `test_sidecar_lifecycle.py`, `test_sidecar_callbacks.py`,
  `test_sidecar_health.py` — the named-pipe server, the sidecar adapter, the status/target/
  fallback/target-changed callbacks, health, microphone enumeration/normalization, history.

The adapter rule holds: no engine module is modified; the sidecar only wraps them.

### 2. Shell runtime self-test

```powershell
VoiceType.exe --selftest    # writes winui/winui_runtime_report.txt ; "result: N/N passed"
```

Currently **39 checks**. This is the WinUI-side parity gate; it maps onto the §13 migration
risk register:

| Self-test checks | §13 risk verified |
| --- | --- |
| `bridge.spawn/connect/ping/getStatus/event.stream/client/disconnect` | #1,#10,#11 IPC seam replaces AppBridge; clean reconnect |
| `engine.launch.mode` | #16 packaging — the shell launches the bundled `engine.exe` when packaged, else the dev `python -m` fallback. With `--expect-packaged-engine` it is a **forced** hard packaged gate (missing/broken engine.exe or a python fallback fails) |
| `engine.insertion.deps` | #8,#16 the engine can import ALL dynamic insertion backends — `comtypes` + `comtypes.client` (Word COM) + `uiautomation` (UIA). `comtypes.client` is required separately because a freeze can bundle the base package but miss that submodule, leaving the Word backend dead while the proof "passes" |
| `bridge.settings.boundary`, `bridge.engine.config` | #11 engine is the single config writer (round-trip) |
| `bridge.getCommands/getTranscripts/listMicrophones/clearHistory.guard` | #9,#12 mic + history + commands over IPC |
| `focus.no_steal`, `hud.surface.no_steal` | **#7 focus-safety — the highest-priority invariant** |
| `hud.style.noactivate/clickthrough`, `hud.surface.noactivate`, `remote.style.noactivate`, `remote.not.clickthrough` | #5,#6 no-activate / click-through interop windows |
| `dpi.permonitor`, `monitors.enumerate` | #13,#14 multi-monitor + per-monitor DPI |
| `tray.shell_notifyicon/health_icon/instance` | #3 tray (no native WinUI tray) |
| `hud.starts_hidden/surface.states/words.preserved` | overlay lifecycle + state morphing |
| `hud.target.reassurance/safe_state/changed`, `hud.fallback.notice` | §10 state model surfaced honestly from real engine signals |
| `onboarding.navigation/engine_map/flag_after_baseline` | §6 first-run wizard: nav, offline-safe engine map, flag ordering |
| `bridge.getModelStatus`, `onboarding.offline_readiness`, `engine.model_management` | honest offline-model readiness + download/delete management |

#### Dev vs packaged-layout self-test

The same `--selftest` binary runs in both layouts. The **dev** run self-adapts (its expectation is
the layout-derived `EngineLaunchMode()`); the **packaged** run passes `--expect-packaged-engine`,
which **forces** the expectation to `packaged` so it does NOT self-adapt — a missing/broken
`engine.exe` (which would make `EngineLaunchMode()` read `dev`) or any python fallback fails hard.

First build the self-contained shell (defines `$out`, the packaged output dir these commands use):

```powershell
dotnet build winui\VoiceType.App\VoiceType.App.csproj -p:Platform=x64
$out = "winui\VoiceType.App\bin\x64\Debug\net9.0-windows10.0.19041.0\win-x64"
```

**Dev (python -m fallback)** — run from `$out` with no `engine\` folder present:

```powershell
& "$out\VoiceType.exe" --selftest          # engine.launch.mode -> expected=dev, spawned='python'
Get-Content winui\winui_runtime_report.txt | Select-Object -First 3
```

**Packaged layout (bundled engine.exe)** — freeze the engine, stage it next to `VoiceType.exe`
as an `engine\` subfolder, then run with the explicit packaged expectation:

```powershell
$out = "winui\VoiceType.App\bin\x64\Debug\net9.0-windows10.0.19041.0\win-x64"
powershell -File packaging\build_engine.ps1 -StageInto $out   # builds dist\engine, copies -> $out\engine
& "$out\VoiceType.exe" --selftest --expect-packaged-engine    # FAILS if engine.exe missing or python used
Get-Content winui\winui_runtime_report.txt | Select-Object -First 3
```

The bundled engine lives at `$out\engine\engine.exe` (the path `RepoPaths.PackagedEnginePath()`
resolves). Both runs must report `result: 39/39 passed`. To prove the packaged gate really is hard:
delete `$out\engine\engine.exe` and re-run the packaged command — it must drop below 39/39
(`engine.launch.mode` fails: `expected=packaged, spawned='python'`).

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
  offline engine selected), but offline **dictation** requires the Whisper model — which must
  be **installed via the explicit download flow** (the onboarding card or the Engine room). It
  is **never silently auto-downloaded on first use** (Option A): starting offline dictation
  without an installed model is **refused** with a clear message that routes the user to the
  download flow. The wizard never claims offline is ready before the model is present.
  First-run flag set only once; a failed save shows feedback and never advances.
- **Tray:** show / start / stop / exit; hide-to-tray vs exit honors the Settings choice.

## Packaging status — in progress (not yet a release)

The shell builds self-contained (`SelfContained=true`, `win-x64`). The engine launch is **no
longer dev-only**: `RepoPaths` spawns a bundled, frozen `engine\engine.exe` when present (the
shipped path), and falls back to the dev `python -m hebrew_live_dictation.bridge` only on a repo
tree. The frozen engine is built by `packaging\engine.spec` / `packaging\build_engine.ps1`, and
the packaged launch is gated by the `--expect-packaged-engine` self-test above.

What remains before a beta: ~~assemble the two-artifact package~~ (done — see "Local unsigned beta
layout" below), ~~make that artifact reproducible via GitHub Actions~~ (workflow added — see
"Reproducible beta in CI" below; **a real Actions run is still pending**), wire GitHub Release
attachment (prepared, tag-gated, dormant), and run the real-hardware focus-safety matrix on the
packaged build. The local PyInstaller/publish proof on a dev machine is **not** the release — the
shippable artifact must come from CI.

### Local unsigned beta layout (P3 — proof of package shape, NOT a release)

`packaging\build_beta.ps1` assembles a self-contained, unpackaged folder a user can run with
**no repo, no Python, no dev environment**:

```powershell
powershell -File packaging\build_beta.ps1          # -> dist\beta\VoiceType-beta
```

It (1) `dotnet publish`es the shell self-contained + `WindowsAppSDKSelfContained=true` (bundles
the .NET runtime AND the Windows App Runtime), (2) freezes the engine (`build_engine.ps1`), and
(3) assembles `dist\beta\VoiceType-beta\` = `VoiceType.exe` + all runtime DLLs + `engine\engine.exe`
+ `READ-ME-BETA.txt`.

- **Output:** `dist\beta\VoiceType-beta\` (gitignored).
- **Size:** ~544 MB on disk. Heavy contributors: the frozen engine (~374 MB — PySide6 + faster-whisper
  + ctranslate2 + grpc), and the self-contained .NET + Windows App Runtime in the shell (~150 MB+).
- **Contents (top level):** `VoiceType.exe`, `VoiceType.dll`, `VoiceType.pri` (see PRI note), the
  .NET + WinAppSDK runtime DLLs, `Microsoft.UI*.pri`, the WinAppSDK locale folders (`en-us\`, `he-IL\`,
  … one per language), `Microsoft.UI.Xaml\`, `NpuDetect\`, `engine\` (engine.exe + `_internal\`), and
  `READ-ME-BETA.txt`. (There is no top-level `resources\` folder.)
- **Run:** double-click `VoiceType.exe`, or from a terminal.
- **Verify (automated, must pass):**
  ```powershell
  powershell -File packaging\verify_beta.ps1     # copies the beta OUT-OF-REPO, runs positive + negative
  ```
  `verify_beta.ps1` copies the layout to `%TEMP%\vt-beta-verify` (so `RepoPaths` can't find the repo
  and no dev fallback is possible), then runs the **positive** packaged self-test and the **negative**
  (engine.exe renamed away) hard-gate check, asserting both. Equivalent manual commands:
  ```powershell
  & "<out-of-repo-copy>\VoiceType.exe" --selftest --expect-packaged-engine   # positive: result: 39/39 passed
  # rename engine\engine.exe away, re-run -> engine.launch.mode FAILS (expected=packaged, spawned='python')
  ```
- **Self-test report path:** the report is written **inside the package** at
  `<package>\winui_runtime_report.txt` (packaged layout has no `winui\` subfolder). In a dev repo tree
  it stays at `<repo>\winui\winui_runtime_report.txt`. The chosen path is also echoed in the report's
  `report:` header line, and a write failure is surfaced (TEMP fallback + a `SELFTEST-REPORT-WRITE-FAILED.txt`
  breadcrumb next to the exe), never silently swallowed.

**PRI note (real defect this layout caught):** `dotnet publish` for unpackaged WinUI drops the app's
own compiled resource index `VoiceType.pri` from the publish folder. Without it, every page/window
throws `XamlParseException 0x802B000A` and the UI never renders (the engine still runs, so it is easy
to miss). `build_beta.ps1` recovers `VoiceType.pri` from the build output into the publish folder; the
packaged self-test's `onboarding.*` / `engine.model_management` checks (which construct real XAML)
guard against a regression.

**SmartScreen / unknown publisher (must be in release notes):** these binaries are **unsigned**.
Windows SmartScreen shows an "unknown publisher" / "Windows protected your PC" warning, and some AV
may flag the unsigned `.exe`. Users proceed via *More info → Run anyway*. This is a **beta**, not a
signed release; signing is a later phase. `READ-ME-BETA.txt` states this in-package.

Already in place (reusable, from the prior app): a signed-manifest updater
(`updater.py`, `docs/updater.md`) with `test_updater.py`, `test_sign_release.py`,
`test_verify.py`. The two-artifact model needs the updater extended to update **both** the
shell and the engine atomically.

### Reproducible beta in CI (P4 — GitHub Actions artifact)

The same beta layout is reproduced in CI by **`.github/workflows/winui-beta.yml`** (separate from
the legacy `build-release.yml`, which is the old Qt app on `main` + `v*` tags — untouched).

- **Triggers:** `workflow_dispatch` (manual), `push` to `feature/winui-redesign-migration`, and
  `push` of a `beta-v*` tag. It cannot fire the legacy pipeline (`beta-v*` does not match `v*`).
- **`build-beta` job (`windows-latest`):** Python 3.12 + .NET 9 → `pip install -r requirements.txt`
  (this also pulls `comtypes`, a transitive dep of `uiautomation`, so the freeze's insertion deps are
  present) → **Python unit tests** → **`packaging\build_beta.ps1`** (publishes the self-contained
  shell, recovers `VoiceType.pri`, freezes `engine.exe`, assembles `dist\beta\VoiceType-beta`; CI has
  no `.venv`, so `build_engine.ps1` falls back to the runner's `python`) → **`packaging\verify_beta.ps1`**
  (out-of-repo positive `--selftest --expect-packaged-engine` + negative engine-rename hard-gate) →
  upload artifacts.
- **Artifacts:** **`VoiceType-winui-beta-unsigned`** = the full `dist\beta\VoiceType-beta` package
  (~544 MB), and **`winui-beta-selftest-report`** = the package-root `winui_runtime_report.txt`
  (uploaded with `if: always()` so a failed verify is still inspectable). Retention 14 days.
- **GitHub Release (prepared, dormant):** the tag-gated **`prerelease`** job runs only on a `beta-v*`
  tag; it zips the package and `gh release create … --prerelease` (unsigned). It is wired but has
  **not** been exercised — pushing the first `beta-v*` tag is what proves it.
- **CI caveat (needs a real run to confirm green):** `verify_beta.ps1` launches the WinUI GUI in
  `--selftest` mode, which constructs real XAML windows. Whether a GitHub-hosted `windows-latest`
  session can create those windows headlessly is unverified until the first actual Actions run. If it
  cannot, that step is where it will surface (the package + report still upload via `if: always()`),
  and the verify step would move to `continue-on-error` with the GUI gate run on self-hosted/interactive
  hardware instead. Everything up to and including `build_beta.ps1` is runner-safe.
- **Still UNSIGNED:** the CI artifact carries the same SmartScreen "unknown publisher" limitation as the
  local layout; CI does not sign. Signing is a later phase.

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

**Option A — explicit acquisition only.** Offline model acquisition goes through the explicit
`downloadModel` flow exclusively. faster-whisper's first-use auto-download is **not** a
readiness path: such a cache has no completion marker and is reported not-ready. The hole is
closed at **two** layers so *every* effective-Whisper path is covered:

1. **Start boundary (best UX).** When offline is the *live* engine but no model is installed,
   the sidecar **refuses** to start (`hotkey_start` / `startDictation` / idle `toggleDictation`)
   and emits a `status` with `state:"error"` + `needsModel:true`. "Live engine" is the effective
   provider, not just the literal config: mode `local` or provider `whisper_local` (with Whisper
   enabled), **and** `smart_auto` when it resolves to `whisper_local` (the sidecar runs the same
   `stt.auto_select.select_provider` the factory uses). The shell brings the console forward and
   routes to the Engine room's download card.
2. **`WhisperLocalStream` load boundary (universal safety net).** Before loading, the offline
   provider checks `is_downloaded` and, if absent, emits a clear `error` instead of letting
   `WhisperModel(...)` auto-download. This is the single choke point every Whisper path flows
   through — crucially the **`auto_fallback` mid-session switch to local**, which the start
   boundary cannot pre-empt (cloud is primary there). The sidecar tags that error `needsModel`
   so the shell routes to download even when it surfaces mid-session.

Together these keep honest UI state, progress/error/retry handling, a real completion marker,
and consistent `getModelStatus` / `compute_health` — with no hidden "usable but not installed"
state and no implicit download anywhere. `deleteModel` is refused while a download is in flight.
