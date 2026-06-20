using System;
using System.Text.Json;
using System.Threading.Tasks;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;

namespace VoiceType.Shell.Views;

/// <summary>
/// Engine room: the "Recommended / Offline / Choose" reframe. The surface speaks in
/// outcomes; the engine internals (stt.provider / stt.mode / google.model) live only
/// in the plain-language -> config mapping below. The engine remains the single config
/// writer (all changes go through setConfig over the bridge).
/// </summary>
public sealed partial class EnginePage : Page
{
    private AppHost? _host;
    private bool _loading;   // suppress write-back while syncing UI from config

    public EnginePage() => this.InitializeComponent();

    protected override void OnNavigatedTo(NavigationEventArgs e)
    {
        _host = e.Parameter as AppHost;
        if (_host != null) _host.ModelDownloadChanged += OnModelDownloadChanged;
        _ = LoadAsync();
        _ = RefreshModelStatusAsync();
    }

    protected override void OnNavigatedFrom(NavigationEventArgs e)
    {
        if (_host != null) _host.ModelDownloadChanged -= OnModelDownloadChanged;
    }

    // ---- offline model management (status / download / delete) ----

    private async Task RefreshModelStatusAsync()
    {
        bool downloaded = false;
        string name = "";
        if (_host?.Client != null)
        {
            try
            {
                var r = await _host.Client.RpcAsync("getModelStatus");
                downloaded = r.TryGetProperty("downloaded", out var d) && d.ValueKind == JsonValueKind.True;
                name = r.TryGetProperty("name", out var n) ? n.GetString() ?? "" : "";
            }
            catch { }
        }
        DispatcherQueue.TryEnqueue(() => RenderModel(downloaded ? "ready" : "absent", name));
    }

    /// <summary>Honest model state: ready only when the model is actually on disk. Download is
    /// offered when absent/failed; delete only when present; the ring shows while downloading.</summary>
    private void RenderModel(string state, string name = "")
    {
        switch (state)
        {
            case "ready":
                ModelStatusText.Text = string.IsNullOrEmpty(name)
                    ? "המודל מותקן ✓ — הכתבה לא־מקוונת מוכנה."
                    : $"המודל מותקן ✓ ({name}) — הכתבה לא־מקוונת מוכנה.";
                ModelDownloadBtn.Visibility = Visibility.Collapsed;
                ModelDeleteBtn.Visibility = Visibility.Visible;
                ModelDeleteBtn.IsEnabled = true;
                ModelRing.IsActive = false; ModelRing.Visibility = Visibility.Collapsed;
                break;
            case "downloading":
                ModelStatusText.Text = "מוריד מודל לא־מקוון… (פעם אחת, דרוש אינטרנט).";
                ModelDownloadBtn.Visibility = Visibility.Collapsed;
                ModelDeleteBtn.Visibility = Visibility.Collapsed;
                ModelRing.IsActive = true; ModelRing.Visibility = Visibility.Visible;
                break;
            case "error":
                ModelStatusText.Text = "הורדת המודל נכשלה. אפשר לנסות שוב.";
                ModelDownloadBtn.Content = "נסו שוב";
                ModelDownloadBtn.Visibility = Visibility.Visible;
                ModelDeleteBtn.Visibility = Visibility.Collapsed;
                ModelRing.IsActive = false; ModelRing.Visibility = Visibility.Collapsed;
                break;
            default: // absent
                ModelStatusText.Text = "המודל אינו מותקן. הכתבה לא־מקוונת דורשת הורדה חד־פעמית (דרוש אינטרנט).";
                ModelDownloadBtn.Content = "הורד מודל";
                ModelDownloadBtn.Visibility = Visibility.Visible;
                ModelDeleteBtn.Visibility = Visibility.Collapsed;
                ModelRing.IsActive = false; ModelRing.Visibility = Visibility.Collapsed;
                break;
        }
    }

    private async void OnDownloadModel(object sender, RoutedEventArgs e)
    {
        RenderModel("downloading");
        if (_host?.Client == null) { RenderModel("error"); return; }
        try
        {
            var r = await _host.Client.RpcAsync("downloadModel");
            bool started = r.TryGetProperty("started", out var s) && s.GetBoolean();
            bool busy = r.TryGetProperty("busy", out var b) && b.GetBoolean();
            if (!started && !busy) await RefreshModelStatusAsync();
        }
        catch { RenderModel("error"); }
    }

    private async void OnDeleteModel(object sender, RoutedEventArgs e)
    {
        if (_host?.Client == null) return;
        var confirm = new ContentDialog
        {
            Title = "למחוק את המודל הלא־מקוון?",
            Content = "הכתבה לא־מקוונת לא תעבוד עד להורדה מחדש.",
            PrimaryButtonText = "מחק",
            CloseButtonText = "ביטול",
            XamlRoot = this.XamlRoot,
            FlowDirection = FlowDirection.RightToLeft,
        };
        try { if (await confirm.ShowAsync() != ContentDialogResult.Primary) return; } catch { return; }

        ModelDeleteBtn.IsEnabled = false;
        bool deleted = false;
        try
        {
            var r = await _host.Client.RpcAsync("deleteModel", new { confirm = true });
            deleted = r.TryGetProperty("deleted", out var d) && d.ValueKind == JsonValueKind.True;
        }
        catch { }
        // Honest feedback: never let a failed delete look like it succeeded. A refusal here is
        // usually a download in flight or a file lock — both are recoverable.
        if (!deleted)
            await ShowMessageAsync("לא ניתן למחוק את המודל כעת.",
                "ייתכן שהורדה פעילה או שהקובץ בשימוש. נסו שוב מאוחר יותר.");
        await RefreshModelStatusAsync();
    }

    private async void OnModelDownloadChanged(string state, string name, string message)
    {
        if (state == "done") { await RefreshModelStatusAsync(); return; }
        DispatcherQueue.TryEnqueue(() => RenderModel(
            state switch { "running" => "downloading", "error" => "error", _ => "absent" }, name));
    }

    // ---- runtime self-test hooks (render only; no RPC) ----
    internal void RenderModelForTest(string state) => RenderModel(state);
    internal bool ModelDownloadVisibleForTest => ModelDownloadBtn.Visibility == Visibility.Visible;
    internal bool ModelDeleteVisibleForTest => ModelDeleteBtn.Visibility == Visibility.Visible;
    internal bool ModelRingActiveForTest => ModelRing.IsActive;

    private async Task LoadAsync()
    {
        string provider = await GetConfigString("stt.provider", "google_v2");
        string mode = await GetConfigString("stt.mode", "api");

        DispatcherQueue.TryEnqueue(() =>
        {
            _loading = true;
            BackupToggle.IsOn = mode == "auto_fallback";

            if (provider == "whisper_local" || mode == "local")
                OptOffline.IsChecked = true;
            else if (provider == "google_v2")
                OptRecommended.IsChecked = true;
            else
            {
                OptChoose.IsChecked = true;
                ProviderCombo.SelectedIndex = provider == "groq" ? 1 : 0;
            }

            bool offline = OptOffline.IsChecked == true;
            BackupCard.Visibility = offline ? Visibility.Collapsed : Visibility.Visible;
            ChooseCard.Visibility = OptChoose.IsChecked == true ? Visibility.Visible : Visibility.Collapsed;
            _loading = false;
        });

        await RefreshLabelAsync();
    }

    private async void OnEngineChoice(object sender, RoutedEventArgs e)
    {
        if (_loading) return;
        string tag = (sender as FrameworkElement)?.Tag as string ?? "";
        bool cloud = tag is "recommended" or "choose";
        BackupCard.Visibility = cloud ? Visibility.Visible : Visibility.Collapsed;
        ChooseCard.Visibility = tag == "choose" ? Visibility.Visible : Visibility.Collapsed;

        bool ok = true;
        switch (tag)
        {
            case "recommended":
                ok &= await SetConfig("stt.provider", "google_v2");
                ok &= await SetConfig("google.model", "chirp_3");
                ok &= await ApplyCloudMode();
                break;
            case "offline":
                ok &= await SetConfig("stt.provider", "whisper_local");
                ok &= await SetConfig("providers.whisper.enabled", true);
                ok &= await SetConfig("stt.mode", "local");
                break;
            default: // choose
                ok &= await SetConfig("stt.provider", SelectedProvider());
                ok &= await ApplyCloudMode();
                break;
        }
        if (!await Finish(ok)) return;
    }

    private async void OnBackupToggled(object sender, RoutedEventArgs e)
    {
        if (_loading || OptOffline.IsChecked == true) return;   // offline has no cloud to back up
        await Finish(await ApplyCloudMode());
    }

    private async void OnProviderChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_loading || OptChoose.IsChecked != true) return;
        await Finish(await SetConfig("stt.provider", SelectedProvider()));
    }

    /// <summary>Apply the cloud-mode pair: backup on -> stt.mode=auto_fallback AND the
    /// local Whisper engine enabled (the fallback prerequisite — without it the backup
    /// promise is false); backup off -> stt.mode=api.</summary>
    private async Task<bool> ApplyCloudMode()
    {
        if (BackupToggle.IsOn)
        {
            bool ok = await SetConfig("providers.whisper.enabled", true);
            return await SetConfig("stt.mode", "auto_fallback") && ok;
        }
        return await SetConfig("stt.mode", "api");
    }

    /// <summary>After a change: refresh the live label on success, or — if any write
    /// failed — tell the user and resync the UI from the actually-persisted config so
    /// nothing ever *looks* saved when it isn't. Returns whether the change succeeded.</summary>
    private async Task<bool> Finish(bool ok)
    {
        if (!ok)
        {
            await ShowMessageAsync("לא ניתן לשמור את ההגדרה כעת.", "בדקו שהמנוע פעיל ונסו שוב.");
            await LoadAsync();
            return false;
        }
        await RefreshLabelAsync();
        return true;
    }

    private string SelectedProvider() => (ProviderCombo.SelectedItem as FrameworkElement)?.Tag as string ?? "deepgram";

    private async Task<string> GetConfigString(string key, string fallback)
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

    /// <summary>Write one config key; returns true only if the engine confirms saved.</summary>
    private async Task<bool> SetConfig(string key, object value)
    {
        if (_host?.Client == null) return false;
        try
        {
            var r = await _host.Client.RpcAsync("setConfig", new { key, value });
            return r.TryGetProperty("saved", out var s) && s.GetBoolean();
        }
        catch { return false; }
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

    private async Task RefreshLabelAsync()
    {
        if (_host?.Client == null) return;
        try
        {
            var h = await _host.Client.RpcAsync("getHealth");
            string label = h.TryGetProperty("engine", out var en) && en.TryGetProperty("label", out var l)
                ? l.GetString() ?? "" : "";
            DispatcherQueue.TryEnqueue(() =>
                CurrentLabel.Text = string.IsNullOrEmpty(label) ? "" : "המנוע הנוכחי: " + label);
        }
        catch { }
    }
}
