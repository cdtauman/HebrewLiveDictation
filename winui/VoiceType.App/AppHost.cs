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
        Client.Disconnected += OnBridgeDisconnected;

        _tray = new TrayIcon();
        _tray.ShowRequested += ShowConsole;
        _tray.StartRequested += StartDictation;
        _tray.StopRequested += StopDictation;
        _tray.ExitRequested += Exit;
        if (!_tray.IsAdded) AppLog.Add("tray failed to register");

        CurrentState = "connecting";
        _main = new MainWindow(this);
        _main.Activate();
        _main.SetEngineStatus("connecting", "");

        if (showOverlays)
        {
            _hud = new HudWindow();
            _remote = new RemoteWindow(this);
            _main.Log("HUD + Remote shown (no-activate, topmost).");
        }

        try
        {
            await Client.ConnectAsync(20000);
            var st = await Client.RpcAsync("getStatus");
            CurrentState = st.TryGetProperty("state", out var stState) ? stState.GetString() ?? "idle" : "idle";
            var connectedState = CurrentState;
            _ui.TryEnqueue(() => { _main?.SetEngineStatus(connectedState, ""); StatusChanged?.Invoke(connectedState, ""); });
        }
        catch (Exception ex)
        {
            CurrentState = "disconnected";
            var msg = ex.Message;
            _ui.TryEnqueue(() => { _main?.SetEngineStatus("disconnected", msg); StatusChanged?.Invoke("disconnected", msg); });
        }
    }

    private void OnBridgeDisconnected()
    {
        if (IsExiting) return;
        _ui.TryEnqueue(() =>
        {
            CurrentState = "disconnected";
            CurrentMessage = "";
            _main?.SetEngineStatus("disconnected", "");
            StatusChanged?.Invoke("disconnected", "");
        });
    }

    /// <summary>Recover from a dead engine: respawn the sidecar on a fresh pipe and reconnect.</summary>
    public async void RestartEngine()
    {
        AppLog.Add("restarting engine…");
        try { if (_bridge is { HasExited: false }) _bridge.Kill(true); } catch { }
        try { Client?.Dispose(); } catch { }

        var (pipeShort, pipeFull) = RepoPaths.NewPipe();
        Client = new BridgeClient(pipeShort);
        Client.EventReceived += OnEvent;
        Client.Disconnected += OnBridgeDisconnected;
        _bridge = RepoPaths.StartSidecar(RepoPaths.FindRoot(), pipeFull, line => AppLog.Add("sidecar: " + line));

        CurrentState = "connecting";
        _main?.SetEngineStatus("connecting", "");
        StatusChanged?.Invoke("connecting", "");
        try
        {
            await Client.ConnectAsync(20000);
            var st = await Client.RpcAsync("getStatus");
            CurrentState = st.TryGetProperty("state", out var s) ? s.GetString() ?? "idle" : "idle";
            var ns = CurrentState;
            _ui.TryEnqueue(() => { _main?.SetEngineStatus(ns, ""); StatusChanged?.Invoke(ns, ""); });
        }
        catch (Exception ex)
        {
            var msg = ex.Message;
            _ui.TryEnqueue(() => { CurrentState = "disconnected"; _main?.SetEngineStatus("disconnected", msg); StatusChanged?.Invoke("disconnected", msg); });
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
                    _main?.SetEngineStatus(CurrentState, CurrentMessage);
                    _hud?.SetStatus(string.IsNullOrEmpty(msg) ? state : msg);
                    _main?.Log($"status: {state} {msg}");
                    StatusChanged?.Invoke(CurrentState, CurrentMessage);
                    break;
                case "text":
                    _hud?.SetWords(e.TryGetProperty("text", out var tx) ? tx.GetString() ?? "" : "");
                    break;
                case "error":
                    string em = e.TryGetProperty("message", out var me) ? me.GetString() ?? "" : "";
                    CurrentState = "error";
                    CurrentMessage = em;
                    _hud?.SetStatus("⚠ " + em);
                    _main?.SetEngineStatus("error", em);
                    _main?.Log("error: " + em);
                    StatusChanged?.Invoke("error", em);
                    break;
                case "hotkey":
                    _main?.Log("hotkey: " + (e.TryGetProperty("edge", out var ed) ? ed.GetString() : ""));
                    break;
            }
        });
    }

    public async void StartDictation() { try { await Client.RpcAsync("startDictation", new { mode = "external" }); } catch (Exception ex) { AppLog.Add("startDictation failed: " + ex.Message); } }
    public async void StopDictation() { try { await Client.RpcAsync("stopDictation"); } catch (Exception ex) { AppLog.Add("stopDictation failed: " + ex.Message); } }

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
