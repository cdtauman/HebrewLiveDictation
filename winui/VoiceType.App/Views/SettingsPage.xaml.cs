using System;
using System.Reflection;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;
using Windows.ApplicationModel.DataTransfer;

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
        int historyLimit = await GetInt("history.max_entries", 500);
        bool startup = WindowsStartup.IsEnabled();   // real OS state, not just the saved value

        _theme = theme;
        DispatcherQueue.TryEnqueue(() =>
        {
            _loading = true;
            SelectTag(ThemeCombo, theme);
            MinimizeToggle.IsOn = minimize;
            StartupToggle.IsOn = startup;
            HistoryLimitBox.Value = historyLimit;
            _loading = false;
        });

        await LoadDiagnosticsAsync();
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

    private async Task LoadDiagnosticsAsync()
    {
        string text = "המנוע אינו פעיל.";
        if (_host?.Client != null)
        {
            try
            {
                var st = await _host.Client.RpcAsync("getStatus");
                var sb = new StringBuilder();
                string configDir = Str(st, "configDir");
                sb.AppendLine("state: " + Str(st, "state"));
                sb.AppendLine("hotkeys: " + (Bool(st, "hotkeysActive") ? "active" : "inactive"));
                sb.AppendLine("config: " + Redact(configDir));
                sb.AppendLine("pipe: " + Str(st, "pipe"));
                sb.AppendLine("shell: VoiceType " + AppVersion());
                sb.AppendLine("");
                sb.AppendLine("קבצים לתמיכה / files for support:");
                sb.AppendLine("• engine log: " + Redact(System.IO.Path.Combine(configDir, "hebrew_live_dictation.log")));
                sb.Append("• shell log: " + Redact(AppLog.FilePath ?? "(unavailable)"));
                text = sb.ToString();
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

    private static string Str(JsonElement o, string key)
        => o.TryGetProperty(key, out var v) && v.ValueKind == JsonValueKind.String ? v.GetString() ?? "" : "";

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
        => o.TryGetProperty(key, out var v) && v.ValueKind == JsonValueKind.True;

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
