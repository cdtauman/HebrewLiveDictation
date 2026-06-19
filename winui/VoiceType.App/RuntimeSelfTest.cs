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

    public static async Task RunAsync()
    {
        Process? bridge = null;
        var events = new List<JsonElement>();
        string repoRoot = RepoPaths.FindRoot();
        string reportPath = Path.Combine(repoRoot, "winui", "winui_runtime_report.txt");

        var (pipeShort, pipeFull) = RepoPaths.NewPipe("voicetype-selftest");
        try
        {
            // 1) Spawn the Python engine bridge on a unique pipe (stdout/stderr drained).
            bridge = RepoPaths.StartSidecar(repoRoot, pipeFull);
            Check("bridge.spawn", bridge != null && !bridge.HasExited,
                  bridge != null ? $"pid={bridge.Id}" : "failed to start");

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

                // Destructive-RPC guard: clearHistory WITHOUT a confirm flag must refuse
                // (so this is safe to run — it never wipes the real store).
                var clr = await client.RpcAsync("clearHistory");
                Check("bridge.clearHistory.guard",
                      clr.TryGetProperty("cleared", out var cl) && !cl.GetBoolean(),
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
            try
            {
                foreach (var hs in new[] { "connecting", "idle", "listening", "stopping", "error", "disconnected" })
                    hudSurface.SetState(hs, hs == "error" ? "בדיקה" : "");
                hudSurface.SetState("listening");        // fresh session
                hudSurface.SetWords("שלום עולם");        // live words stream in
                hudSurface.SetState("listening");        // repeated status refresh must NOT wipe them
                wordsAfterRefresh = hudSurface.CurrentWordsForTest;
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
            hudSurface.Window.Close();

            // 6d) Production tray path: a top-level (broadcast-capable) window + health orb
            //     icon registered via the real TrayIcon (not the raw nid above).
            var trayInst = new TrayIcon();
            Check("tray.instance", trayInst.IsAdded, "real TrayIcon added (health orb + broadcast-capable window)");
            trayInst.Dispose();

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
            Application.Current.Exit();
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
        sb.AppendLine(new string('-', 60));
        foreach (var (name, ok, detail) in Results)
            sb.AppendLine($"[{(ok ? "PASS" : "FAIL")}] {name}{(detail.Length > 0 ? " — " + detail : "")}");
        try { File.WriteAllText(path, sb.ToString(), new UTF8Encoding(true)); } catch { }
    }
}
