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
resolves). In the positive run, `engine.launch.mode` must PASS (`expected=packaged, spawned='engine'`)
and all non-focus checks must pass (`result: 39/39` on a quiet desktop; the two focus checks are
advisory and may read 37–38/39 if another window steals foreground — see the build/focus split note
below). To prove the packaged gate really is hard: delete `$out\engine\engine.exe` and re-run — it must
drop (`engine.launch.mode` FAILS: `expected=packaged, spawned='python'`).

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
layout" below), ~~make that artifact reproducible via GitHub Actions~~ (done — two green runs, see
"Reproducible beta in CI" below), wire GitHub Release attachment (prepared, tag-gated, dormant), and
~~run the real-hardware focus-safety matrix on the packaged build~~ (in progress — see "P5 manual QA /
focus-safety matrix" below). The local PyInstaller/publish proof on a dev machine is **not** the
release — the shippable artifact must come from CI.

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
  (engine.exe renamed away) hard-gate check. It preserves **both** reports under distinct names so neither
  overwrites the other: `winui_runtime_report.positive.txt` (the positive proof) and
  `winui_runtime_report.negative.txt` (the expected hard-gate FAIL).

  **Build/artifact vs GUI-focus split (P4 review decision).** The script HARD-GATES only the deterministic,
  packaging-relevant checks (`engine.launch.mode` PASS positive / FAIL when engine.exe is missing, packaged
  layout, XAML/PRI rendering, report written). The two focus-safety checks — `focus.no_steal` and
  `hud.surface.no_steal` — are **advisory**: they fail whenever *any* unrelated window holds the foreground
  while the test runs (the report shows `fgAfter != hud`, i.e. a third window grabbed focus, not our HUD),
  which is non-deterministic on a busy desktop or a shared/headless CI runner (observed 39/37/38 across
  back-to-back runs, a different foreground thief each time). They still **run and are recorded** in the
  report; they just do not gate packaged verification. **Authoritative focus-safety is the P5 real-hardware
  focus matrix** (dictate into Word/Gmail/WhatsApp; §16). Equivalent manual commands:
  ```powershell
  & "<out-of-repo-copy>\VoiceType.exe" --selftest --expect-packaged-engine   # positive: engine.launch.mode PASS;
  #   all non-focus checks pass (result 39/39 on a quiet desktop, 37-38/39 if a window steals focus)
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
- **WinUI build on the runner needed TWO fixes (learned across the first real CI runs):**
  1. **.NET SDK pin (`.NET 9`).** WindowsAppSDK 1.7 PRI generation (`MrtCore.PriGen`) fails on the
     runner's **preinstalled .NET 10 SDK** with `MSB4062` (the `ExpandPriContent` task can't be loaded).
     `setup-dotnet` installs 9.0.x, but the highest installed SDK (10) wins unless pinned, so the workflow
     writes a **workspace-only `global.json`** (`version 9.0.100`, `rollForward: latestFeature`) before
     building — highest 9.0.x, never 10. Not committed (gitignored) so local SDK choice isn't forced.
  2. **Provision the PRI task into the SDK.** Pinning to .NET 9 was **necessary but not sufficient**: the
     task DLL `Microsoft.Build.Packaging.Pri.Tasks.dll` is a **Visual Studio MSBuild component**, absent
     from *both* the .NET 9 and .NET 10 SDKs on the runner. The runner actually has **Visual Studio 18
     Enterprise** (`C:\Program Files\Microsoft Visual Studio\18\Enterprise`, *not* VS 2022). The
     `Provision WindowsAppSDK PRI task` step uses `vswhere` to find VS, then copies its
     `…\v18.0\AppxPackage\` tasks into the SDK's `v17.0` and `v18.0` `AppxPackage` folders so
     `dotnet publish` (.NET 9) can load `ExpandPriContent`. (Local builds need neither fix — the dev
     machine's VS already supplies the task in the SDK path.) **Maintenance:** this workaround tracks the
     runner's VS layout — `vswhere` finds whichever VS is installed and its `AppxPackage` tasks are mirrored
     into the SDK's `v17.0`/`v18.0` folders; if a future runner image bumps the SDK's expected `vNN.0`
     folder, extend that target list in the step.
- **`build-beta` job (`windows-latest`):** Python 3.12 + .NET 9 (pinned) → `pip install -r requirements.txt`
  (this also pulls `comtypes`, a transitive dep of `uiautomation`, so the freeze's insertion deps are
  present) → **Python unit tests** → **`packaging\build_beta.ps1`** (publishes the self-contained
  shell, recovers `VoiceType.pri`, freezes `engine.exe`, assembles `dist\beta\VoiceType-beta`; CI has
  no `.venv`, so `build_engine.ps1` falls back to the runner's `python`) → **`packaging\verify_beta.ps1`**
  (out-of-repo positive `--selftest --expect-packaged-engine` + negative engine-rename hard-gate) →
  upload artifacts.
- **Artifacts (retention 14 days):**
  - **`VoiceType-winui-beta-unsigned`** = the full `dist\beta\VoiceType-beta` package (~544 MB).
    Uploaded with `if: always()`, so the package is preserved even if GUI verification fails.
  - **`winui-beta-selftest-reports`** = BOTH preserved self-test reports (uploaded `if: always()`):
    - `winui_runtime_report.positive.txt` — **the packaged positive proof** (`--expect-packaged-engine`,
      `engine.launch.mode` PASS, `spawned='engine'`; all non-focus checks pass). On a quiet desktop this is
      39/39; if a window steals focus during the run it may read 37–38/39 with only the advisory focus
      checks failing (see the split note below) — the hard gate still passes.
    - `winui_runtime_report.negative.txt` — **the negative hard-gate proof** (engine.exe renamed away;
      `engine.launch.mode` FAIL, `spawned='python'`). This report is *expected* to show a failing check.

    The app always writes one canonical `<package>\winui_runtime_report.txt` and each run overwrites it,
    so `verify_beta.ps1` copies it to these two distinct names after each phase. Read `.positive.txt`
    for the success proof — never the canonical/last-written file, which holds the negative run.
- **Verify-step timeout:** the verification step has `timeout-minutes: 12` so a stuck GUI self-test
  cannot burn the whole job's time budget (`verify_beta.ps1` is itself bounded — ~40s poll per run).
- **GitHub Release (prepared, dormant):** the tag-gated **`prerelease`** job runs only on a `beta-v*`
  tag; it zips the package and `gh release create … --prerelease` (unsigned). It is wired but has
  **not** been exercised — pushing the first `beta-v*` tag is what proves it.
- **Build/artifact vs GUI-focus split (decision):** packaged verification hard-gates only the
  deterministic packaging checks; the environment-sensitive focus checks are advisory and deferred to the
  P5 real-hardware focus matrix (see the split note under "Verify" above). This was decided after the focus
  checks proved non-deterministic even on a local interactive machine (39/37/38 across runs), so they
  cannot be a reliable gate on a shared/headless runner.
- **CONFIRMED green on hosted `windows-latest` (2026-06-21):** first successful run
  [27904562014](https://github.com/cdtauman/HebrewLiveDictation/actions/runs/27904562014) (commit
  `840fba9`). The hosted runner **does** build the shell (with the two fixes above) **and** runs the
  WinUI/XAML GUI self-test — the packaged verify passed: **positive 39/39** (`engine.launch.mode` PASS,
  `spawned='engine'`; the focus checks even passed on the clean runner desktop), **negative hard-gate
  25/28** (`engine.launch.mode` FAIL, `spawned='python'`), `BETA VERIFY: PASSED`. So the earlier worry
  that a hosted session might not create XAML windows is resolved — it does. Uploaded artifacts:
  `VoiceType-winui-beta-unsigned` (~222 MB zipped, ~544 MB on disk) and `winui-beta-selftest-reports`
  (both `.positive.txt` and `.negative.txt`).
- **Still UNSIGNED:** the CI artifact carries the same SmartScreen "unknown publisher" limitation as the
  local layout; CI does not sign. Signing is a later phase.

### P5 — Manual QA / focus-safety matrix (real hardware — AUTHORITATIVE)

This is the **hard real-hardware gate for focus safety**. The CI focus checks
(`focus.no_steal`, `hud.surface.no_steal`) were **advisory**; the results below are **authoritative**.
Run the matrix against the **CI artifact**, not a local rebuild.

**Artifact under test (do not rebuild):**
- Artifact: **`VoiceType-winui-beta-unsigned`**
- From green P4 run **27905256239** (commit `eb53c0b`):
  https://github.com/cdtauman/HebrewLiveDictation/actions/runs/27905256239
- Downloaded/extracted to `c:\tmp\vt-p5-artifact` (run `VoiceType.exe` from there).
- Automatable pre-check on the dev machine: the artifact **launches and self-tests 39/39**,
  `engine.launch.mode` PASS (`spawned='engine'`) — confirms the package runs before manual QA.

**Stop condition (Must-Fix):** if any target **steals focus**, **inserts text twice**, or inserts into
the **wrong place/target**, STOP and record it as a Must-Fix — do not continue to P6.

**Tested Windows environment** (fill in):
| Field | Value |
|---|---|
| Windows build | _(dev machine reference: Windows 11 Pro 10.0.26200)_ |
| Display scaling / DPI | _____ |
| Monitor setup | _____ |
| Microphone | _____ |
| Engine mode tested | _(Recommended/Google · Offline · both)_ |
| Microsoft Word version | _____ |
| Chrome version | _____ |
| WhatsApp / Telegram version | _____ |
| VS Code version | _____ |
| Tester / date | _____ |

**Per-target insertion + focus matrix** (mark PASS / FAIL / N/A):
| # | Target | Insertion path | Checks | Result | Notes |
|---|---|---|---|---|---|
| 1 | Notepad | SendInput/Unicode | Hebrew RTL renders correctly · spoken punctuation · **no self-injection** into VoiceType | ☐ | |
| 2 | Microsoft Word | COM | COM insertion path · mixed Hebrew/English · paragraph-break command | ☐ | |
| 3 | Chrome / Gmail | UIA | UIA path · **final-only** commit (no interim spam) · **send only when intended** | ☐ | |
| 4 | WhatsApp / Telegram desktop | UIA/SendInput | message text · emoji phrase · **send boundary** (no premature send) | ☐ | |
| 5 | VS Code / Electron | UIA/SendInput | correct target identity · **no stale target** after app switch | ☐ | |

**Cross-cutting focus / state / UX checks** (mark PASS / FAIL / N/A):
| # | Check | Result | Notes |
|---|---|---|---|
| A | HUD never steals focus | ☐ | |
| B | Remote never steals focus | ☐ | |
| C | Tray never steals focus | ☐ | |
| D | Target reassurance correct (`→ {app}`) | ☐ | |
| E | Unknown/unsafe target shows **"יעד לא זוהה"** | ☐ | |
| F | "Target changed" warning appears when target changes mid-session | ☐ | |
| G | auto_fallback / offline-backup notice is honest | ☐ | |
| H | RTL correct across rooms + onboarding | ☐ | |
| I | DPI / multi-monitor behavior (if available) | ☐ | |
| J | Onboarding skip / finish behavior | ☐ | |
| K | Offline model missing → download flow honest (no silent auto-download) | ☐ | |
| L | Tray show / start / stop / exit + hide-to-tray | ☐ | |

**Status (2026-06-22):**
- **P5 pre-smoke: PASS** (Notepad, via F8 and the floating Remote).
- **Full P5 matrix: DEFERRED — not fully run.** Priority shifted to Product Completion (below).
- **Known risk:** Word / Gmail / WhatsApp / VS Code insertion + focus-safety **not yet verified**.
- **Not ready for public beta on P5 alone** — the matrix is incomplete and the product is not feature-
  complete (see "Product Completion / Feature Parity").

Pre-smoke detail — after rounds 1–3 (below) the Notepad pre-smoke passes for the **supported start paths**:
- **F8 (global hotkey) → target app: PASS.**
- **Floating Remote → target app: PASS.**
- Offline engine / mic / STT / start-stop / **clipboard-paste final insertion** all working; remaining
  recognition weakness is the small offline model, not a P5 blocker.

**Supported beta dictation workflow (the matrix uses these):** focus the target app → start/stop with
**F8 or the floating Remote** → the final transcript is inserted **once** into the target → history matches
the inserted text (minus normal model mistakes) → nothing inserted into VoiceType / File Explorer / a wrong
target. **Home button and Tray are SECONDARY** (they naturally take focus when clicked) — **not** P5
blockers; a last-external-target backstop can be added later if they are ever promoted to official
dictation paths. Run every per-target row below via **F8 and the Remote** (not Home/Tray).

**Round history (blockers found and fixed before the pass):**

**Round 1 (2026-06-21) — beta blockers; core dictation unusable for the tester.** Artifact under test:
`VoiceType-winui-beta-unsigned` (run 27905256239 / `eb53c0b`) at `c:\tmp\vt-p5-artifact`.

Diagnosis evidence (read from the live machine — the packaged engine did **not** persist a log at that
point, see finding 6, so evidence is settings + model cache + crash dump + source):
- `%APPDATA%\VoiceType\settings.json` (shared with the dev/legacy app): `stt.provider=google_v2`,
  `stt.mode=api`, `google.project_id=""`, `hotkeys.hotkey="copilot"`, `providers.whisper.enabled=true`.
- `%APPDATA%\VoiceType\models\models--Systran--faster-whisper-small`: has `config.json` +
  `tokenizer.json` + `vocabulary.txt` but **no `model.bin`** and **no `.vt_complete`** → `is_downloaded()`
  = not-ready (interrupted ~480 MB weights download).
- Crash dump `%LOCALAPPDATA%\CrashDumps\VoiceType.exe.19668.dmp` (2026-06-21 00:52).

P5 Must-Fix beta blockers:
1. **Default engine is Google but Google is unconfigurable.** Fresh `stt.provider` default is `google_v2`
   with empty `project_id`; there is **no Google credential UI anywhere** (onboarding defers to the
   Engine room; the Engine room only writes `google.model`). Onboarding's finish does apply offline
   (`whisper_local`), but any user on the Google path (default config or this tester's stale config)
   cannot make it work → dictation produces no transcripts.
2. **Offline model download is not legible.** Progress is indeterminate (spinner + "מוריד…", no
   %/bytes/size) and a partial/failed download leaves the model not-ready with no clear surfaced error;
   the tester could not tell it was downloading, failing, or done.
3. **Hotkey not changeable.** Controls room shows the hotkey as read-only text — no rebind UI. F8 is the
   *default*, but this tester's stale config is `copilot`, so F8 did nothing and there was no recovery.
4. **Engine logs are not persisted in the packaged build** (`run()` uses `logging.basicConfig`, never
   `setup_logging`), so field diagnosis has no engine log to inspect.

Working as designed (not blockers): UI/Tray/Remote start-stop buttons ARE wired to `startDictation`;
text insertion + the full STT pipeline are proven by the 2026-06-17 dev-app log; packaged engine spawns
(self-test 39/39). The failure is configuration + missing config UIs, not the start trigger or insertion.

**Must-Fix resolution (2026-06-21) — fixes applied; manual re-test pending.**
1. **Honest engine choice.** The Engine room now presents **Offline (Whisper) as "מומלץ בבטא"**; selecting
   Google or "ספק ענן אחר" shows "חיבור לענן אינו זמין בגרסת הבטא" and **routes to Offline** (no dead cloud
   path). Cloud captions say credential setup isn't available in this beta. ([EnginePage.xaml] / `OnEngineChoice`)
2. **Legible offline download.** Download copy now states size + time ("~500MB — עשוי לקחת מספר דקות, דרוש
   אינטרנט, אפשר להמשיך לעבוד") and a clearer failure message; states are downloading→done/failed with retry.
   (Progress stays honest-indeterminate; HF gives no granular bytes.)
3. **Hotkey rebind UI.** Controls now has a hotkey **picker** (F2–F12 + Copilot, plus whatever is saved)
   that applies **immediately** via a new `reloadHotkeys` RPC (`HotkeyListener.update_settings()`), with a
   conflict warning when the Copilot key is chosen. Fixes the "stuck on copilot, no recovery" trap.
4. **Packaged engine now persists a log.** `run()` calls `app_logging.setup_logging(config_dir)` →
   `%APPDATA%\VoiceType\hebrew_live_dictation.log`. Verified on the real FS: after a packaged verify run the
   log gained today's entries (was last-written 2026-06-17).

Verification of the fixes: Python 267/267; WinUI build 0 errors; dev self-test 39/39; beta rebuilt (544 MB);
`verify_beta.ps1` PASSED (positive 39/39, negative hard-gate FAIL); engine log confirmed persisting.

**Audit reconciliation (2026-06-21, two external audits) — status vs HEAD + action.**

| # | Item | Status at HEAD | Evidence | Action |
|---|---|---|---|---|
| 1 | Shell self-injection (WinUI shell is a separate PID from the engine) | **Still broken** | `editing_backend.is_current_process()` compares to `os.getpid()` = the *engine* pid; the shell (`VoiceType.exe`, different pid) passed `is_usable_external()` | Sidecar adds `"voicetype.exe"` to `BLOCKED_TARGET_PROCESSES` (no protected-module edit) → all shell/HUD/Remote/tray windows are non-targets. Regression test added. |
| 2 | Frozen-engine audio deterministic (PortAudio) | **Already functional; made deterministic** | `dist\engine\_internal\_sounddevice_data\portaudio-binaries\libportaudio64bit.dll` present; engine log shows `AudioStream … started … vad=True` today from packaged runs | Added `sounddevice` to the REQUIRED `collect_all` in `engine.spec` so PortAudio no longer depends on the auto-hook. |
| 3 | Real end-to-end smoke before the full matrix | **Was undocumented** | 39/39 self-test proves launch/PRI/launch-mode, not voice | Added the **required P5 pre-smoke** below (manual voice path; only non-voice parts are checkable). |
| 4 | Stale/unconfigured cloud config | **Partially fixed** | Engine room already routes cloud→Offline (prior commit), but a returning user who never opens it still started on the cloud path | Added **startup recovery** `recover_unconfigured_cloud()`: an unconfigured cloud engine (empty/dangling Google creds, no key) is switched to offline at engine start. Configured cloud + `smart_auto`/local left untouched. Tests added. |
| 5 | Persist shell-side diagnostics | **Still broken** (in-memory only) | `AppLog` was a 400-line RAM ring buffer | `AppLog` now also appends to **`%APPDATA%\VoiceType\shell.log`** (rotated at 1 MB). Engine stdout/stderr (`"sidecar: …"`) + bridge launch failures already flow through `AppLog`, so they persist. |
| 6 | Triage the `VoiceType.exe` crash dump | **Not actionable in our code** | Application Error 1000: faulting module **`igd10umt64xe.DLL`** (Intel iGPU driver), `0xc0000005`, in the **Debug** build at 00:52 | GPU-driver access violation during WinUI render, not our code. Mitigation: update the Intel graphics driver; re-collect if it recurs in the **Release/packaged** build. |

**Required P5 pre-smoke (must pass before resuming the full focus-safety matrix):** with the rebuilt
artifact — (1) Engine room → **Offline** → **download model** → wait for "מותקן ✓"; (2) put the cursor in
**Notepad**, press the hotkey, speak one Hebrew phrase, stop; (3) confirm the transcript appears via
History / `getTranscripts`; (4) confirm the text lands **once** in Notepad and the shell/HUD/Remote never
took focus. The voice path cannot be faked; only mic enumeration and the packaged engine's audio-stream
start are machine-checkable (both confirmed). Resume the §matrix only after this smoke passes.

**Diagnostics / which files to send for support:** `%APPDATA%\VoiceType\hebrew_live_dictation.log`
(engine), `%APPDATA%\VoiceType\shell.log` (WinUI shell, new), the package-root `winui_runtime_report.txt`,
and any `%LOCALAPPDATA%\CrashDumps\VoiceType.exe.*.dmp`.

**Pre-smoke round 1 (CI artifact `1e4a5e4`) — partial fail (Remote-start target capture).** Good: offline
model, start/stop, STT, final-only insertion, history, Hebrew punctuation/newline all worked. **Failure:**
starting from the floating **Remote** with **Notepad** as the intended target, the transcript appeared in
the app/history but text did **not** land in Notepad. Engine log root cause:
```
EditingBackend - Using z-order external target instead of foreground target:
  foreground=…process=voicetype.exe title=שלט        (the Remote took foreground)
  target=…process=explorer.exe title=VoiceType-winui-beta-unsigned - סייר הקבצים   (File Explorer)
```
The Remote (interactive, `WS_EX_NOACTIVATE`) still **activated on the XAML button-click**, so the shell
became foreground. The shell self-target denylist correctly blocked self-injection, but
`capture_best_target`'s **z-order fallback then picked the topmost OTHER external window** (the File
Explorer window showing the extracted beta folder), not Notepad — so text went there. F8 works because
Notepad is already foreground (captured directly). Home/Tray share the same root cause (shell foreground at
capture). **Fix:** `Native.MakeNoActivate()` subclasses the Remote to return `MA_NOACTIVATE` on
`WM_MOUSEACTIVATE`, so clicking it delivers the click but never takes foreground → the user's real target
stays foreground and is captured directly. (Build-verified; the focus behavior itself needs a human re-smoke.)

**Pre-smoke round 2 — insertion-path failure (offline final not typed).** Recognized Hebrew reached
history but **was not inserted** into the focused window, even with the target correctly captured as
`notepad.exe`, and even via F8. Engine log: every attempt logged `DictationController - Received real
final STT event` but only **5 `Injector event`s across 21 `whisper_local` sessions**. Root cause in
`dictation_controller.handle_stt_event`: `whisper_local` emits its single final **~2 s AFTER stop**, by
which time the stop-flush ([line 112]) already ran with an empty accumulator; in `final_only` mode the
late final is then *accumulated* and only flushed on trailing `.?!`/a command — so plain phrases land in
history but are never typed (the round-1 "successes" were the finals that happened to end in punctuation).
**Fix (authorized engine change):** in the external/final path, a non-command, non-live final that
arrives while `state != "listening"` and nothing was injected this session is **injected once, verbatim**
(`has_pasted_final` guards double-insertion; cloud finals-while-listening are unchanged). 6 regression
tests in `tests/test_poststop_final.py` (no-punctuation/with-punctuation/late-after-idle injected once,
no duplicate, cloud-while-listening unchanged).

**Pre-smoke round 3 — insertion corruption (Hebrew garbled).** Insertion landed in Notepad, but the
text was corrupted vs history (e.g. "שלום עולם זה מבחן" → "שלום זזזזזזה ןןןן" — chars repeated + dropped).
Engine log: `Injector event backend=unicode_keyboard` with `raw_text_len==text_len==inserted_len` — the
injector's accounting was correct; the corruption is at the OS delivery layer. Root cause:
`text_injector._type_unicode_text` types **char-by-char** via `SendInput` keydown+keyup with only
`time.sleep(0.001)` (1 ms) between chars; under the load right after offline processing, Notepad drops
some `WM_CHAR`s and auto-repeats others. For Notepad the generic `TargetProfile.preferred_backend ==
"unicode_keyboard"` forced that path. **Fix (authorized `text_injector.py` change):** for a final-only
complete utterance, `inject_final` now calls `_insert_text(target_text, prefer_clipboard=True)`, which
inserts via **atomic clipboard paste** (exact Hebrew/Unicode, with `restore_clipboard`), falling back to
unicode if the paste fails, and never diverting Word (COM). Added insert-attempt instrumentation (length,
prefer_clipboard, profile backend, target, backend used, fallback chain). 4 regression tests in
`tests/test_final_clipboard_insertion.py` (final→clipboard; paste-fail→unicode fallback; non-final→unicode
unchanged; Word→COM not clipboard).

Per-target focus matrix below remains **unfilled** — re-run manual P5 against the **rebuilt** artifact
after the pre-smoke. The cloud→offline routing, startup recovery, shell self-target block, hotkey rebind,
post-stop final insertion, clipboard-paste fidelity, and logging are build-verified + unit-tested, but the
end-to-end voice path still needs a human pass. (Home/Tray target-capture — the shell-foreground backstop
— remains a separate open item if those paths still mis-target.)

## Product Completion / Feature Parity (post-P5 — the beta is NOT feature-complete)

P5 validates that the **supported** dictation workflow (F8 + Remote → target app) works end to end. It
does **not** make the product feature-complete — the WinUI shell is still a subset of the original vision
and of the legacy Qt app. Before the beta is called complete, a dedicated Product Completion phase must
close these gaps. (Runs **after** P5 and the P6 review; do not start until explicitly directed.)

### Audit (A–F), 2026-06-22

**A. What already works (WinUI):** core offline dictation (F8/Remote → clipboard insert), mic, STT,
start/stop, status; the 6-room IA — Home (status + recent), **Dictation (language selection + punctuation
toggles + live command reference)**, Engine (offline / model download / offline-backup), Controls (hotkey
rebind + toggle/PTT + mic + HUD/Remote toggles), History (transcripts + **TXT export** + clear), **Settings
(theme + startup + minimize-on-close + Advanced door + Diagnostics viewer)**; focus-safe HUD + Remote;
onboarding (offline-first); persisted engine + shell logs; tray; CI beta artifact.

**B. Missing from the original vision:** live/interim "words-while-speaking" for the **offline** engine
(`whisper_local` emits no interims; the HUD shows live words only for a streaming provider, and the Remote
shows none); an **offline model catalog** (only one hard-coded `small` model — weak quality); cloud as a
real **Recommended** path (Google Chirp 3 config + test); Advanced/Labs depth (VAD/recognizer) — deferred.

**C. Regressed from the legacy Qt app** (`qt_app.py` had these; WinUI dropped them): **Google setup UI**
(project_id · model · region · credential-mode · service-account JSON file picker); **provider selection +
API keys** (Deepgram/Groq); **Whisper model selection** (combo → now one fixed model); **DOCX export**
(WinUI is TXT-only); advanced **audio/VAD/recognizer** settings; **updater / update-check** surface. (Voice
editing commands — delete last word/sentence, replace/delete phrase, send/next — are preserved via the
command pack + the Dictation command reference, not regressed in capability.)

**D. Do first (highest "real product" impact):** (1) **Cloud/Google setup** — biggest regression and the
path to *good* Hebrew quality (Chirp 3), since the offline `small` model is weak; (2) **offline model
manager** — let users pick a larger/better model; (3) **live/interim in HUD + Remote** for streaming
providers.

**E. Can wait:** experimental live-typing-into-target (Labs); offline partial-decode interims (hard, low
ROI); DOCX export; updater UI; advanced VAD/recognizer Labs settings.

**F. Recommended phased plan:**
- **PC1 — Cloud provider setup (Google first):** restore the Engine-room Google config (project_id /
  region / model / SA-JSON picker / ADC / **Test connection**); mark cloud usable only when configured;
  wire `smart_auto`. Reuses the engine's existing `google_stt_v2` + `auto_select`.
- **PC2 — Offline model manager:** catalog (tiny/base/small/medium/large) with size · quality · speed ·
  RAM · recommended; download / delete / select; optional local-folder import.
- **PC3 — Live/interim experience:** show interim words in **HUD and Remote** for streaming providers;
  keep final-only insertion; defer offline partial-decode.
- **PC4 — Parity cleanup:** per-provider language clarity; DOCX export; updater/update-check surface;
  Diagnostics polish; audio/VAD Labs.
- **PC5 — Full P5 matrix + P6 review** before any public beta.

1. **Live / interim dictation experience (Gboard-like).** The user should see words **while speaking**;
   the HUD/Remote should show recent/interim words, not only finals. RTL-safety decision to make: show
   live/interim words **in the HUD/Remote only**; keep **final-only insertion** into the target app
   (today's hardened behavior); optional experimental live-typing-into-target behind a Labs toggle later.
   (Note: offline `whisper_local` emits no interims — interim display likely needs a streaming/cloud
   provider or a partial-decode path.)
2. **Offline model manager.** List **all** downloadable models with size · quality · speed · RAM estimate ·
   a "recommended" label; allow download / delete / select; import a local model folder if practical.
   (Today: one hard-coded model, indeterminate progress, no choice.)
3. **Language selection.** Verify a dictation-language selector exists **and actually changes the active
   provider's language**; Hebrew / English / other must be clear **per provider**; the UI must state what
   each provider/model supports.
4. **Cloud providers — bring Google/Chirp back properly.** A real Google setup surface: Project ID ·
   location/region · recognizer/model · service-account JSON picker · ADC if supported · a working **Test
   connection**; other cloud providers / API-key setup if still intended. Cloud must **not** be shown as
   usable until configured (replace today's honest route-to-Offline with real setup).
5. **Old-app feature-parity audit (legacy Qt vs WinUI).** List missing/regressed: Google setup · live
   interim text · overlay/toolbar behavior · hotkey modes (toggle/PTT) · spoken punctuation · editing
   commands · delete last word/sentence · replace/delete phrase · send/next field · mic/audio/VAD settings ·
   history/export · diagnostics/log viewer · provider/model settings · tray/startup behavior ·
   updater/release notes.

### Product Completion — running changelog

- **PC1 — Google/Chirp setup (done).** Engine room now has a real **Google Cloud config card** (shown
  when "Google Chirp 3" is selected): Project ID · Region · Model (chirp_3/chirp_2/…) · Recognizer ID ·
  credential mode (service-account JSON / ADC) · **JSON file picker** · **Test connection** (live
  `list_recognizers` check) · honest **configured / not-configured / failed** status. New sidecar RPCs
  `getGoogleStatus` + `testConnection` (reuse the engine's credential/project resolution; no protected
  engine module changed). Selecting Google sets `provider=google_v2`; missing credentials are reported
  here and still route to Offline at next start (`recover_unconfigured_cloud`). Deepgram/Groq ("Choose")
  remain routed to Offline (later phase). *Tests:* Python 282/282; WinUI build 0 errors; dev self-test
  39/39; packaged verify PASSED. *Known limits:* live connection result depends on the user's real GCP
  credentials (can't be CI-verified); `smart_auto` Google-when-usable is handled by `auto_select`.
  *Core path unaffected* (offline F8/Remote untouched). **Next: PC2 started.**
- **PC2 — Offline model manager (done).** The Engine-room offline-model card now has a **model selector**
  (ComboBox) listing all six known models (tiny/base/small/medium/large-v3/distil-large-v3), each showing
  **download size · RAM · quality · speed · ★recommended · ✓installed**, plus a metadata line for the
  selected model. Selecting a model sets `providers.whisper.model`; the existing download/delete/status
  then follow the selected model. New sidecar RPC `getModelCatalog` (size+RAM from the engine's
  `MODEL_REGISTRY`; quality/speed/recommended are presentation — **`medium` is recommended for Hebrew**,
  since the English-distilled `distil` models are weaker for Hebrew). *Tests:* Python 282/282; WinUI 0
  errors; dev self-test 39/39. *Known limits:* no manual local-folder import yet (deferred); large models
  need the RAM the catalog states (engine `ram_preflight` still guards load). *Core path unaffected*
  (default stays `small`; download/delete reuse the proven path). **Next: PC3 started.**
- **PC3 — Live/interim words in HUD + Remote (done).** The HUD already showed live words on `text` events;
  the **Remote** now shows them too — a single trimmed RTL line below the orb/button (Remote resized
  280×104), shown only while listening/stopping and cleared otherwise. `AppHost`'s `text` case now feeds
  both `_hud.SetWords` and `_remote.SetWords`. **Streaming providers** (cloud Google) stream interims → live
  words while speaking; **offline `whisper_local`** has no interims, so words appear at the end (the final,
  briefly) — accepted per the phase rule. **Target-app insertion stays final-only** (no live-typing into
  the target). *Tests:* WinUI 0 errors; dev self-test 39/39 (Remote constructs; no-activate intact; no
  Python change). *Core path unaffected.* **Next: PC4 started.**

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
