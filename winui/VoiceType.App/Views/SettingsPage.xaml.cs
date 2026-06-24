using System;
using System.Reflection;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;
using Windows.ApplicationModel.DataTransfer;
using Windows.System;

namespace VoiceType.Shell.Views;

/// <summary>
/// Settings room: appearance (theme — applied live), startup/close behavior, an Advanced
/// door (history limit + a note that expert engine options come later), Diagnostics, and
/// About. The engine stays the single config writer; "start with Windows" is the one OS-
/// level action and is mirrored from the actual registry state so it never lies.
/// </summary>
public sealed partial class SettingsPage : Page
{
    private AppHost? _host;
    private bool _loading;
    private string _theme = "light";   // last successfully-persisted theme (for live rollback)

    public SettingsPage() => this.InitializeComponent();

    protected override void OnNavigatedTo(NavigationEventArgs e)
    {
        _host = e.Parameter as AppHost;
        AboutText.Text = "VoiceType · גרסה " + AppVersion();
        _ = LoadAsync();
    }

    private async Task LoadAsync()
    {
        string theme = await GetString("app.theme", "light");
        bool minimize = await GetBool("app.minimize_on_close", true);
        bool historyEnabled = await GetBool("history.enabled", true);
        int historyLimit = await GetInt("history.max_entries", 500);
        bool startup = WindowsStartup.IsEnabled();   // real OS state, not just the saved value

        _theme = theme;
        DispatcherQueue.TryEnqueue(() =>
        {
            _loading = true;
            SelectTag(ThemeCombo, theme);
            MinimizeToggle.IsOn = minimize;
            StartupToggle.IsOn = startup;
            RenderHistoryPrivacy(historyEnabled, historyLimit);
            _loading = false;
        });

        await LoadLabsAsync();
        await LoadDiagnosticsAsync();
        await LoadUpdateStatusAsync();
    }

    private async void OnThemeChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_loading) return;
        string prev = _theme;
        string theme = (ThemeCombo.SelectedItem as FrameworkElement)?.Tag as string ?? "light";
        _host?.Console?.ApplyTheme(theme);            // live, even before the write lands
        if (await Persist("app.theme", theme)) _theme = theme;
        else _host?.Console?.ApplyTheme(prev);        // save failed — revert the live theme too
    }

    private async void OnMinimizeToggled(object sender, RoutedEventArgs e)
    {
        if (_loading) return;
        if (await Persist("app.minimize_on_close", MinimizeToggle.IsOn) && _host != null)
            _host.MinimizeOnClose = MinimizeToggle.IsOn;   // keep the close handler in sync
    }

    private async void OnStartupToggled(object sender, RoutedEventArgs e)
    {
        if (_loading) return;
        bool want = StartupToggle.IsOn;
        bool osOk = WindowsStartup.Set(want);            // the actual auto-start behavior
        bool actual = WindowsStartup.IsEnabled();        // OS truth after the attempt — wins

        // Persist what the registry actually says, never the intent — config must not claim
        // startup is enabled/disabled unless the OS change really took.
        await Persist("app.start_with_windows", actual);
        if (!osOk || actual != want)
        {
            _loading = true;
            StartupToggle.IsOn = actual;
            _loading = false;
            await ShowMessageAsync("לא ניתן לעדכן את ההפעלה האוטומטית.", "נסו שוב.");
        }
    }

    private async void OnHistoryLimitChanged(NumberBox sender, NumberBoxValueChangedEventArgs args)
    {
        if (_loading) return;
        if (double.IsNaN(args.NewValue)) return;
        await Persist("history.max_entries", (int)args.NewValue);
    }

    private async void OnHistoryEnabledToggled(object sender, RoutedEventArgs e)
    {
        if (_loading) return;
        bool enabled = HistoryEnabledToggle.IsOn;
        HistoryLimitBox.IsEnabled = enabled;
        if (!await Persist("history.enabled", enabled))
            return;
    }

    private void RenderHistoryPrivacy(bool enabled, int historyLimit)
    {
        HistoryEnabledToggle.IsOn = enabled;
        HistoryLimitBox.Value = historyLimit;
        HistoryLimitBox.IsEnabled = enabled;
    }

    private async Task LoadUpdateStatusAsync()
    {
        bool enabled = false;
        bool endpoint = false;
        bool signingKey = false;
        string version = AppVersion();
        string channel = "";
        if (_host?.Client != null)
        {
            try
            {
                var status = await _host.Client.RpcAsync("getUpdateStatus");
                enabled = Bool(status, "enabled");
                endpoint = Bool(status, "endpointConfigured");
                signingKey = Bool(status, "signingKeyConfigured");
                version = Str(status, "currentVersion");
                channel = Str(status, "channel");
            }
            catch { }
        }
        DispatcherQueue.TryEnqueue(() => RenderUpdateStatus(enabled, endpoint, signingKey, version, channel, ""));
    }

    private async void OnUpdateEnabledToggled(object sender, RoutedEventArgs e)
    {
        if (_loading) return;
        bool enabled = UpdateEnabledToggle.IsOn;
        if (await Persist("updater.enabled", enabled))
            await LoadUpdateStatusAsync();
    }

    private async void OnCheckUpdates(object sender, RoutedEventArgs e)
    {
        if (_host?.Client == null) return;
        CheckUpdatesButton.IsEnabled = false;
        UpdateStatusText.Text = "בודק מניפסט עדכונים חתום...";
        try
        {
            var result = await _host.Client.RpcAsync("checkForUpdates", timeoutMs: 30000);
            await RenderUpdateResultAsync(result);
        }
        catch (Exception ex)
        {
            UpdateStatusText.Text = "בדיקת העדכונים נכשלה: " + ex.Message;
        }
        finally
        {
            CheckUpdatesButton.IsEnabled = true;
        }
    }

    private async Task RenderUpdateResultAsync(JsonElement result)
    {
        string status = Str(result, "status");
        string message = Str(result, "message");
        string version = "";
        string notes = "";
        string url = "";
        if (result.TryGetProperty("manifest", out var manifest) && manifest.ValueKind == JsonValueKind.Object)
        {
            version = Str(manifest, "version");
            notes = Str(manifest, "notes");
            url = Str(manifest, "url");
        }

        if (status == "update_available")
        {
            UpdateStatusText.Text = string.IsNullOrWhiteSpace(version)
                ? "זמין עדכון חתום."
                : $"זמין עדכון חתום: {version}. ההורדה וההתקנה הן ידניות.";
            await ShowUpdateDialogAsync(version, notes, url);
            return;
        }
        if (status == "up_to_date")
            UpdateStatusText.Text = "הגרסה הנוכחית עדכנית. " + message;
        else if (status == "blocked")
            UpdateStatusText.Text = "עדכון לא יוצע: " + message;
        else if (status == "disabled")
            UpdateStatusText.Text = "בדיקת עדכונים כבויה.";
        else if (status == "not_configured")
            UpdateStatusText.Text = "בדיקת עדכונים אינה מוגדרת: " + message;
        else if (status == "untrusted")
            UpdateStatusText.Text = "מניפסט העדכון לא אומת ונחסם.";
        else
            UpdateStatusText.Text = string.IsNullOrWhiteSpace(message) ? "בדיקת העדכונים נכשלה." : message;
    }

    private async Task ShowUpdateDialogAsync(string version, string notes, string url)
    {
        var dialog = new ContentDialog
        {
            Title = string.IsNullOrWhiteSpace(version) ? "זמין עדכון" : $"זמין עדכון {version}",
            Content = string.IsNullOrWhiteSpace(notes)
                ? "המניפסט אומת בחתימה. VoiceType לא מריץ מתקינים אוטומטית."
                : notes + "\n\nהמניפסט אומת בחתימה. VoiceType לא מריץ מתקינים אוטומטית.",
            PrimaryButtonText = "פתח הורדה",
            IsPrimaryButtonEnabled = !string.IsNullOrWhiteSpace(url),
            CloseButtonText = "סגור",
            DefaultButton = ContentDialogButton.Close,
            XamlRoot = this.XamlRoot,
            FlowDirection = FlowDirection.RightToLeft,
        };
        var choice = await dialog.ShowAsync();
        if (choice == ContentDialogResult.Primary && Uri.TryCreate(url, UriKind.Absolute, out var uri))
            await Launcher.LaunchUriAsync(uri);
    }

    private void RenderUpdateStatus(bool enabled, bool endpointConfigured, bool signingKeyConfigured,
                                    string version, string channel, string message)
    {
        _loading = true;
        UpdateEnabledToggle.IsOn = enabled;
        _loading = false;
        string configured = endpointConfigured && signingKeyConfigured ? "מוגדר" : "לא מוגדר";
        string prefix = enabled ? "בדיקת עדכונים פעילה" : "בדיקת עדכונים כבויה";
        string channelText = string.IsNullOrWhiteSpace(channel) ? "" : $" · ערוץ: {channel}";
        UpdateStatusText.Text = string.IsNullOrWhiteSpace(message)
            ? $"{prefix}. גרסה {version}{channelText}. מניפסט חתום: {configured}."
            : message;
    }

    private async Task LoadLabsAsync()
    {
        bool enabled = false;
        string mode = "final_only";
        string backend = "v1";
        bool tsf = false;
        bool liveInsert = false;
        string message = "Final-only target insertion is protected. Live words remain display-only in HUD/Remote.";

        if (_host?.Client != null)
        {
            try
            {
                var status = await _host.Client.RpcAsync("getLabsStatus");
                enabled = Bool(status, "liveTargetTypingEnabled");
                tsf = Bool(status, "tsfExperimentalTransport");
                mode = Str(status, "liveTypingMode");
                backend = Str(status, "inputBackend");
                liveInsert = Bool(status, "liveSegmentInsert");
                message = Str(status, "message");
            }
            catch { }
        }

        DispatcherQueue.TryEnqueue(() =>
        {
            RenderLabs(enabled, mode, backend, tsf, message);
            _loading = true;
            LiveInsertToggle.IsOn = liveInsert;
            _loading = false;
        });
    }

    private async void OnLiveInsertToggled(object sender, RoutedEventArgs e)
    {
        if (_loading) return;
        // Labs append mode (safe, opt-in): commit each completed segment during dictation.
        // Independent of the locked interim-rewrite live-typing gate; final-only stays default.
        await Persist("labs.live_segment_insert_enabled", LiveInsertToggle.IsOn);
    }

    private void RenderLabs(bool enabled, string mode, string backend, bool tsf, string message)
    {
        LabsLiveTypingToggle.IsOn = enabled;
        LabsStatusText.Text = enabled
            ? "Experimental Labs gate is open. Not approved for public beta."
            : message;
        LabsModeText.Text = $"target insertion: {mode}; backend: {backend}; TSF: {(tsf ? "enabled" : "disabled")}";
    }

    internal void RenderLabsForTest(bool enabled, string mode, string backend, bool tsf)
        => RenderLabs(enabled, mode, backend, tsf,
            "Final-only target insertion is protected. Live words remain display-only in HUD/Remote.");

    internal void RenderHistoryPrivacyForTest(bool enabled, int historyLimit)
        => RenderHistoryPrivacy(enabled, historyLimit);

    internal void RenderUpdateStatusForTest(bool enabled, bool endpointConfigured, bool signingKeyConfigured,
                                            string version, string channel, string message = "")
        => RenderUpdateStatus(enabled, endpointConfigured, signingKeyConfigured, version, channel, message);

    internal bool HistoryEnabledForTest => HistoryEnabledToggle.IsOn;
    internal bool HistoryLimitEnabledForTest => HistoryLimitBox.IsEnabled;
    internal int HistoryLimitForTest => (int)HistoryLimitBox.Value;
    internal bool UpdateEnabledForTest => UpdateEnabledToggle.IsOn;
    internal string UpdateStatusForTest => UpdateStatusText.Text;

    internal bool LabsLiveTypingEnabledForTest => LabsLiveTypingToggle.IsOn;
    internal string LabsStatusForTest => LabsStatusText.Text;
    internal string LabsModeForTest => LabsModeText.Text;
    internal bool LiveInsertEnabledForTest => LiveInsertToggle.IsOn;
    internal bool LiveInsertToggleEnabledForTest => LiveInsertToggle.IsEnabled;

    private async Task LoadDiagnosticsAsync()
    {
        string text = "המנוע אינו פעיל.";
        if (_host?.Client != null)
        {
            try
            {
                var diag = await _host.Client.RpcAsync("getDiagnosticsSnapshot");
                text = FormatDiagnostics(diag);
            }
            catch { text = "לא ניתן לקרוא את מצב המנוע."; }
        }
        DispatcherQueue.TryEnqueue(() => DiagnosticsText.Text = text);
    }

    private void OnCopyDiagnostics(object sender, RoutedEventArgs e)
    {
        try
        {
            var pkg = new DataPackage();
            pkg.SetText(DiagnosticsText.Text);
            Clipboard.SetContent(pkg);
        }
        catch { }
    }

    private static string FormatDiagnostics(JsonElement diag)
    {
        var state = Obj(diag, "state");
        var paths = Obj(diag, "paths");
        var runtime = Obj(diag, "runtime");
        var provider = Obj(diag, "provider");
        var routing = Obj(provider, "routing");
        var model = Obj(diag, "model");
        var target = Obj(diag, "target");
        var labs = Obj(diag, "labs");
        var update = Obj(diag, "update");
        var caps = Obj(diag, "capabilities");
        var insertion = Obj(caps, "insertion");

        var sb = new StringBuilder();
        sb.AppendLine("VoiceType diagnostics");
        sb.AppendLine("shell: VoiceType " + AppVersion());
        sb.AppendLine("shell launch: " + RepoPaths.EngineLaunchMode());
        sb.AppendLine("packaged engine: " + Redact(RepoPaths.PackagedEnginePath() ?? "(none)"));
        sb.AppendLine("engine state: " + Str(state, "engine"));
        sb.AppendLine("hotkeys: " + (Bool(state, "hotkeysActive") ? "active" : "inactive"));
        sb.AppendLine("pipe: " + Str(state, "pipe"));
        sb.AppendLine("");
        sb.AppendLine("provider:");
        sb.AppendLine("  effective: " + Str(provider, "effectiveProvider") + " / " + Str(routing, "effectiveLabel"));
        sb.AppendLine("  mode: " + Str(provider, "mode") + " stream: " + Str(provider, "stream"));
        sb.AppendLine("  start gate: " + Str(routing, "startGate"));
        sb.AppendLine("  backup: " + (Bool(routing, "backupReady") ? "ready" : "not ready"));
        sb.AppendLine("");
        sb.AppendLine("model:");
        sb.AppendLine("  " + Str(model, "name") + " state=" + Str(model, "state")
                      + " downloaded=" + (Bool(model, "downloaded") ? "true" : "false"));
        string modelPath = Redact(Str(model, "path"));
        if (!string.IsNullOrWhiteSpace(modelPath)) sb.AppendLine("  path: " + modelPath);
        sb.AppendLine("");
        sb.AppendLine("target:");
        sb.AppendLine("  usable=" + (Bool(target, "usable") ? "true" : "false")
                      + " label=" + Str(target, "label") + " process=" + Str(target, "process"));
        string reason = Str(target, "reason");
        if (!string.IsNullOrWhiteSpace(reason)) sb.AppendLine("  reason: " + reason);
        sb.AppendLine("");
        sb.AppendLine("package/runtime:");
        sb.AppendLine("  engine frozen=" + (Bool(runtime, "frozen") ? "true" : "false")
                      + " python=" + Str(runtime, "python") + " platform=" + Str(runtime, "platform"));
        sb.AppendLine("  executable: " + Redact(Str(runtime, "executable")));
        sb.AppendLine("  cwd: " + Redact(Str(runtime, "cwd")));
        sb.AppendLine("  insertion deps: comtypes=" + BoolText(insertion, "comtypes")
                      + " comtypes.client=" + BoolText(insertion, "comtypes_client")
                      + " uiautomation=" + BoolText(insertion, "uiautomation"));
        sb.AppendLine("");
        sb.AppendLine("updates/labs:");
        sb.AppendLine("  version=" + Str(update, "currentVersion")
                      + " updates=" + (Bool(update, "enabled") ? "enabled" : "disabled")
                      + " configured=" + (Bool(update, "endpointConfigured") && Bool(update, "signingKeyConfigured") ? "true" : "false"));
        sb.AppendLine("  labs=" + Str(labs, "gate")
                      + " insertion=" + Str(labs, "liveTypingMode") + "/" + Str(labs, "inputBackend"));
        sb.AppendLine("");
        sb.AppendLine("support files:");
        sb.AppendLine("  config: " + Redact(Str(paths, "configDir")));
        sb.AppendLine("  engine log: " + Redact(Str(paths, "engineLog")));
        sb.Append("  shell log: " + Redact(AppLog.FilePath ?? "(unavailable)"));
        return sb.ToString();
    }

    private static string BoolText(JsonElement o, string key) => Bool(o, key) ? "true" : "false";

    private static JsonElement Obj(JsonElement o, string key)
        => o.ValueKind == JsonValueKind.Object && o.TryGetProperty(key, out var v) && v.ValueKind == JsonValueKind.Object
            ? v : default;

    internal static string FormatDiagnosticsForTest(JsonElement diag) => FormatDiagnostics(diag);

    private static string Str(JsonElement o, string key)
        => o.ValueKind == JsonValueKind.Object && o.TryGetProperty(key, out var v) && v.ValueKind == JsonValueKind.String
            ? v.GetString() ?? "" : "";

    /// <summary>Replace the user's home directory with "~" so a copied diagnostic block
    /// doesn't leak the account name.</summary>
    private static string Redact(string path)
    {
        if (string.IsNullOrEmpty(path)) return path;
        string home = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        return !string.IsNullOrEmpty(home) && path.StartsWith(home, StringComparison.OrdinalIgnoreCase)
            ? "~" + path.Substring(home.Length) : path;
    }

    private static bool Bool(JsonElement o, string key)
        => o.ValueKind == JsonValueKind.Object && o.TryGetProperty(key, out var v) && v.ValueKind == JsonValueKind.True;

    private static string AppVersion()
        => Assembly.GetExecutingAssembly().GetName().Version?.ToString(3) ?? "1.0.0";

    private static void SelectTag(ComboBox combo, string tag)
    {
        foreach (var obj in combo.Items)
            if (obj is FrameworkElement fe && fe.Tag as string == tag) { combo.SelectedItem = obj; return; }
        combo.SelectedIndex = 0;
    }

    /// <summary>Write a setting; on failure tell the user and resync the UI from the
    /// actually-persisted config so a control never *looks* set when it isn't.</summary>
    private async Task<bool> Persist(string key, object value)
    {
        bool ok = false;
        if (_host?.Client != null)
        {
            try
            {
                var r = await _host.Client.RpcAsync("setConfig", new { key, value });
                ok = r.TryGetProperty("saved", out var s) && s.GetBoolean();
            }
            catch { ok = false; }
        }
        if (!ok)
        {
            await ShowMessageAsync("לא ניתן לשמור את ההגדרה כעת.", "בדקו שהמנוע פעיל ונסו שוב.");
            await LoadAsync();
        }
        return ok;
    }

    private async Task<string> GetString(string key, string fallback)
    {
        if (_host?.Client == null) return fallback;
        try
        {
            var r = await _host.Client.RpcAsync("getConfig", new { key });
            return r.TryGetProperty("value", out var v) && v.ValueKind == JsonValueKind.String
                ? v.GetString() ?? fallback : fallback;
        }
        catch { return fallback; }
    }

    private async Task<bool> GetBool(string key, bool fallback)
    {
        if (_host?.Client == null) return fallback;
        try
        {
            var r = await _host.Client.RpcAsync("getConfig", new { key });
            if (r.TryGetProperty("value", out var v))
            {
                if (v.ValueKind == JsonValueKind.True) return true;
                if (v.ValueKind == JsonValueKind.False) return false;
            }
        }
        catch { }
        return fallback;
    }

    private async Task<int> GetInt(string key, int fallback)
    {
        if (_host?.Client == null) return fallback;
        try
        {
            var r = await _host.Client.RpcAsync("getConfig", new { key });
            if (r.TryGetProperty("value", out var v) && v.ValueKind == JsonValueKind.Number
                && v.TryGetInt32(out var n)) return n;
        }
        catch { }
        return fallback;
    }

    private async Task ShowMessageAsync(string title, string body)
    {
        var dialog = new ContentDialog
        {
            Title = title,
            Content = body,
            CloseButtonText = "סגור",
            XamlRoot = this.XamlRoot,
            FlowDirection = FlowDirection.RightToLeft,
        };
        try { await dialog.ShowAsync(); } catch { }
    }
}
