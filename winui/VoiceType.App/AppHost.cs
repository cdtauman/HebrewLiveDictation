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
/// owns the tray icon, the console (MainWindow, hide-to-tray), and the signature
/// surfaces — the live HUD and draggable Remote, shown per config (Controls room;
/// --show forces both). Created on the UI thread from App.OnLaunched.
/// </summary>
public sealed class AppHost
{
    public BridgeClient Client { get; private set; } = null!;
    public bool IsExiting { get; private set; }

    /// <summary>The console window — used by rooms that need its HWND (e.g. file pickers,
    /// which require InitializeWithWindow in unpackaged WinUI).</summary>
    public MainWindow? Console => _main;

    /// <summary>Latest engine state ("idle"|"listening"|"stopping"|"error") + message.
    /// Raised on the UI thread so views (e.g. Home) can reflect it live.</summary>
    public string CurrentState { get; private set; } = "idle";
    public string CurrentMessage { get; private set; } = "";
    public event Action<string, string>? StatusChanged;

    /// <summary>Local-model download progress (state = "running"|"done"|"error", model name,
    /// message). The model name is carried through so the surfaces stay correct under future
    /// multi-model support. Raised on the UI thread.</summary>
    public event Action<string, string, string>? ModelDownloadChanged;

    /// <summary>Raised when a dictation start was refused because offline is the live engine but
    /// no model is installed (Option A: no silent auto-download). Handled by the console to route
    /// the user to the explicit download flow (Engine room). UI thread.</summary>
    public event Action? OfflineModelRequired;

    /// <summary>Cached "minimize to tray on close" choice (Settings room). Read on connect
    /// and updated live by Settings so the synchronous window-close handler can honor it
    /// without an IPC round-trip. Defaults to the engine default (true).</summary>
    public bool MinimizeOnClose { get; set; } = true;

    private Process? _bridge;
    private MainWindow? _main;
    private TrayIcon? _tray;
    private HudWindow? _hud;
    private RemoteWindow? _remote;
    private DispatcherQueue _ui = null!;

    public async Task RunAsync(bool showOverlays)
    {
        _ui = DispatcherQueue.GetForCurrentThread();

        // Durable session marker (always written, so shell.log exists for support even on a clean run).
        AppLog.Add($"shell session start — engine launch mode: {RepoPaths.EngineLaunchMode()}");

        // Per-launch unique pipe: the client can only ever attach to the sidecar we
        // spawn here, never a stale/orphan one. stdout/stderr are drained into AppLog.
        var (pipeShort, pipeFull) = RepoPaths.NewPipe();
        Client = new BridgeClient(pipeShort);
        _bridge = RepoPaths.StartSidecar(RepoPaths.FindRoot(), pipeFull, line => AppLog.Add("sidecar: " + line));
        Wire(Client);
        var client = Client;

        _tray = new TrayIcon();
        _tray.ShowRequested += ShowConsole;
        _tray.StartRequested += StartDictation;
        _tray.StopRequested += StopDictation;
        _tray.ExitRequested += Exit;
        if (!_tray.IsAdded) AppLog.Add("tray failed to register");

        CurrentState = "connecting";
        _main = new MainWindow(this);
        _main.Activate();

        // The signature surfaces live at the cursor, not behind a debug flag: create them
        // always and drive visibility from config (Controls room). --show forces both on.
        _hud = new HudWindow();
        _remote = new RemoteWindow(this);
        ApplyEngineState("connecting", "");

        await ConnectAndSyncAsync(client);
        await ApplyAppPreferencesAsync();
        await MaybeRunOnboardingAsync();
        await ApplyOverlayVisibilityAsync(showOverlays);
    }

    /// <summary>On a genuine first run (app.first_run_completed not yet true), present the
    /// setup wizard and wait for it to close before showing the overlays. The wizard
    /// persists every choice through the engine and sets the flag itself, so a normal
    /// finish — or a skip — never shows it again. If the flag can't be read (bridge issue)
    /// we do NOT block startup on a wizard.</summary>
    private async Task MaybeRunOnboardingAsync()
    {
        if (await TryGetBoolConfig("app.first_run_completed") != false) return;

        var tcs = new TaskCompletionSource();
        OnboardingWindow? wiz = null;
        _ui.TryEnqueue(() =>
        {
            try
            {
                wiz = new OnboardingWindow(this);
                wiz.Closed += (_, __) => tcs.TrySetResult();
                wiz.Activate();
            }
            catch (Exception ex) { AppLog.Add("onboarding failed: " + ex.Message); tcs.TrySetResult(); }
        });
        await tcs.Task;
    }

    /// <summary>Apply the persisted shell preferences (Settings room) once the engine is
    /// reachable: color theme (live) and the minimize-on-close choice (cached for the
    /// synchronous close handler). Silently no-ops if the values can't be read.</summary>
    private async Task ApplyAppPreferencesAsync()
    {
        string theme = await TryGetStringConfig("app.theme") ?? "light";
        _ui.TryEnqueue(() => _main?.ApplyTheme(theme));
        if (await TryGetBoolConfig("app.minimize_on_close") is bool m) MinimizeOnClose = m;
    }

    private async Task<string?> TryGetStringConfig(string key)
    {
        try
        {
            var r = await Client.RpcAsync("getConfig", new { key });
            if (r.TryGetProperty("value", out var v) && v.ValueKind == JsonValueKind.String)
                return v.GetString();
        }
        catch { }
        return null;
    }

    /// <summary>Live show/hide of the Voice HUD (Controls room toggle), no focus steal.</summary>
    public void SetHudVisible(bool visible) => _ui.TryEnqueue(() =>
    {
        try { if (_hud != null) { if (visible) _hud.Window.AppWindow.Show(false); else _hud.Window.AppWindow.Hide(); } } catch { }
    });

    /// <summary>Live show/hide of the Remote (Controls room toggle), no focus steal.</summary>
    public void SetRemoteVisible(bool visible) => _ui.TryEnqueue(() =>
    {
        try { if (_remote != null) { if (visible) _remote.Window.AppWindow.Show(false); else _remote.Window.AppWindow.Hide(); } } catch { }
    });

    private async Task ApplyOverlayVisibilityAsync(bool forceShow)
    {
        if (forceShow) { SetHudVisible(true); SetRemoteVisible(true); return; }

        // Only surface an overlay when we have actually read the user's choice from the
        // engine and it says "visible". If the bridge is unreachable or the config read
        // fails, the value is unknown → keep both hidden. Never default-show something the
        // user may have turned off just because we couldn't reach the engine.
        SetHudVisible(await TryGetBoolConfig("app.show_overlay") == true);
        SetRemoteVisible(await TryGetBoolConfig("toolbar.enabled") == true);
    }

    /// <summary>Read a boolean config value, or null when the value can't be established
    /// (bridge down, RPC failure, missing/non-bool value). Callers treat null as "keep hidden".</summary>
    private async Task<bool?> TryGetBoolConfig(string key)
    {
        try
        {
            var r = await Client.RpcAsync("getConfig", new { key });
            if (r.TryGetProperty("value", out var v))
            {
                if (v.ValueKind == JsonValueKind.True) return true;
                if (v.ValueKind == JsonValueKind.False) return false;
            }
        }
        catch { }
        return null;
    }

    /// <summary>Subscribe a client's event + disconnect callbacks, tagged with the client
    /// identity so a stale client from a previous engine can never drive the UI after a
    /// restart.</summary>
    private void Wire(BridgeClient client)
    {
        client.EventReceived += e => OnEvent(client, e);
        client.Disconnected += () => OnBridgeDisconnected(client);
    }

    /// <summary>Connect, read initial status, and publish it — but only if this client is
    /// still the current one when the (awaited) results land.</summary>
    private async Task ConnectAndSyncAsync(BridgeClient client)
    {
        try
        {
            await client.ConnectAsync(20000);
            var st = await client.RpcAsync("getStatus");
            var connectedState = st.TryGetProperty("state", out var s) ? s.GetString() ?? "idle" : "idle";
            _ui.TryEnqueue(() =>
            {
                if (client != Client) return;             // superseded by a newer engine
                CurrentState = connectedState;
                ApplyEngineState(connectedState, "");
                StatusChanged?.Invoke(connectedState, "");
            });
        }
        catch (Exception ex)
        {
            var msg = ex.Message;
            _ui.TryEnqueue(() =>
            {
                if (client != Client) return;
                CurrentState = "disconnected";
                ApplyEngineState("disconnected", msg);
                StatusChanged?.Invoke("disconnected", msg);
            });
        }
    }

    /// <summary>Push one engine state to every status surface at once — console pane
    /// footer, Voice HUD, Remote, and tray orb — so all four stay in lockstep. UI thread only.</summary>
    private void ApplyEngineState(string state, string message)
    {
        _main?.SetEngineStatus(state, message);
        _hud?.SetState(state, message);
        _remote?.SetState(state);
        _tray?.SetHealth(state);
    }

    private void OnBridgeDisconnected(BridgeClient source)
    {
        if (IsExiting) return;
        _ui.TryEnqueue(() =>
        {
            if (source != Client) return;                 // an old engine we already replaced
            CurrentState = "disconnected";
            CurrentMessage = "";
            ApplyEngineState("disconnected", "");
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
        var client = new BridgeClient(pipeShort);
        Wire(client);
        Client = client;                                   // becomes current before any await
        _bridge = RepoPaths.StartSidecar(RepoPaths.FindRoot(), pipeFull, line => AppLog.Add("sidecar: " + line));

        CurrentState = "connecting";
        ApplyEngineState("connecting", "");
        StatusChanged?.Invoke("connecting", "");
        await ConnectAndSyncAsync(client);
    }

    private void OnEvent(BridgeClient source, JsonElement e)
    {
        string? kind = e.TryGetProperty("kind", out var k) ? k.GetString() : null;
        _ui.TryEnqueue(() =>
        {
            if (source != Client) return;                 // stale client from a previous engine
            switch (kind)
            {
                case "status":
                    string state = e.TryGetProperty("state", out var s) ? s.GetString() ?? "" : "";
                    string msg = e.TryGetProperty("message", out var m) ? m.GetString() ?? "" : "";
                    string target = e.TryGetProperty("target", out var tg) ? tg.GetString() ?? "" : "";
                    bool fallback = e.TryGetProperty("fallback", out var fb) && fb.ValueKind == JsonValueKind.True;
                    bool targetChanged = e.TryGetProperty("targetChanged", out var tc) && tc.ValueKind == JsonValueKind.True;
                    bool needsModel = e.TryGetProperty("needsModel", out var nm) && nm.ValueKind == JsonValueKind.True;
                    CurrentState = string.IsNullOrEmpty(state) ? CurrentState : state;
                    CurrentMessage = msg;
                    ApplyEngineState(CurrentState, CurrentMessage);
                    _hud?.SetTarget(target);   // "יעד: {app}" reassurance while listening
                    _hud?.SetTargetChanged(targetChanged);   // amber "target changed — not written"
                    _hud?.SetFallback(fallback);   // amber "offline backup active" when cloud dropped
                    _main?.Log($"status: {state} {msg}");
                    StatusChanged?.Invoke(CurrentState, CurrentMessage);
                    // Offline start refused for lack of a model: bring the console forward and
                    // route the user to the explicit download flow (Engine room).
                    if (needsModel) { ShowConsole(); OfflineModelRequired?.Invoke(); }
                    break;
                case "text":
                    _hud?.SetWords(e.TryGetProperty("text", out var tx) ? tx.GetString() ?? "" : "");
                    break;
                case "error":
                    string em = e.TryGetProperty("message", out var me) ? me.GetString() ?? "" : "";
                    bool errNeedsModel = e.TryGetProperty("needsModel", out var enm) && enm.ValueKind == JsonValueKind.True;
                    CurrentState = "error";
                    CurrentMessage = em;
                    ApplyEngineState("error", em);
                    _main?.Log("error: " + em);
                    StatusChanged?.Invoke("error", em);
                    // The offline provider refused for a missing model (e.g. auto_fallback
                    // switched to local mid-session): route to the explicit download flow.
                    if (errNeedsModel) { ShowConsole(); OfflineModelRequired?.Invoke(); }
                    break;
                case "hotkey":
                    _main?.Log("hotkey: " + (e.TryGetProperty("edge", out var ed) ? ed.GetString() : ""));
                    break;
                case "modelDownload":
                    string mdState = e.TryGetProperty("state", out var mds) ? mds.GetString() ?? "" : "";
                    string mdName = e.TryGetProperty("name", out var mdn) ? mdn.GetString() ?? "" : "";
                    string mdMsg = e.TryGetProperty("message", out var mdm) ? mdm.GetString() ?? "" : "";
                    ModelDownloadChanged?.Invoke(mdState, mdName, mdMsg);
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
