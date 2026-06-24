using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Windows.Graphics;

namespace VoiceType.Shell;

/// <summary>
/// Automated runtime verification of the migration-critical behaviors that can be
/// checked without a human watching the screen: the C#-side bridge + history contract,
/// the no-activate / always-on-top overlay windows (focus-safety), the signature
/// surfaces (HUD morphing, tray health orb), window styles, DPI awareness, and
/// multi-monitor info. Writes a report file and exits.
/// </summary>
internal static class RuntimeSelfTest
{
    private static readonly List<(string name, bool ok, string detail)> Results = new();
    private static void Check(string name, bool ok, string detail = "")
        => Results.Add((name, ok, detail));

    // Rich one-line detail for a failed XAML construction (diagnoses Release/self-contained
    // XAML-loading regressions): type + message + inner-most message + HRESULT.
    private static string XamlDetail(Exception ex)
    {
        var inner = ex; while (inner.InnerException != null) inner = inner.InnerException;
        string m = $"{ex.GetType().Name}: {ex.Message} | inner: {inner.GetType().Name}: {inner.Message} | hr=0x{ex.HResult:X8}";
        return m.Length > 400 ? m.Substring(0, 400) : m;
    }

    public static async Task RunAsync(bool expectPackaged = false)
    {
        Process? bridge = null;
        var events = new List<JsonElement>();
        string repoRoot = RepoPaths.FindRoot();
        // Report path that works in BOTH layouts: a dev tree keeps the existing gitignored
        // <repo>\winui\ location (that folder exists); a packaged beta has no winui\ subfolder, so
        // write into the package ROOT (<package>\winui_runtime_report.txt) — never into a missing
        // subfolder. WriteReport also creates the dir and surfaces any write failure (no swallow).
        string winuiDir = Path.Combine(repoRoot, "winui");
        string reportPath = Directory.Exists(winuiDir)
            ? Path.Combine(winuiDir, "winui_runtime_report.txt")
            : Path.Combine(repoRoot, "winui_runtime_report.txt");

        var (pipeShort, pipeFull) = RepoPaths.NewPipe("voicetype-selftest");
        try
        {
            // 1) Spawn the engine bridge on a unique pipe (stdout/stderr drained).
            bridge = RepoPaths.StartSidecar(repoRoot, pipeFull);
            Check("bridge.spawn", bridge != null && !bridge.HasExited,
                  bridge != null ? $"pid={bridge.Id}" : "failed to start");

            // 1b) Launch-mode parity (P2): the process the shell ACTUALLY spawned must match the
            //     expected mode. Packaged layout (engine\engine.exe present) must run the bundled
            //     engine.exe; dev tree must run the python -m fallback.
            //
            //     The expectation comes from the EXPLICIT --expect-packaged-engine flag when given,
            //     NOT from the layout. This is the key hardening: EngineLaunchMode() is derived from
            //     whether engine.exe exists, so using it alone as "expected" would let a missing/
            //     broken engine.exe silently read "dev" and pass through python. Forcing "packaged"
            //     makes that case fail hard. Without the flag, the dev run self-adapts to the layout.
            string derivedMode = RepoPaths.EngineLaunchMode();   // "packaged" iff engine\engine.exe present
            string expectMode = expectPackaged ? "packaged" : derivedMode;
            string spawned = "";
            try { if (bridge is { HasExited: false }) spawned = bridge.ProcessName; } catch { }
            bool isEngineExe = spawned.Equals("engine", StringComparison.OrdinalIgnoreCase);
            bool isPython = spawned.StartsWith("python", StringComparison.OrdinalIgnoreCase);
            bool modeOk = expectMode == "packaged" ? isEngineExe : isPython;
            Check("engine.launch.mode", modeOk,
                  $"expected={expectMode}{(expectPackaged ? " (forced --expect-packaged-engine)" : "")}, " +
                  $"spawned='{spawned}', derived={derivedMode}, " +
                  $"packagedEngine={RepoPaths.PackagedEnginePath() ?? "(none)"}");

            // 1c) R3-Google stabilization: the pick-lists must include the entries needed to probe
            //     Google model/language behavior. Presence in the UI is not proof of dictation.
            bool hasLatestLong = Views.EnginePage.GoogleModels.Any(m => m.tag == "latest_long");
            Check("engine.google.models", hasLatestLong,
                  hasLatestLong ? "Google model list includes latest_long (diagnostic candidate; not proof of live words)"
                                : "latest_long missing from the Google model dropdown");
            bool hasHeIl = Views.DictationPage.Languages.Any(l => l.tag == "he-IL");
            Check("dictation.languages", hasHeIl,
                  hasHeIl ? "Hebrew language list includes he-IL (diagnostic only; iw-IL remains documented default)"
                          : "he-IL missing from the dictation language list");
            bool hasDeepgramNova3 = Views.EnginePage.DeepgramModels.Any(m => m.tag == "nova-3");
            Check("engine.deepgram.models", hasDeepgramNova3,
                  hasDeepgramNova3 ? "Deepgram model list includes nova-3 for Hebrew streaming"
                                   : "nova-3 missing from the Deepgram model dropdown");
            bool hasGroqWhisper = Views.EnginePage.GroqModels.Any(m => m.tag == "whisper-large-v3");
            Check("engine.groq.models", hasGroqWhisper,
                  hasGroqWhisper ? "Groq model list includes whisper-large-v3 final-only transcription"
                                 : "whisper-large-v3 missing from the Groq model dropdown");

            // 2) Connect the C# client and exercise the contract from the WinUI side.
            using var client = new BridgeClient(pipeShort);
            var disconnected = new System.Threading.ManualResetEventSlim(false);
            client.EventReceived += e => { lock (events) events.Add(e.Clone()); };
            client.Disconnected += () => disconnected.Set();
            try
            {
                await client.ConnectAsync(20000);
                Check("bridge.connect", true, "NamedPipeClientStream (overlapped)");

                var ping = await client.RpcAsync("ping");
                Check("bridge.ping", ping.TryGetProperty("ok", out var ok) && ok.GetBoolean(), ping.ToString());

                var st = await client.RpcAsync("getStatus");
                Check("bridge.getStatus", st.TryGetProperty("state", out var s) && s.GetString() == "idle",
                      "state=" + st.GetProperty("state").GetString());

                var providerStatus = await client.RpcAsync("getProviderStatus");
                bool providerShape = providerStatus.TryGetProperty("providers", out var ps)
                                     && ps.ValueKind == JsonValueKind.Array
                                     && ps.EnumerateArray().Any(p =>
                                         p.TryGetProperty("id", out var id)
                                         && id.GetString() == "google_v2"
                                         && p.TryGetProperty("capabilities", out var pc)
                                         && pc.TryGetProperty("streaming", out _))
                                     && providerStatus.TryGetProperty("effectiveProvider", out _);
                bool routingShape = providerStatus.TryGetProperty("routing", out var routing)
                                    && routing.ValueKind == JsonValueKind.Object
                                    && routing.TryGetProperty("startGate", out _)
                                    && routing.TryGetProperty("backupReady", out _);
                Check("bridge.getProviderStatus", providerShape && routingShape,
                      providerShape && routingShape ? "provider control plane returned registry rows + routing"
                                    : providerStatus.GetRawText());

                var labsStatus = await client.RpcAsync("getLabsStatus");
                bool labsLocked = labsStatus.TryGetProperty("gate", out var lg) && lg.GetString() == "locked"
                                  && labsStatus.TryGetProperty("liveTypingMode", out var lm) && lm.GetString() == "final_only"
                                  && labsStatus.TryGetProperty("inputBackend", out var lb) && lb.GetString() == "v1"
                                  && labsStatus.TryGetProperty("tsfExperimentalTransport", out var ltsf)
                                  && ltsf.ValueKind == JsonValueKind.False;
                Check("bridge.getLabsStatus", labsLocked,
                      labsLocked ? "live target typing Labs gate is locked; insertion stays final-only"
                                 : labsStatus.GetRawText());

                var credentialStatus = await client.RpcAsync("getProviderCredentialStatus", new { provider = "deepgram" });
                bool credentialShape = credentialStatus.TryGetProperty("provider", out var cpv)
                                       && cpv.GetString() == "deepgram"
                                       && credentialStatus.TryGetProperty("configured", out _)
                                       && credentialStatus.TryGetProperty("storage", out _)
                                       && !credentialStatus.TryGetProperty("apiKey", out _);
                Check("bridge.providerCredentialStatus", credentialShape,
                      credentialShape ? "provider credential status returned no-secret storage metadata"
                                      : credentialStatus.GetRawText());

                var theme = (await client.RpcAsync("getConfig", new { key = "app.theme" }))
                            .GetProperty("value").GetString();
                var wrote = await client.RpcAsync("setConfig", new { key = "app.theme", value = theme });
                Check("bridge.settings.boundary",
                      wrote.TryGetProperty("saved", out var sv) && sv.GetBoolean(),
                      $"app.theme round-trip = {theme}");

                // Engine room writes stt.mode via setConfig — verify the exact key round-trips
                // (read current value, write it back unchanged: no net change to user config).
                var modeRead = await client.RpcAsync("getConfig", new { key = "stt.mode" });
                string modeNow = modeRead.TryGetProperty("value", out var mv) && mv.ValueKind == JsonValueKind.String
                                 ? mv.GetString()! : "api";
                var modeWrote = await client.RpcAsync("setConfig", new { key = "stt.mode", value = modeNow });
                Check("bridge.engine.config",
                      modeWrote.TryGetProperty("saved", out var ms) && ms.GetBoolean(),
                      $"stt.mode round-trip = {modeNow}");

                // History room contract (read-only; clearHistory is intentionally NOT
                // exercised here so the real transcript store is never wiped by a test).
                var tr = await client.RpcAsync("getTranscripts", new { count = 5 });
                Check("bridge.getTranscripts",
                      tr.TryGetProperty("items", out var trItems) && trItems.ValueKind == JsonValueKind.Array,
                      "items[] returned");
                var histStatus = await client.RpcAsync("getHistoryStatus");
                bool histStatusShape = histStatus.TryGetProperty("enabled", out var hsEnabled)
                                       && (hsEnabled.ValueKind == JsonValueKind.True || hsEnabled.ValueKind == JsonValueKind.False)
                                       && histStatus.TryGetProperty("maxEntries", out var hsMax) && hsMax.ValueKind == JsonValueKind.Number
                                       && histStatus.TryGetProperty("count", out var hsCount) && hsCount.ValueKind == JsonValueKind.Number;
                int histCount = histStatus.TryGetProperty("count", out var hsCountMsg) && hsCountMsg.TryGetInt32(out var hcv) ? hcv : -1;
                Check("bridge.getHistoryStatus", histStatusShape,
                      histStatusShape ? $"history status returned (count={histCount})" : histStatus.GetRawText());

                // Dictation room command reference (read-only).
                var cmds = await client.RpcAsync("getCommands");
                bool hasPunct = cmds.TryGetProperty("punctuation", out var cp) && cp.ValueKind == JsonValueKind.Array;
                bool hasActions = cmds.TryGetProperty("actions", out var ca) && ca.ValueKind == JsonValueKind.Array;
                Check("bridge.getCommands", hasPunct && hasActions,
                      $"punctuation+actions returned ({(hasPunct ? cp.GetArrayLength() : 0)}+{(hasActions ? ca.GetArrayLength() : 0)})");

                // Controls room microphone picker: thin-adapter enumeration RPC.
                var mics = await client.RpcAsync("listMicrophones");
                bool micItems = mics.TryGetProperty("items", out var mi) && mi.ValueKind == JsonValueKind.Array;
                Check("bridge.listMicrophones", micItems,
                      $"items[] returned ({(micItems ? mi.GetArrayLength() : 0)} input devices)");

                // Honest offline readiness: real on-disk model presence (not a config flag).
                var modelStat = await client.RpcAsync("getModelStatus");
                bool msShape = modelStat.TryGetProperty("downloaded", out var dl)
                               && (dl.ValueKind == JsonValueKind.True || dl.ValueKind == JsonValueKind.False)
                               && modelStat.TryGetProperty("name", out _) && modelStat.TryGetProperty("path", out _);
                Check("bridge.getModelStatus", msShape,
                      $"model status returned (downloaded={(msShape && dl.ValueKind == JsonValueKind.True)})");

                // Packaged insertion smoke check: the dynamic text-insertion backends
                // (comtypes.client for Word COM, uiautomation for the UIA path) must be importable
                // in the ENGINE process. In a packaged run this proves the freeze actually bundled
                // them (editing_backend imports them lazily, so PyInstaller can't see them) — i.e.
                // real injection into Word/UIA targets works, not just engine startup. In dev the
                // venv has them. A hard check either way.
                var caps = await client.RpcAsync("getCapabilities");
                bool True_(JsonElement o, string p) => o.TryGetProperty(p, out var v) && v.ValueKind == JsonValueKind.True;
                // The Word COM path specifically needs comtypes.client (a submodule a freeze can miss
                // even when the base comtypes package is bundled), so require it ALONGSIDE comtypes and
                // uiautomation — otherwise the proof could pass while the real Word backend is absent.
                bool insOk = caps.TryGetProperty("insertion", out var ins)
                             && True_(ins, "comtypes")
                             && True_(ins, "comtypes_client")
                             && True_(ins, "uiautomation");
                Check("engine.insertion.deps", insOk,
                      insOk ? "comtypes + comtypes.client (Word COM) + uiautomation (UIA) importable in the engine"
                            : $"missing insertion backend(s): {caps.GetRawText()}");

                // Codex MF5: prove python-docx + the DOCX history-export path actually work in the
                // (frozen) engine — it ships a default template a freeze can miss. Writes a tiny DOCX.
                var docx = await client.RpcAsync("selfTestDocx");
                bool docxOk = True_(docx, "ok")
                              && docx.TryGetProperty("size", out var dsz) && dsz.TryGetInt32(out var dv) && dv > 0;
                Check("engine.export.docx", docxOk,
                      docxOk ? "python-docx wrote a non-empty DOCX in the engine"
                             : $"DOCX export self-test failed: {docx.GetRawText()}");

                // Destructive-RPC guard: clearHistory WITHOUT a confirm flag must refuse
                // (so this is safe to run — it never wipes the real store).
                var clr = await client.RpcAsync("clearHistory");
                Check("bridge.clearHistory.guard",
                      clr.TryGetProperty("cleared", out var cl) && !cl.GetBoolean(),
                      "refused without confirm");
                var delHist = await client.RpcAsync("deleteTranscript", new { id = "selftest-noop" });
                Check("bridge.deleteTranscript.guard",
                      delHist.TryGetProperty("deleted", out var dh) && !dh.GetBoolean(),
                      "refused without confirm");

                await client.RpcAsync("startDictation", new { mode = "external" });
                await Task.Delay(2500);
                await client.RpcAsync("stopDictation");
                await Task.Delay(1500);
                lock (events)
                {
                    var kinds = events.Select(e => e.TryGetProperty("kind", out var k) ? k.GetString() : null)
                                      .Where(k => k != null).ToList();
                    Check("bridge.event.stream", kinds.Contains("status") || kinds.Contains("heartbeat"),
                          "event kinds: " + string.Join(",", kinds.Distinct()));
                }
            }
            catch (Exception ex)
            {
                Check("bridge.client", false, ex.Message);
            }

            // 3) No-activate / always-on-top overlay windows + FOCUS-SAFETY proof.
            IntPtr fgBefore = Native.GetForegroundWindow();

            var (hud, hudHwnd) = MakeOverlayWindow("VoiceType HUD — חיווי קולי", clickThrough: true,
                                                   x: 200, y: 900, w: 720, h: 120);
            var (remote, remoteHwnd) = MakeOverlayWindow("שלט", clickThrough: false,
                                                         x: 1200, y: 820, w: 240, h: 80);
            await Task.Delay(400); // let the window manager settle

            IntPtr fgAfter = Native.GetForegroundWindow();
            bool noSteal = fgAfter == fgBefore && fgAfter != hudHwnd && fgAfter != remoteHwnd;
            Check("focus.no_steal", noSteal,
                  $"fgBefore=0x{fgBefore.ToInt64():X} fgAfter=0x{fgAfter.ToInt64():X} " +
                  $"('{Native.GetWindowTitle(fgAfter)}'); hud=0x{hudHwnd.ToInt64():X}");

            long hudEx = Native.GetExStyle(hudHwnd);
            long remoteEx = Native.GetExStyle(remoteHwnd);
            Check("hud.style.noactivate", (hudEx & Native.WS_EX_NOACTIVATE) != 0, $"exStyle=0x{hudEx:X}");
            Check("hud.style.clickthrough", (hudEx & Native.WS_EX_TRANSPARENT) != 0, "WS_EX_TRANSPARENT");
            Check("remote.style.noactivate", (remoteEx & Native.WS_EX_NOACTIVATE) != 0, $"exStyle=0x{remoteEx:X}");
            Check("remote.not.clickthrough", (remoteEx & Native.WS_EX_TRANSPARENT) == 0,
                  "Remote stays interactive (has buttons)");
            bool idlePolicy =
                !AppHost.ShouldShowRemote(remoteEnabled: false, idleQuickStartEnabled: true, consoleHidden: false, state: "idle")
                && AppHost.ShouldShowRemote(remoteEnabled: false, idleQuickStartEnabled: true, consoleHidden: true, state: "idle")
                && AppHost.ShouldShowRemote(remoteEnabled: false, idleQuickStartEnabled: true, consoleHidden: true, state: "error")
                && !AppHost.ShouldShowRemote(remoteEnabled: false, idleQuickStartEnabled: true, consoleHidden: true, state: "listening")
                && AppHost.ShouldShowRemote(remoteEnabled: true, idleQuickStartEnabled: false, consoleHidden: false, state: "listening")
                && AppHost.ShouldShowRemote(remoteEnabled: false, idleQuickStartEnabled: false, consoleHidden: false, state: "idle", forceVisible: true);
            Check("remote.idle.policy", idlePolicy,
                  "idle quick-start shows only while console is hidden and idle/error; Remote toggle and --show override");

            // 4) DPI awareness (PerMonitorV2 expected from app.manifest).
            IntPtr ctx = Native.GetThreadDpiAwarenessContext();
            int awareness = Native.GetAwarenessFromDpiAwarenessContext(ctx); // 2 = PerMonitor
            uint hudDpi = Native.GetDpiForWindow(hudHwnd);
            Check("dpi.permonitor", awareness == 2, $"awareness={awareness} hudDpi={hudDpi} (scale {hudDpi / 96.0:0.00}x)");

            // 5) Multi-monitor info.
            int monitors = Native.GetSystemMetrics(Native.SM_CMONITORS);
            int vw = Native.GetSystemMetrics(Native.SM_CXVIRTUALSCREEN);
            int vh = Native.GetSystemMetrics(Native.SM_CYVIRTUALSCREEN);
            Check("monitors.enumerate", monitors >= 1, $"count={monitors} virtual={vw}x{vh}");

            // 6) Tray icon can be created in this WinUI process (Shell_NotifyIcon NIM_ADD).
            var nid = new Native.NOTIFYICONDATA
            {
                cbSize = System.Runtime.InteropServices.Marshal.SizeOf<Native.NOTIFYICONDATA>(),
                hWnd = hudHwnd,
                uID = 1,
                uFlags = Native.NIF_ICON | Native.NIF_TIP,
                hIcon = Native.LoadIcon(IntPtr.Zero, Native.IDI_APPLICATION),
                szTip = "VoiceType",
            };
            bool added = Native.Shell_NotifyIcon(Native.NIM_ADD, ref nid);
            if (added) Native.Shell_NotifyIcon(Native.NIM_DELETE, ref nid);
            Check("tray.shell_notifyicon", added, "NIM_ADD succeeded (full click handling = interactive build)");

            // 6b) Health-orb tray icon renders (GDI 32bpp premultiplied-alpha HICON).
            IntPtr orb = Native.CreateDotIcon(0x51, 0xCF, 0x66);
            Check("tray.health_icon", orb != IntPtr.Zero, "CreateDotIcon -> HICON (brand status orb)");
            if (orb != IntPtr.Zero) Native.DestroyIcon(orb);

            // 6c) The productized Voice HUD must preserve focus-safety and morph through
            //     every engine state (incl. live words) without throwing.
            IntPtr fgPreHud = Native.GetForegroundWindow();
            var hudSurface = new HudWindow();
            bool hiddenAtStart = !hudSurface.Window.AppWindow.IsVisible;   // constructed hidden (no startup flash)
            bool hudStates = true;
            string wordsAfterRefresh = "";
            string targetWhileListening = "";
            string targetAfterStop = "x";
            string targetSafeState = "";
            bool fallbackShown = false;
            bool fallbackClearedOnStop = true;
            bool targetChangedOk = false;
            string wordsDuringPause = "";
            try
            {
                foreach (var hs in new[] { "connecting", "idle", "listening", "paused", "stopping", "error", "disconnected" })
                    hudSurface.SetState(hs, hs == "error" ? "בדיקה" : "");
                hudSurface.SetState("listening");        // fresh session
                hudSurface.SetWords("שלום עולם");        // live words stream in
                hudSurface.SetState("paused");           // pause keeps the same session words
                wordsDuringPause = hudSurface.CurrentWordsForTest;
                hudSurface.SetState("listening");        // resume keeps them too
                hudSurface.SetTarget("Word");            // confident, injector-aligned target
                targetWhileListening = hudSurface.CurrentTargetForTest;
                hudSurface.SetTarget("");                // unknown/unsafe target -> non-claiming state, not a wrong claim
                targetSafeState = hudSurface.CurrentTargetForTest;
                hudSurface.SetTarget("Word");            // back to a known target
                hudSurface.SetTargetChanged(true);       // window detached -> amber "target changed"
                bool targetChangedShown = hudSurface.TargetChangedForTest;
                hudSurface.SetTargetChanged(false);      // transient: next normal status clears it
                bool targetChangedCleared = !hudSurface.TargetChangedForTest && hudSurface.CurrentTargetForTest == "יעד: Word";
                targetChangedOk = targetChangedShown && targetChangedCleared;
                hudSurface.SetFallback(true);            // cloud dropped -> offline backup notice
                hudSurface.SetState("listening");        // repeated status refresh must NOT wipe them
                fallbackShown = hudSurface.FallbackVisibleForTest;   // latched + still shown
                wordsAfterRefresh = hudSurface.CurrentWordsForTest;
                hudSurface.SetState("idle");             // leaving listening clears target + fallback
                targetAfterStop = hudSurface.CurrentTargetForTest;
                fallbackClearedOnStop = !hudSurface.FallbackVisibleForTest;
                hudSurface.SetState("listening");        // restore for the no-steal/visibility checks below
            }
            catch { hudStates = false; }

            hudSurface.Window.AppWindow.Show(false);   // show no-activate, exactly as AppHost does
            await Task.Delay(200);
            long hudSurfaceEx = Native.GetExStyle(hudSurface.Hwnd);
            IntPtr fgPostHud = Native.GetForegroundWindow();
            Check("hud.starts_hidden", hiddenAtStart, "overlay constructed hidden, shown only after config");
            Check("hud.surface.noactivate", (hudSurfaceEx & Native.WS_EX_NOACTIVATE) != 0, $"exStyle=0x{hudSurfaceEx:X}");
            Check("hud.surface.no_steal", hudSurface.Window.AppWindow.IsVisible && fgPostHud == fgPreHud,
                  "shown no-activate, did not take foreground");
            Check("hud.surface.states", hudStates, "SetState morphs through all states + words");
            Check("hud.words.preserved", wordsAfterRefresh == "שלום עולם",
                  $"live words survive a repeated 'listening' refresh (got '{wordsAfterRefresh}')");
            Check("hud.pause.words_preserved", wordsDuringPause == "שלום עולם",
                  $"pause keeps live words visible but muted (got '{wordsDuringPause}')");
            Check("hud.target.reassurance", targetWhileListening == "יעד: Word" && targetAfterStop == "",
                  $"shows target while listening, cleared on stop (got '{targetWhileListening}')");
            Check("hud.target.safe_state", targetSafeState == "יעד לא זוהה",
                  $"unknown/unsafe target shows a non-claiming state, never a destination claim (got '{targetSafeState}')");
            Check("hud.target.changed", targetChangedOk,
                  "target-changed shows amber warning, reverts to the target on the next status");
            Check("hud.fallback.notice", fallbackShown && fallbackClearedOnStop,
                  "offline-backup notice latches while listening, cleared on stop");
            hudSurface.Window.Close();

            // 6d) Production tray path: a top-level (broadcast-capable) window + health orb
            //     icon registered via the real TrayIcon (not the raw nid above).
            var trayInst = new TrayIcon();
            Check("tray.instance", trayInst.IsAdded, "real TrayIcon added (health orb + broadcast-capable window)");
            trayInst.Dispose();

            // 6e) First-run wizard: constructs and steps through all 5 stages; the Finish
            //     action appears only on the last step and Back returns. Navigation only —
            //     no config writes (host omitted), so the real first-run flag is untouched.
            try
            {
                var wiz = new OnboardingWindow(null!);
                int steps = wiz.StepCountForTest;
                for (int i = 0; i < steps - 1; i++) wiz.NextForTest();
                bool finishOnLast = wiz.CurrentStepForTest == steps - 1 && wiz.FinishVisibleForTest;
                wiz.BackForTest();
                bool backWorks = wiz.CurrentStepForTest == steps - 2 && !wiz.FinishVisibleForTest;
                Check("onboarding.navigation", steps == 5 && finishOnLast && backWorks,
                      $"5-step wizard navigates; Finish only on last step (steps={steps})");
            }
            catch (Exception ex) { Check("onboarding.navigation", false, XamlDetail(ex)); }

            // 6f) Engine mapping (pure, no writes): BOTH choices must run truly offline
            //     (whisper_local/local) — Recommended must NOT persist api/auto_fallback
            //     before credentials, since the cloud provider throws at startup. This is the
            //     single source of truth ApplyEngine uses.
            try
            {
                var off = new Dictionary<string, object>();
                foreach (var (k, v) in OnboardingWindow.EngineConfig("offline")) off[k] = v;
                var rec = new Dictionary<string, object>();
                foreach (var (k, v) in OnboardingWindow.EngineConfig("recommended")) rec[k] = v;

                bool Local(Dictionary<string, object> m) =>
                    m.TryGetValue("stt.mode", out var mode) && (string)mode == "local"
                    && m.TryGetValue("stt.provider", out var prov) && (string)prov == "whisper_local";
                bool recNotCloud = rec.TryGetValue("stt.mode", out var rm) && (string)rm != "api" && (string)rm != "auto_fallback";
                Check("onboarding.engine_map", Local(off) && Local(rec) && recNotCloud,
                      "Offline and Recommended both run local; Recommended never cloud without a key");
            }
            catch (Exception ex) { Check("onboarding.engine_map", false, ex.Message); }

            // 6g) Completion ordering invariant: the first-run flag may be written ONLY after
            //     the safe baseline persisted (regression guard for the ordering bug).
            Check("onboarding.flag_after_baseline",
                  !OnboardingWindow.MayMarkComplete(false) && OnboardingWindow.MayMarkComplete(true),
                  "first_run_completed gated on a successful offline baseline");

            // 6h) Honest offline-readiness rendering (no real download triggered): ready hides
            //     the install button; absent offers it; downloading shows the ring, no button.
            try
            {
                var wiz = new OnboardingWindow(null!);
                wiz.RenderReadinessForTest("ready");
                bool readyOk = !wiz.DownloadButtonVisibleForTest && wiz.OfflineNoteForTest.Contains("מוכנה");
                wiz.RenderReadinessForTest("absent");
                bool absentOk = wiz.DownloadButtonVisibleForTest;
                wiz.RenderReadinessForTest("downloading");
                bool dlOk = !wiz.DownloadButtonVisibleForTest && wiz.DownloadRingActiveForTest;
                Check("onboarding.offline_readiness", readyOk && absentOk && dlOk,
                      "offline note honest per model state; download offered only when not ready");
            }
            catch (Exception ex) { Check("onboarding.offline_readiness", false, XamlDetail(ex)); }

            // 6h.1) Controls-room advanced audio/VAD rendering: dependent timing controls stay
            //       disabled until their parent feature is enabled (render only; no RPC/audio).
            try
            {
                var cp = new Views.ControlsPage();
                cp.RenderRemoteForTest(remote: false, idleQuickStart: true);
                bool remoteIdleOk = !cp.RemoteToggleForTest && cp.IdleRemoteToggleForTest;
                cp.RenderAudioAdvancedForTest(vad: false, endpointing: true, autoStop: false);
                bool quietDefaults = !cp.VadControlsEnabledForTest
                                     && cp.AutoStopToggleEnabledForTest
                                     && !cp.AutoStopControlsEnabledForTest;
                cp.RenderAudioAdvancedForTest(vad: true, endpointing: true, autoStop: true);
                bool allEnabled = cp.VadControlsEnabledForTest
                                  && cp.AutoStopToggleEnabledForTest
                                  && cp.AutoStopControlsEnabledForTest;
                cp.RenderAudioAdvancedForTest(vad: true, endpointing: false, autoStop: true);
                bool endpointOff = cp.VadControlsEnabledForTest
                                   && !cp.AutoStopToggleEnabledForTest
                                   && !cp.AutoStopControlsEnabledForTest;
                Check("controls.audio_vad.surface", remoteIdleOk && quietDefaults && allEnabled && endpointOff,
                      "advanced audio/VAD controls and idle Remote toggle render honestly");
            }
            catch (Exception ex) { Check("controls.audio_vad.surface", false, XamlDetail(ex)); }

            // 6h.2) Optional audio feedback: render the Controls switch/volume and prove the
            //       generated WAV tones are valid without playing real speaker audio.
            try
            {
                var cp = new Views.ControlsPage();
                cp.RenderSoundForTest(enabled: false, volume: 35);
                bool offOk = !cp.SoundVolumeEnabledForTest && cp.SoundVolumeTextForTest == "35";
                cp.RenderSoundForTest(enabled: true, volume: 70);
                bool onOk = cp.SoundVolumeEnabledForTest && cp.SoundVolumeTextForTest == "70";

                string toneDir = Path.Combine(Path.GetTempPath(), "voicetype-selftest-tones-" + Guid.NewGuid().ToString("N"));
                string? startTone = AudioFeedbackPlayer.TonePath(toneDir, "start", 70);
                string? stopTone = AudioFeedbackPlayer.TonePath(toneDir, "stop", 70);
                bool tonesOk = startTone != null && stopTone != null
                               && startTone != stopTone
                               && AudioFeedbackPlayer.IsToneFileForTest(startTone)
                               && AudioFeedbackPlayer.IsToneFileForTest(stopTone);
                try { Directory.Delete(toneDir, recursive: true); } catch { }
                Check("controls.audio_feedback.surface", offOk && onOk && tonesOk,
                      "feedback switch/volume render and cached start/stop WAV tones generate");
            }
            catch (Exception ex) { Check("controls.audio_feedback.surface", false, XamlDetail(ex)); }

            // 6h.3) Dictation-room language assists: command-pack override, spoken emoji, phrase
            //       boost, and custom phrase box render without touching real credentials/audio.
            try
            {
                var dp = new Views.DictationPage();
                dp.RenderLanguageAssistForTest("en", spokenEmoji: true, phraseBoost: 9, new[] { "Codex", "VoiceType" });
                bool assistsOk = dp.SelectedCommandPackForTest == "en"
                                 && dp.SpokenEmojiForTest
                                 && dp.PhraseBoostTextForTest == "9"
                                 && dp.CustomPhrasesTextForTest.Contains("Codex")
                                 && dp.CustomPhrasesTextForTest.Contains("VoiceType");
                Check("dictation.language_assists.surface", assistsOk,
                      "command pack, spoken emoji, phrase boost, and custom phrase controls render");
            }
            catch (Exception ex) { Check("dictation.language_assists.surface", false, XamlDetail(ex)); }

            // 6h.4) Settings Labs gate: target live typing is visible as an experimental locked
            //       path, not a production-ready toggle.
            try
            {
                var sp = new Views.SettingsPage();
                sp.RenderLabsForTest(enabled: false, mode: "final_only", backend: "v1", tsf: false);
                bool labsOk = !sp.LabsLiveTypingEnabledForTest
                              && sp.LabsStatusForTest.Contains("Final-only")
                              && sp.LabsModeForTest.Contains("final_only")
                              && sp.LabsModeForTest.Contains("TSF: disabled");
                Check("settings.labs_gate.surface", labsOk,
                      "Settings renders live target typing as locked/final-only by default");
            }
            catch (Exception ex) { Check("settings.labs_gate.surface", false, XamlDetail(ex)); }

            // 6h.5) History privacy/search surface: render only, no real history mutation.
            try
            {
                var hp = new Views.HistoryPage();
                hp.RenderHistoryForTest(enabled: false, maxEntries: 500, count: 3, visibleItems: 0, query: "missing");
                bool historyOk = hp.PrivacyStatusForTest.Contains("3")
                                 && hp.HistoryActionsVisibleForTest
                                 && hp.HistoryEmptyVisibleForTest;
                var sp = new Views.SettingsPage();
                sp.RenderHistoryPrivacyForTest(enabled: false, historyLimit: 250);
                bool settingsPrivacyOk = !sp.HistoryEnabledForTest
                                         && !sp.HistoryLimitEnabledForTest
                                         && sp.HistoryLimitForTest == 250;
                Check("history.privacy.surface", historyOk && settingsPrivacyOk,
                      "History search/status and Settings save-history toggle render safely");
            }
            catch (Exception ex) { Check("history.privacy.surface", false, XamlDetail(ex)); }

            // 6i) Engine-room offline model management: download offered when absent, delete
            //     offered when present, ring while downloading (render only — no RPC/download).
            try
            {
                var ep = new Views.EnginePage();
                ep.RenderModelForTest("absent");
                bool absentOk = ep.ModelDownloadVisibleForTest && !ep.ModelDeleteVisibleForTest;
                ep.RenderModelForTest("ready");
                bool readyOk = !ep.ModelDownloadVisibleForTest && ep.ModelDeleteVisibleForTest;
                ep.RenderModelForTest("downloading");
                bool dlOk = ep.ModelRingActiveForTest && !ep.ModelDownloadVisibleForTest;
                ep.RenderModelForTest("incomplete");
                bool incompleteOk = ep.ModelDownloadVisibleForTest
                                    && !ep.ModelDeleteVisibleForTest
                                    && !ep.ModelRingActiveForTest;
                Check("engine.model_management", absentOk && readyOk && dlOk && incompleteOk,
                      "download when absent/incomplete, delete when present, ring while downloading");
                ep.RenderSmartAutoForTest("Smart Auto route ready");
                Check("engine.smart_auto.surface",
                      ep.SmartAutoCardVisibleForTest && ep.SmartAutoStatusForTest.Contains("route", StringComparison.OrdinalIgnoreCase),
                      "Smart Auto routing card renders status text");
            }
            catch (Exception ex) { Check("engine.model_management", false, XamlDetail(ex)); }

            // 7) Disconnect surfacing: a dead engine must raise BridgeClient.Disconnected
            //    so the shell can drop to a recoverable "disconnected" state (not hang).
            try { if (bridge is { HasExited: false }) bridge.Kill(true); } catch { }
            bool sawDisconnect = disconnected.Wait(TimeSpan.FromSeconds(4));
            Check("bridge.disconnect", sawDisconnect,
                  sawDisconnect ? "Disconnected raised after engine kill" : "no Disconnected within 4s");

            hud.Close(); remote.Close();
        }
        catch (Exception ex)
        {
            Check("selftest.fatal", false, ex.ToString());
        }
        finally
        {
            WriteReport(reportPath);
            try { if (bridge is { HasExited: false }) bridge.Kill(true); } catch { }
            Environment.Exit(Results.Count > 0 && Results.All(r => r.ok) ? 0 : 1);
        }
    }

    private static (Window window, IntPtr hwnd) MakeOverlayWindow(string title, bool clickThrough,
                                                                 int x, int y, int w, int h)
    {
        var window = new Window { Title = title };
        window.Content = new Grid
        {
            FlowDirection = FlowDirection.RightToLeft,
            Children = { new TextBlock { Text = title, Margin = new Thickness(16) } }
        };
        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(window);

        var presenter = OverlappedPresenter.CreateForToolWindow();
        presenter.IsAlwaysOnTop = true;
        presenter.IsResizable = false;
        presenter.SetBorderAndTitleBar(false, false);
        window.AppWindow.SetPresenter(presenter);
        window.AppWindow.MoveAndResize(new RectInt32(x, y, w, h));

        Native.MakeOverlay(hwnd, clickThrough);   // WS_EX_NOACTIVATE | TOPMOST | (TRANSPARENT)
        window.AppWindow.Show(activateWindow: false);  // show WITHOUT stealing focus
        return (window, hwnd);
    }

    private static void WriteReport(string path)
    {
        int pass = Results.Count(r => r.ok);
        var sb = new StringBuilder();
        sb.AppendLine("VoiceType WinUI runtime self-test");
        sb.AppendLine($"timestamp: {DateTime.Now:O}");
        sb.AppendLine($"result: {pass}/{Results.Count} passed");
        sb.AppendLine($"report: {path}");
        sb.AppendLine(new string('-', 60));
        foreach (var (name, ok, detail) in Results)
            sb.AppendLine($"[{(ok ? "PASS" : "FAIL")}] {name}{(detail.Length > 0 ? " — " + detail : "")}");
        string body = sb.ToString();

        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            File.WriteAllText(path, body, new UTF8Encoding(true));
        }
        catch (Exception ex)
        {
            // Do NOT swallow: a missing/locked/unwritable report path must be visible, or packaged
            // verification could "run" while leaving nothing to inspect. Fall back to TEMP with a
            // loud header AND drop a breadcrumb next to the exe so the failure can't be silent.
            bool fbOk = false;
            string fb = Path.Combine(Path.GetTempPath(), "winui_runtime_report.txt");
            try
            {
                File.WriteAllText(fb,
                    $"PRIMARY REPORT WRITE FAILED for '{path}': {ex.GetType().Name}: {ex.Message}\r\n\r\n{body}",
                    new UTF8Encoding(true));
                fbOk = true;
            }
            catch { }
            try
            {
                File.WriteAllText(Path.Combine(AppContext.BaseDirectory, "SELFTEST-REPORT-WRITE-FAILED.txt"),
                    $"Could not write the self-test report to '{path}'.\r\n{ex}\r\n" +
                    $"Fallback: {(fbOk ? fb : "ALSO FAILED")}\r\n", new UTF8Encoding(true));
            }
            catch { }
        }
    }
}
