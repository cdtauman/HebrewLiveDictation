using System;
using System.Diagnostics;
using System.IO;
using System.Text.Json;
using System.Threading.Tasks;
using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml;

namespace VoiceType.Shell;

/// <summary>
/// Ties the interactive WinUI shell to the Python engine sidecar: spawns the bridge,
/// owns the tray icon, the console (MainWindow, hide-to-tray), and — in --show mode —
/// the live HUD and draggable Remote. Created on the UI thread from App.OnLaunched.
/// </summary>
public sealed class AppHost
{
    public BridgeClient Client { get; } = new BridgeClient();
    public bool IsExiting { get; private set; }

    private Process? _bridge;
    private MainWindow? _main;
    private TrayIcon? _tray;
    private HudWindow? _hud;
    private RemoteWindow? _remote;
    private DispatcherQueue _ui = null!;

    public async Task RunAsync(bool showOverlays)
    {
        _ui = DispatcherQueue.GetForCurrentThread();
        _bridge = StartBridge();
        Client.EventReceived += OnEvent;

        _tray = new TrayIcon();
        _tray.ShowRequested += ShowConsole;
        _tray.StartRequested += StartDictation;
        _tray.StopRequested += StopDictation;
        _tray.ExitRequested += Exit;

        _main = new MainWindow(this);
        _main.Activate();
        _main.SetBridgeStatus((_tray.IsAdded ? "tray active" : "tray FAILED") + " · מתחבר…");

        if (showOverlays)
        {
            _hud = new HudWindow();
            _remote = new RemoteWindow(this);
            _main.Log("HUD + Remote shown (no-activate, topmost).");
        }

        try
        {
            await Client.ConnectAsync(20000);
            _main.SetBridgeStatus("connected ✓");
            var st = await Client.RpcAsync("getStatus");
            _main.SetEngineState(st.GetProperty("state").GetString() ?? "?");
        }
        catch (Exception ex)
        {
            _main.SetBridgeStatus("connect failed: " + ex.Message);
        }
    }

    private void OnEvent(JsonElement e)
    {
        string? kind = e.TryGetProperty("kind", out var k) ? k.GetString() : null;
        _ui.TryEnqueue(() =>
        {
            switch (kind)
            {
                case "status":
                    string state = e.TryGetProperty("state", out var s) ? s.GetString() ?? "" : "";
                    string msg = e.TryGetProperty("message", out var m) ? m.GetString() ?? "" : "";
                    _main?.SetEngineState(state);
                    _hud?.SetStatus(string.IsNullOrEmpty(msg) ? state : msg);
                    _main?.Log($"status: {state} {msg}");
                    break;
                case "text":
                    _hud?.SetWords(e.TryGetProperty("text", out var tx) ? tx.GetString() ?? "" : "");
                    break;
                case "error":
                    string em = e.TryGetProperty("message", out var me) ? me.GetString() ?? "" : "";
                    _hud?.SetStatus("⚠ " + em);
                    _main?.Log("error: " + em);
                    break;
                case "hotkey":
                    _main?.Log("hotkey: " + (e.TryGetProperty("edge", out var ed) ? ed.GetString() : ""));
                    break;
            }
        });
    }

    public async void StartDictation() { try { await Client.RpcAsync("startDictation", new { mode = "external" }); } catch { } }
    public async void StopDictation() { try { await Client.RpcAsync("stopDictation"); } catch { } }

    public void ShowConsole() => _ui.TryEnqueue(() =>
    {
        _main?.AppWindow.Show();
        if (_main != null)
            Native.SetForegroundWindow(WinRT.Interop.WindowNative.GetWindowHandle(_main));
    });

    public async void Exit()
    {
        IsExiting = true;
        try { await Client.RpcAsync("shutdown"); } catch { }
        try { _tray?.Dispose(); } catch { }
        try { if (_bridge is { HasExited: false }) _bridge.Kill(true); } catch { }
        Application.Current.Exit();
    }

    private static Process? StartBridge()
    {
        try { return Process.Start(RepoPaths.SidecarStartInfo(RepoPaths.FindRoot())); }
        catch { return null; }
    }
}
