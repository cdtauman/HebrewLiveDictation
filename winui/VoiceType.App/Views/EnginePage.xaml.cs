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
                ModelStatusText.Text = "מוריד מודל לא־מקוון (כ־500MB) — עשוי לקחת מספר דקות, דרוש אינטרנט. אפשר להמשיך לעבוד בינתיים; נעדכן כשיסתיים.";
                ModelDownloadBtn.Visibility = Visibility.Collapsed;
                ModelDeleteBtn.Visibility = Visibility.Collapsed;
                ModelRing.IsActive = true; ModelRing.Visibility = Visibility.Visible;
                break;
            case "error":
                ModelStatusText.Text = "הורדת המודל נכשלה — ייתכן ניתוק אינטרנט או הורדה חלקית. בדקו את החיבור ונסו שוב.";
                ModelDownloadBtn.Content = "נסו שוב";
                ModelDownloadBtn.Visibility = Visibility.Visible;
                ModelDeleteBtn.Visibility = Visibility.Collapsed;
                ModelRing.IsActive = false; ModelRing.Visibility = Visibility.Collapsed;
                break;
            default: // absent
                ModelStatusText.Text = "המודל אינו מותקן. הכתבה לא־מקוונת דורשת הורדה חד־פעמית (כ־500MB, דרוש אינטרנט).";
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
            GoogleCard.Visibility = OptRecommended.IsChecked == true ? Visibility.Visible : Visibility.Collapsed;
            _loading = false;
        });

        await RefreshLabelAsync();
        if (provider == "google_v2") await LoadGoogleConfigAsync();
    }

    // ---- Google Cloud setup (PC1) ----
    private static readonly string[] GoogleLocations =
        { "eu", "us", "global", "europe-west1", "europe-west2", "europe-west3", "europe-west4", "us-central1" };
    private static readonly (string tag, string label)[] GoogleModels =
        { ("chirp_3", "Chirp 3"), ("chirp_2", "Chirp 2"), ("chirp", "Chirp"), ("latest_short", "Latest Short") };

    private async Task LoadGoogleConfigAsync()
    {
        string projectId = await GetConfigString("google.project_id", "");
        string location = await GetConfigString("google.location", "eu");
        string recognizer = await GetConfigString("google.recognizer_id", "_");
        string model = await GetConfigString("google.model", "chirp_3");
        string mode = await GetConfigString("google.credential_mode", "service_account_json");
        string credPath = await GetConfigString("google.credentials_path", "");

        DispatcherQueue.TryEnqueue(() =>
        {
            _loading = true;
            if (LocationCombo.Items.Count == 0)
                foreach (var loc in GoogleLocations) LocationCombo.Items.Add(new ComboBoxItem { Content = loc, Tag = loc });
            SelectComboByTag(LocationCombo, location, "eu");
            if (GoogleModelCombo.Items.Count == 0)
                foreach (var (t, label) in GoogleModels) GoogleModelCombo.Items.Add(new ComboBoxItem { Content = label, Tag = t });
            SelectComboByTag(GoogleModelCombo, model, "chirp_3");
            SelectComboByTag(CredModeCombo, mode, "service_account_json");
            CredPathRow.Visibility = mode == "service_account_json" ? Visibility.Visible : Visibility.Collapsed;
            ProjectIdBox.Text = projectId;
            RecognizerBox.Text = string.IsNullOrEmpty(recognizer) ? "_" : recognizer;
            CredPathBox.Text = credPath;
            _loading = false;
        });
        await RefreshGoogleStatusAsync();
    }

    private static void SelectComboByTag(ComboBox combo, string tag, string fallback)
    {
        foreach (var obj in combo.Items)
            if (obj is ComboBoxItem ci && (ci.Tag as string) == tag) { combo.SelectedItem = obj; return; }
        foreach (var obj in combo.Items)
            if (obj is ComboBoxItem ci && (ci.Tag as string) == fallback) { combo.SelectedItem = obj; return; }
        if (combo.Items.Count > 0) combo.SelectedIndex = 0;
    }

    /// <summary>Honest, no-network Google state from the engine (configured / not-configured).</summary>
    private async Task RefreshGoogleStatusAsync()
    {
        bool configured = false; string projectId = "";
        if (_host?.Client != null)
        {
            try
            {
                var r = await _host.Client.RpcAsync("getGoogleStatus");
                configured = r.TryGetProperty("configured", out var c) && c.ValueKind == JsonValueKind.True;
                projectId = r.TryGetProperty("projectId", out var p) ? p.GetString() ?? "" : "";
            }
            catch { }
        }
        DispatcherQueue.TryEnqueue(() =>
            GoogleStatusText.Text = configured
                ? $"מוגדר ✓  (פרויקט {projectId}). מומלץ ללחוץ 'בדיקת חיבור'."
                : "לא מוגדר. הזינו Project ID ובחרו קובץ הרשאות (JSON), או השתמשו בלא־מקוון. ללא הגדרה תקפה ההכתבה תעבור אוטומטית ללא־מקוון.");
    }

    private async void OnProjectIdChanged(object sender, RoutedEventArgs e)
    {
        if (_loading) return;
        await SetConfig("google.project_id", ProjectIdBox.Text.Trim());
        await RefreshGoogleStatusAsync();
    }

    private async void OnRecognizerChanged(object sender, RoutedEventArgs e)
    {
        if (_loading) return;
        string v = RecognizerBox.Text.Trim();
        await SetConfig("google.recognizer_id", string.IsNullOrEmpty(v) ? "_" : v);
    }

    private async void OnLocationChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_loading) return;
        await SetConfig("google.location", (LocationCombo.SelectedItem as ComboBoxItem)?.Tag as string ?? "eu");
    }

    private async void OnGoogleModelChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_loading) return;
        await SetConfig("google.model", (GoogleModelCombo.SelectedItem as ComboBoxItem)?.Tag as string ?? "chirp_3");
        await RefreshLabelAsync();
    }

    private async void OnCredModeChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_loading) return;
        string mode = (CredModeCombo.SelectedItem as ComboBoxItem)?.Tag as string ?? "service_account_json";
        await SetConfig("google.credential_mode", mode);
        DispatcherQueue.TryEnqueue(() =>
            CredPathRow.Visibility = mode == "service_account_json" ? Visibility.Visible : Visibility.Collapsed);
        await RefreshGoogleStatusAsync();
    }

    private async void OnBrowseCredentials(object sender, RoutedEventArgs e)
    {
        if (_host?.Console == null) return;
        var picker = new Windows.Storage.Pickers.FileOpenPicker
        {
            SuggestedStartLocation = Windows.Storage.Pickers.PickerLocationId.DocumentsLibrary,
        };
        picker.FileTypeFilter.Add(".json");
        // Unpackaged WinUI: a picker must be associated with the owning window's HWND.
        WinRT.Interop.InitializeWithWindow.Initialize(picker, WinRT.Interop.WindowNative.GetWindowHandle(_host.Console));
        var file = await picker.PickSingleFileAsync();
        if (file == null) return;
        await SetConfig("google.credentials_path", file.Path);
        DispatcherQueue.TryEnqueue(() => CredPathBox.Text = file.Path);
        await RefreshGoogleStatusAsync();
    }

    private async void OnTestConnection(object sender, RoutedEventArgs e)
    {
        if (_host?.Client == null) return;
        DispatcherQueue.TryEnqueue(() =>
        {
            TestRing.IsActive = true; TestRing.Visibility = Visibility.Visible;
            TestConnBtn.IsEnabled = false; TestStatusText.Text = "בודק חיבור…";
        });
        string msg = "";
        try
        {
            var r = await _host.Client.RpcAsync("testConnection", new { provider = "google_v2" });
            msg = r.TryGetProperty("message", out var m) ? m.GetString() ?? "" : "";
        }
        catch (Exception ex) { msg = "שגיאה בבדיקה: " + ex.Message; }
        DispatcherQueue.TryEnqueue(() =>
        {
            TestRing.IsActive = false; TestRing.Visibility = Visibility.Collapsed;
            TestConnBtn.IsEnabled = true; TestStatusText.Text = msg;
        });
        await RefreshGoogleStatusAsync();
    }

    private async void OnEngineChoice(object sender, RoutedEventArgs e)
    {
        if (_loading) return;
        string tag = (sender as FrameworkElement)?.Tag as string ?? "";

        if (tag == "choose")
        {
            // PC1 supports Google only; the other cloud providers (Deepgram/Groq) are not configurable
            // yet, so honestly route to Offline rather than leave a dead path.
            await ShowMessageAsync("ספק זה אינו נתמך עדיין",
                "Deepgram/Groq עדיין אינם ניתנים להגדרה בגרסה זו. עוברים למנוע הלא־מקוון. (Google Cloud כן זמין — בחרו 'Google Chirp 3'.)");
            _loading = true;
            OptOffline.IsChecked = true;
            GoogleCard.Visibility = Visibility.Collapsed;
            ChooseCard.Visibility = Visibility.Collapsed;
            BackupCard.Visibility = Visibility.Collapsed;
            _loading = false;
            await Finish(await ApplyOffline());
            return;
        }

        if (tag == "recommended")
        {
            // Google Chirp 3 — a real configurable cloud path. provider=google_v2; the config card below
            // captures project/region/model/credentials and offers a live Test connection. If credentials
            // are missing it is reported as not-configured here, and the engine routes to offline at the
            // next start (recover_unconfigured_cloud) so the user is never stuck on a dead path.
            GoogleCard.Visibility = Visibility.Visible;
            ChooseCard.Visibility = Visibility.Collapsed;
            BackupCard.Visibility = Visibility.Visible;
            bool ok = await SetConfig("stt.provider", "google_v2");
            if (string.IsNullOrEmpty(await GetConfigString("google.model", "")))
                ok &= await SetConfig("google.model", "chirp_3");
            ok &= await ApplyCloudMode();
            if (!await Finish(ok)) return;
            await LoadGoogleConfigAsync();
            return;
        }

        // offline
        GoogleCard.Visibility = Visibility.Collapsed;
        ChooseCard.Visibility = Visibility.Collapsed;
        BackupCard.Visibility = Visibility.Collapsed;
        await Finish(await ApplyOffline());
    }

    /// <summary>Apply the offline (local Whisper) engine — the only engine usable in this beta.</summary>
    private async Task<bool> ApplyOffline()
    {
        bool ok = await SetConfig("stt.provider", "whisper_local");
        ok &= await SetConfig("providers.whisper.enabled", true);
        ok &= await SetConfig("stt.mode", "local");
        return ok;
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
