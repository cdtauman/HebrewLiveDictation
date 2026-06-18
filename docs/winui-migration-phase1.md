# VoiceType — Phase 1 WinUI Migration Validation Report

**Goal:** quickly prove the WinUI 3 shell + Python engine sidecar architecture can
preserve the important existing behaviors, with the smallest proof per behavior.
**Date:** 2026-06-18 · **Machine:** Windows 11 (10.0.26200), .NET SDK 10.0.301,
Python 3.12.10, VS Build Tools 18, Windows App Runtime 1.5/1.6/1.7, **display at 150% DPI**.

> **Bottom line:** Phase 1 is **GREEN**. The WinUI 3 + Python-sidecar architecture preserves
> every migration-critical behavior that can be checked automatically. Three independent
> automated suites pass: **engine bridge 9/9**, **WinUI runtime 14/14**, **self-contained
> packaged exe 14/14 (runs standalone)**. The #1 risk — *no focus stealing* — is **proven**.
> The Python engine was **not modified**. Remaining items need a human at the screen
> (visual RTL, tray clicks, actual F8 keypress, per-app injection, 2+ monitor placement).

---

## 1. Result summary (the 11 requested checks)

| # | Behavior | Status | Evidence |
|---|---|---|---|
| 7 | **WinUI ↔ Python Named-Pipe JSON-RPC bridge** | ✅ **VERIFIED (both sides)** | Python self-test 9/9; C# client connect/ping/getStatus/events 14/14 |
| 8 | **Settings read/write boundary** | ✅ **VERIFIED** | engine = single writer; `app.theme` round-trip from both Python and C# |
| 3 | **No-focus Voice HUD** | ✅ **VERIFIED (runtime)** | `focus.no_steal`: foreground unchanged after show; `WS_EX_NOACTIVATE`+`TRANSPARENT` set |
| 4 | **Floating Remote toolbar** | ✅ **VERIFIED (runtime)** | no-activate + topmost, stays interactive (no click-through) |
| 11 | **DPI / multi-monitor** | ✅ **VERIFIED (DPI) / ⚠ 1 monitor here** | PerMonitorV2 (awareness=2) at **150%** (144 DPI); monitor enumeration works (count=1 on this box) |
| 9 | **Packaging smoke test** | ✅ **VERIFIED** | `dotnet publish` self-contained unpackaged exe (110 MB) runs standalone, 14/14 |
| 1 | **Tray behavior** | ✅ **VERIFIED (creation) / ⚠ clicks manual** | `Shell_NotifyIcon` NIM_ADD succeeds in-process; click handling = interactive build |
| 5 | **Global hotkeys / push-to-talk** | ✅ **VERIFIED (starts) / ⚠ keypress manual** | `HotkeyListener` starts in sidecar (`hotkeys=True`), drives controller |
| 6 | **Text insertion parity** | ✅ **VERIFIED (init) / ⚠ matrix manual** | engine-side & unmodified; injector + foreground hook + Word-COM init OK |
| 2 | **Hidden / background operation** | ✅ **ARCH VERIFIED / ⚠ hide-to-tray UX = next** | sidecar is always-on & owns engine headless; WinUI hide-to-tray is a small interactive-shell add |
| 10 | **Hebrew / RTL rendering** | ⚠ **PARTIAL (runs) / visual manual** | windows built with `FlowDirection=RightToLeft` + Hebrew render in the running app; visual correctness = human |

Toolchain gates: **NuGet restore ✅**, **WinUI compile ✅**, **B1 resolved ✅**.

---

## 2. Automated evidence

### 2.1 Engine bridge — 9/9  (`python phase1_winui/bridge/selftest_bridge.py`)
```
pipe.connect · rpc.ping · rpc.getStatus.idle · hotkeys.active · settings.read
settings.write.boundary · events.async_push · dictation.start.event(listening)
dictation.stop.event(stopping->idle)        => 9/9 passed
```

### 2.2 WinUI runtime — 14/14  (`VoiceType.Shell.exe --selftest`, written to `phase1_runtime_report.txt`)
```
[PASS] bridge.spawn            pid=...
[PASS] bridge.connect          NamedPipeClientStream (overlapped)
[PASS] bridge.ping             {"ok": true, ...}
[PASS] bridge.getStatus        state=idle
[PASS] bridge.settings.boundary app.theme round-trip = light
[PASS] bridge.event.stream     event kinds: status,heartbeat
[PASS] focus.no_steal          fgBefore==fgAfter ; hud never became foreground   <-- #1 RISK PROVEN
[PASS] hud.style.noactivate    exStyle has WS_EX_NOACTIVATE
[PASS] hud.style.clickthrough  WS_EX_TRANSPARENT
[PASS] remote.style.noactivate WS_EX_NOACTIVATE
[PASS] remote.not.clickthrough interactive (has buttons)
[PASS] dpi.permonitor          awareness=2 hudDpi=144 (1.50x)
[PASS] monitors.enumerate      count=1 virtual=1920x1200
[PASS] tray.shell_notifyicon   NIM_ADD succeeded
```

### 2.3 Packaging — self-contained publish runs standalone (14/14)
`dotnet publish -c Release -r win-x64 --self-contained` → 110 MB unpackaged folder;
running the published exe with `--selftest` scores 14/14 (no dev tools on the path).

---

## 3. Architecture proven
- **Process model:** WinUI 3 (.NET 9, C#) shell ↔ **headless Python sidecar** that runs the
  **unmodified** `src/hebrew_live_dictation/` engine. The sidecar runs a windowless
  `QApplication` (required because `DictationController` is a QObject using
  `QueuedConnection`/`QTimer`). The IPC seam **replaces** `qt_app.py`'s `AppBridge`.
- **Transport:** Named pipe `\\.\pipe\voicetype-bridge`, newline-delimited JSON-RPC,
  **overlapped I/O** on the server (so async status/text/error events stream while the read
  loop is blocked). C# uses `NamedPipeClientStream` (overlapped) — no threading hazards.
- **Settings boundary:** the engine is the single writer of `settings.json` (schema v4 +
  migrations preserved); the shell only calls `getConfig`/`setConfig`.
- **Focus-safety:** overlays are `OverlappedPresenter` tool windows shown with
  `AppWindow.Show(activateWindow:false)` plus `WS_EX_NOACTIVATE | WS_EX_TOPMOST |
  WS_EX_LAYERED` (+`WS_EX_TRANSPARENT` for the click-through HUD). Verified to not steal focus.

---

## 4. Blockers found & resolved
- **B1 (resolved): Appx/MSIX MSBuild tooling.** WinUI's PRI pipeline needs
  `Microsoft.Build.Packaging.Pri.Tasks.dll` + `Microsoft.Build.AppxPackage.dll`, absent from
  the dotnet SDK. **Fix:** user installed VS Build Tools 18; `Directory.Build.props` points
  `AppxMSBuildToolsPath` at `...\BuildTools\MSBuild\Microsoft\VisualStudio\v18.0\AppxPackage\`
  so plain `dotnet build`/`publish` work with PRI **enabled**.
- **TFM correction:** retargeted **net8 → net9** (`Microsoft.WindowsDesktop.App` 8.0 is not
  installed; 9.0/10.0 are) and bumped **WindowsAppSDK 1.6 → 1.7** (runtime 1.7 installed).
  A net8 build launched with HRESULT 0x80670016 (runtime-not-found) until corrected.
- **Bridge defects fixed during the spike:** sync-handle pipe deadlock → overlapped I/O;
  single-threaded Python test client; orphan-bridge pipe hijack → kill-before/after in runners.

---

## 4b. Manual-test surface (`--show` + tray + hide-to-tray)  [added]

An interactive mode now exists for eyeball verification (built, launches, spawns the
bridge as a child — automated smoke test passes; visuals are for you to confirm):

```
cd phase1_winui/shell
dotnet build
.\bin\Debug\net9.0-windows10.0.19041.0\win-x64\VoiceType.Shell.exe --show
```
What launches: the **console** (RTL Hebrew), a **tray icon**, the **Voice HUD**
(bottom-center, click-through, dark RTL pill) and the **Remote** (bottom-right, draggable
by its `⠿` handle, with התחל/עצור buttons). All connect to the auto-spawned Python sidecar.

Manual checks this unlocks (items 1, 2, 6 below):
- **RTL** — confirm Hebrew reads right-to-left on console, HUD, Remote; Latin tokens embed correctly.
- **Focus-safety, live** — click around other apps; the HUD/Remote stay on top and never take focus.
- **Drag** — drag the Remote by its handle; it should move without flicker/activation.
- **Tray** — left-click = show console; right-click = menu (הצג / התחל / עצור / יציאה).
- **Hide-to-tray** — click the console's X (or "הסתר למגש"); it hides, app keeps running; reopen from tray.
- **Live status** — press the Remote's "התחל" (or your **F8** hotkey): the HUD reflects engine
  status streamed from the sidecar; "עצור" stops. ("יציאה" cleanly shuts down the sidecar + app.)

> Note: `--show` spawns a fresh sidecar; if a stale bridge is already running, kill stray
> `voicetype_bridge` python processes first (the test runners do this automatically).

## 5. Still requires a human (cannot be automated here)
1. **Visual RTL correctness** of every surface (mixed LTR tokens like "Project ID", model names).
2. **Tray icon clicks** (left/right/double) and menu — creation is proven; interaction is not.
3. **Actual F8 / push-to-talk keypress** while another app is focused (hook is started; firing is manual).
4. **Per-app text insertion matrix** (Word COM / Gmail UIA / WhatsApp / Notepad) — engine-side & unchanged.
5. **2+ monitor placement & mixed-DPI** (only one monitor present on this machine).
6. **Hide-to-tray + interactive HUD/Remote wiring** in `MainWindow` (small build; selftest used standalone windows).

---

## 6. Files produced (engine untouched; nothing committed)
```
phase1_winui/
  bridge/voicetype_bridge.py     # overlapped Named-Pipe JSON-RPC sidecar (no engine changes)
  bridge/selftest_bridge.py      # 9/9
  shell/                         # WinUI 3 unpackaged, net9, WinAppSDK 1.7
    Directory.Build.props        # B1 fix (AppxMSBuildToolsPath -> BuildTools)
    VoiceType.Shell.csproj, app.manifest (PerMonitorV2)
    App.xaml(.cs)                # entrypoint: --selftest | --show | (interactive)
    MainWindow.xaml(.cs)         # RTL console + hide-to-tray (AppWindow.Closing -> Hide)
    AppHost.cs                   # spawns sidecar; owns tray + console + overlays; bridge wiring
    TrayIcon.cs                  # message-only window + Shell_NotifyIcon + context menu
    Overlays.cs                  # HUD (click-through) + draggable Remote, no-activate/topmost
    Native.cs                    # Win32 interop (no-activate, tray, menu, drag, DPI, monitors)
    BridgeClient.cs              # C# NamedPipeClientStream JSON-RPC client
    RuntimeSelfTest.cs           # 14/14 automated runtime checks (--selftest)
  phase1_runtime_report.txt      # latest runtime run output
  PHASE1_REPORT.md               # this file
```

### How to reproduce
```
python phase1_winui/bridge/selftest_bridge.py                      # 9/9
cd phase1_winui/shell && dotnet build                              # builds (B1 fix auto-applies)
.\bin\Debug\net9.0-windows10.0.19041.0\win-x64\VoiceType.Shell.exe --selftest   # 14/14 -> report
dotnet publish -c Release -r win-x64 --self-contained              # standalone package
```
