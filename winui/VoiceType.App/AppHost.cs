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
    public BridgeClient Client { get; private set; } = null!;
    public bool IsExiting { get; private set; }

    /// <summary>Latest engine state ("idle"|"listening"|"stopping"|"error") + message.
    /// Raised on the UI thread so views (e.g. Home) can reflect it live.</summary>
    public string CurrentState { get; private set; } = "idle";
    public string CurrentMessage { get; private set; } = "";
    public event Action<string, string>? StatusChanged;

    private Process? _bridge;
    private MainWindow? _main;
    private TrayIcon? _tray;
    private HudWindow? _hud;
    private RemoteWindow? _remote;
    private DispatcherQueue _ui = null!;

    public async Task RunAsync(bool showOverlays)
    {
        _ui = DispatcherQueue.GetForCurrentThread();

        // Per-launch unique pipe: the client can only ever attach to the sidecar we
        // spawn here, never a stale/orphan one. stdout/stderr are drained into AppLog.
        var (pipeShort, pipeFull) = RepoPaths.NewPipe();
        Client = new BridgeClient(pipeShort);
        _bridge = RepoPaths.StartSidecar(RepoPaths.FindRoot(), pipeFull, line => AppLog.Add("sidecar: " + line));
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
            CurrentState = st.TryGetProperty("state", out var stState) ? stState.GetString() ?? "idle" : "idle";
            _main.SetEngineState(CurrentState);
            var connectedState = CurrentState;
            _ui.TryEnqueue(() => StatusChanged?.Invoke(connectedState, ""));
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
                    CurrentState = string.IsNullOrEmpty(state) ? CurrentState : state;
                    CurrentMessage = msg;
                    _main?.SetEngineState(state);
                    _hud?.SetStatus(string.IsNullOrEmpty(msg) ? state : msg);
                    _main?.Log($"status: {state} {msg}");
                    StatusChanged?.Invoke(CurrentState, CurrentMessage);
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

}
