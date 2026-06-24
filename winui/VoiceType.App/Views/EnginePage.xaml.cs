using System;
using System.Collections.Generic;
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
        _ = LoadModelCatalogAsync();
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
                string state = Str(r, "state");
                DispatcherQueue.TryEnqueue(() =>
                    RenderModel(downloaded ? "ready" : (string.IsNullOrEmpty(state) ? "absent" : state), name));
                return;
            }
            catch { }
        }
        DispatcherQueue.TryEnqueue(() => RenderModel(downloaded ? "ready" : "absent", name));
    }

    // ---- offline model catalog (PC2): list/select; download/delete reuse the selected model ----
    private bool _loadingCatalog;
    private string _selectedSizeLabel = "";   // size of the selected model, for honest download copy
    private string _selectedModelState = "missing";

    private async Task LoadModelCatalogAsync()
    {
        if (_host?.Client == null) return;
        JsonElement r;
        try { r = await _host.Client.RpcAsync("getModelCatalog"); }
        catch { return; }
        string selected = r.TryGetProperty("selected", out var s) ? s.GetString() ?? "" : "";
        var rows = new List<(string name, string label)>();
        string selectedMeta = "";
        string selectedSize = "";
        _selectedModelState = "missing";
        if (r.TryGetProperty("items", out var items) && items.ValueKind == JsonValueKind.Array)
        {
            foreach (var it in items.EnumerateArray())
            {
                string name = it.TryGetProperty("name", out var n) ? n.GetString() ?? "" : "";
                string size = it.TryGetProperty("sizeLabel", out var sz) ? sz.GetString() ?? "" : "";
                string quality = it.TryGetProperty("quality", out var q) ? q.GetString() ?? "" : "";
                string speed = it.TryGetProperty("speed", out var sp) ? sp.GetString() ?? "" : "";
                int ram = it.TryGetProperty("ramMb", out var rm) && rm.TryGetInt32(out var rv) ? rv : 0;
                bool downloaded = it.TryGetProperty("downloaded", out var d) && d.ValueKind == JsonValueKind.True;
                bool recommended = it.TryGetProperty("recommended", out var rc) && rc.ValueKind == JsonValueKind.True;
                string state = Str(it, "state");
                string stateLabel = state switch
                {
                    "downloading" => "  downloading",
                    "incomplete" => "  incomplete",
                    _ => downloaded ? "  installed" : "",
                };
                string label = name + (recommended ? "  recommended" : "") + stateLabel;
                string meta = $"{size} · זיכרון ~{ram}MB · איכות: {quality} · מהירות: {speed}";
                if (name == selected)
                {
                    selectedMeta = meta;
                    selectedSize = size;
                    _selectedModelState = string.IsNullOrEmpty(state) ? (downloaded ? "ready" : "missing") : state;
                }
                rows.Add((name, label));
            }
        }
        DispatcherQueue.TryEnqueue(() =>
        {
            _loadingCatalog = true;
            ModelCombo.Items.Clear();
            ComboBoxItem? sel = null;
            foreach (var (name, label) in rows)
            {
                var item = new ComboBoxItem { Content = label, Tag = name };
                ModelCombo.Items.Add(item);
                if (name == selected) sel = item;
            }
            if (sel != null) ModelCombo.SelectedItem = sel;
            else if (ModelCombo.Items.Count > 0) ModelCombo.SelectedIndex = 0;
            ModelMetaText.Text = selectedMeta;
            if (!string.IsNullOrEmpty(selectedSize)) _selectedSizeLabel = selectedSize;
            // Re-render the status copy so the download text reflects the selected model's real size.
            if (ModelDownloadBtn.Visibility == Visibility.Visible && ModelDeleteBtn.Visibility != Visibility.Visible)
                RenderModel(_selectedModelState);
            _loadingCatalog = false;
        });
    }

    private async void OnModelSelected(object sender, SelectionChangedEventArgs e)
    {
        if (_loadingCatalog) return;
        string name = (ModelCombo.SelectedItem as ComboBoxItem)?.Tag as string ?? "";
        if (string.IsNullOrEmpty(name)) return;
        if (!await SetConfig("providers.whisper.model", name))
        {
            await ShowMessageAsync("לא ניתן לשמור את בחירת המודל כעת.", "בדקו שהמנוע פעיל ונסו שוב.");
            return;
        }
        // The download/delete card and status follow the selected model.
        await RefreshModelStatusAsync();
        await LoadModelCatalogAsync();
    }

    /// <summary>Honest download-size suffix for the selected model (e.g. " (~1.5 GB)"), so the copy
    /// never claims a fixed ~500 MB when the user picked medium/large.</summary>
    private string SizeSuffix() => string.IsNullOrEmpty(_selectedSizeLabel) ? "" : $" ({_selectedSizeLabel})";

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
                ModelStatusText.Text = $"מוריד מודל לא־מקוון{SizeSuffix()} — עשוי לקחת מספר דקות, דרוש אינטרנט. אפשר להמשיך לעבוד בינתיים; נעדכן כשיסתיים.";
                ModelDownloadBtn.Visibility = Visibility.Collapsed;
                ModelDeleteBtn.Visibility = Visibility.Collapsed;
                ModelRing.IsActive = true; ModelRing.Visibility = Visibility.Visible;
                break;
            case "incomplete":
                ModelStatusText.Text = $"נמצאה הורדה חלקית או לא שמישה. הורידו מחדש את המודל{SizeSuffix()} כדי להשלים את ההתקנה.";
                ModelDownloadBtn.Content = "הורד מחדש";
                ModelDownloadBtn.Visibility = Visibility.Visible;
                ModelDeleteBtn.Visibility = Visibility.Collapsed;
                ModelRing.IsActive = false; ModelRing.Visibility = Visibility.Collapsed;
                break;
            case "error":
                ModelStatusText.Text = "הורדת המודל נכשלה — ייתכן ניתוק אינטרנט או הורדה חלקית. בדקו את החיבור ונסו שוב.";
                ModelDownloadBtn.Content = "נסו שוב";
                ModelDownloadBtn.Visibility = Visibility.Visible;
                ModelDeleteBtn.Visibility = Visibility.Collapsed;
                ModelRing.IsActive = false; ModelRing.Visibility = Visibility.Collapsed;
                break;
            default: // absent
                ModelStatusText.Text = $"המודל אינו מותקן. הכתבה לא־מקוונת דורשת הורדה חד־פעמית{SizeSuffix()} (דרוש אינטרנט).";
                ModelDownloadBtn.Content = "הורד מודל";
                ModelDownloadBtn.Visibility = Visibility.Visible;
                ModelDeleteBtn.Visibility = Visibility.Collapsed;
                ModelRing.IsActive = false; ModelRing.Visibility = Visibility.Collapsed;
                break;
        }
    }

    private async void OnDownloadModel(object sender, RoutedEventArgs e)
    {
        string name = (ModelCombo.SelectedItem as ComboBoxItem)?.Tag as string ?? "";
        RenderModel("downloading", name);
        if (_host?.Client == null) { RenderModel("error"); return; }
        try
        {
            var r = await _host.Client.RpcAsync(
                "downloadModel",
                string.IsNullOrEmpty(name) ? null : new { name });
            bool started = r.TryGetProperty("started", out var s) && s.GetBoolean();
            bool busy = r.TryGetProperty("busy", out var b) && b.GetBoolean();
            bool alreadyDownloaded = r.TryGetProperty("alreadyDownloaded", out var ad) && ad.GetBoolean();
            if (started)
            {
                await LoadModelCatalogAsync();
            }
            else if (alreadyDownloaded)
            {
                RenderModel("ready", name);
                await LoadModelCatalogAsync();
            }
            else if (busy)
            {
                RenderModel("downloading", Str(r, "name"));
                await LoadModelCatalogAsync();
            }
            else if (!started)
            {
                await RefreshModelStatusAsync();
                await LoadModelCatalogAsync();
            }
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
        await LoadModelCatalogAsync();   // reflect the new downloaded state in the catalog
    }

    private async void OnModelDownloadChanged(string state, string name, string message)
    {
        if (state == "done") { await RefreshModelStatusAsync(); await LoadModelCatalogAsync(); return; }
        if (state == "running")
        {
            DispatcherQueue.TryEnqueue(() => RenderModel("downloading", name));
            await LoadModelCatalogAsync();
            return;
        }
        DispatcherQueue.TryEnqueue(() => RenderModel(
            state switch { "running" => "downloading", "error" => "error", _ => "absent" }, name));
    }

    // ---- runtime self-test hooks (render only; no RPC) ----
    internal void RenderModelForTest(string state) => RenderModel(state);
    internal bool ModelDownloadVisibleForTest => ModelDownloadBtn.Visibility == Visibility.Visible;
    internal bool ModelDeleteVisibleForTest => ModelDeleteBtn.Visibility == Visibility.Visible;
    internal bool ModelRingActiveForTest => ModelRing.IsActive;
    internal void RenderSmartAutoForTest(string text)
    {
        SmartAutoCard.Visibility = Visibility.Visible;
        SmartAutoStatusText.Text = text;
    }
    internal bool SmartAutoCardVisibleForTest => SmartAutoCard.Visibility == Visibility.Visible;
    internal string SmartAutoStatusForTest => SmartAutoStatusText.Text;

    private async Task LoadAsync()
    {
        string provider = await GetConfigString("stt.provider", "google_v2");
        string mode = await GetConfigString("stt.mode", "api");

        DispatcherQueue.TryEnqueue(() =>
        {
            _loading = true;
            BackupToggle.IsOn = mode == "auto_fallback" || mode == "smart_auto";

            if (mode == "smart_auto")
                OptSmart.IsChecked = true;
            else if (provider == "whisper_local" || mode == "local")
                OptOffline.IsChecked = true;
            else if (provider == "google_v2")
                OptRecommended.IsChecked = true;
            else
            {
                OptChoose.IsChecked = true;
                ProviderCombo.SelectedIndex = provider == "groq" ? 1 : 0;
            }

            bool offline = OptOffline.IsChecked == true;
            bool smart = OptSmart.IsChecked == true;
            BackupCard.Visibility = offline ? Visibility.Collapsed : Visibility.Visible;
            if (smart) BackupCard.Visibility = Visibility.Collapsed;
            SmartAutoCard.Visibility = smart ? Visibility.Visible : Visibility.Collapsed;
            ChooseCard.Visibility = OptChoose.IsChecked == true ? Visibility.Visible : Visibility.Collapsed;
            GoogleCard.Visibility = OptRecommended.IsChecked == true ? Visibility.Visible : Visibility.Collapsed;
            _loading = false;
        });

        await RefreshLabelAsync();
        await LoadProviderStatusAsync();
        if (mode != "smart_auto")
        {
            if (provider == "google_v2") await LoadGoogleConfigAsync();
            else await LoadSelectedProviderConfigAsync();
        }
    }

    // ---- Google Cloud setup (PC1) ----
    private static readonly string[] GoogleLocations =
        { "eu", "us", "global", "europe-west1", "europe-west2", "europe-west3", "europe-west4", "us-central1" };
    // Model labels are intentionally cautious: connection verification is not dictation verification,
    // and live/interim behavior must be proven by a real transcription probe.
    internal static readonly (string tag, string label)[] GoogleModels =
    {
        ("chirp_3", "Chirp 3 — סופי בלבד · דורש הוכחת תמלול"),
        ("chirp_2", "Chirp 2 — סופי בלבד · דורש הוכחת תמלול"),
        ("chirp", "Chirp — סופי בלבד · דורש הוכחת תמלול"),
        ("latest_long", "Latest Long — נתיב R3 מוכח כשמוגדר בדיוק"),
        ("latest_short", "Latest Short — אמירות קצרות בלבד"),
    };

    internal static readonly (string tag, string label)[] DeepgramModels =
    {
        ("nova-3", "Nova-3 · זרימה חיה בעברית"),
        ("nova-2", "Nova-2 · גיבוי ישן"),
    };

    internal static readonly (string tag, string label)[] GroqModels =
    {
        ("whisper-large-v3", "Whisper Large v3 · תמלול עברית סופי בלבד"),
        ("whisper-large-v3-turbo", "Whisper Large v3 Turbo · סופי בלבד, זמן תגובה נמוך"),
    };

    /// <summary>Longer, honest per-model guidance shown under the picker (R3 item 2).</summary>
    private static string GoogleModelMeta(string tag) => tag switch
    {
        "chirp_3" => "Chirp 3: מתייחס כהחזרה סופית בלבד — בלי מילים חיות. אם הוא מחזיר ריק בשילוב אזור/שפה, עברו לנתיב שנבדק במקום להניח שהחיבור מוכיח תמלול.",
        "chirp_2" => "Chirp 2: מתייחס כסופי בלבד (ללא מילים חיות) ודורש בדיקת תמלול אמיתית לשילוב שבחרתם.",
        "chirp" => "Chirp: משפחת Chirp הוותיקה; סופי בלבד ודורש בדיקת תמלול אמיתית לשילוב שבחרתם.",
        "latest_long" => "Latest Long: נתיב R3 שנבדק בהצלחה הוא latest_long / eu / iw-IL / _. גם כאן נדרש חיבור מאומת בפרויקט שלכם והכתבה אמיתית לפני שמסמנים PASS.",
        "latest_short" => "Latest Short: לאמירות קצרות; לא להניח מילים חיות או התאמה להכתבה ארוכה בלי בדיקת תמלול.",
        _ => "",
    };

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
            GoogleModelMetaText.Text = GoogleModelMeta(model);
            SelectComboByTag(CredModeCombo, mode, "service_account_json");
            CredPathRow.Visibility = mode == "service_account_json" ? Visibility.Visible : Visibility.Collapsed;
            ProjectIdBox.Text = projectId;
            RecognizerBox.Text = string.IsNullOrEmpty(recognizer) ? "_" : recognizer;
            CredPathBox.Text = credPath;
            _loading = false;
        });
        await RefreshGoogleStatusAsync();
    }

    private async Task LoadDeepgramConfigAsync()
    {
        string model = await GetConfigString("providers.deepgram.model", "nova-3");
        DispatcherQueue.TryEnqueue(() =>
        {
            _loading = true;
            if (DeepgramModelCombo.Items.Count == 0)
                foreach (var (t, label) in DeepgramModels)
                    DeepgramModelCombo.Items.Add(new ComboBoxItem { Content = label, Tag = t });
            SelectComboByTag(DeepgramModelCombo, model, "nova-3");
            _loading = false;
        });
        await LoadProviderKeyStatusAsync();
    }

    private async Task LoadGroqConfigAsync()
    {
        string model = await GetConfigString("providers.groq.model", "whisper-large-v3");
        DispatcherQueue.TryEnqueue(() =>
        {
            _loading = true;
            if (GroqModelCombo.Items.Count == 0)
                foreach (var (t, label) in GroqModels)
                    GroqModelCombo.Items.Add(new ComboBoxItem { Content = label, Tag = t });
            SelectComboByTag(GroqModelCombo, model, "whisper-large-v3");
            _loading = false;
        });
        await LoadProviderKeyStatusAsync();
    }

    private async Task LoadSelectedProviderConfigAsync()
    {
        if (SelectedProvider() == "groq") await LoadGroqConfigAsync();
        else await LoadDeepgramConfigAsync();
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
        bool verified = false, hasCreds = false;
        string projectId = "", model = "", location = "", language = "", recognizer = "", credentialMode = "";
        if (_host?.Client != null)
        {
            try
            {
                var r = await _host.Client.RpcAsync("getGoogleStatus");
                verified = r.TryGetProperty("verified", out var v) && v.ValueKind == JsonValueKind.True;
                hasCreds = r.TryGetProperty("hasCredentials", out var hc) && hc.ValueKind == JsonValueKind.True;
                projectId = r.TryGetProperty("projectId", out var p) ? p.GetString() ?? "" : "";
                model = r.TryGetProperty("model", out var md) ? md.GetString() ?? "" : "";
                location = r.TryGetProperty("location", out var lo) ? lo.GetString() ?? "" : "";
                language = r.TryGetProperty("language", out var lg) ? lg.GetString() ?? "" : "";
                recognizer = r.TryGetProperty("recognizer", out var rc) ? rc.GetString() ?? "" : "";
                credentialMode = r.TryGetProperty("credentialMode", out var cm) ? cm.GetString() ?? "" : "";
            }
            catch { }
        }
        bool requestsLiveWords = model == "latest_long";
        // Honest: this is connection verification only. Real dictation/live words require a transcript probe.
        DispatcherQueue.TryEnqueue(() =>
        {
            GoogleStatusText.Text = verified
                ? $"חיבור מאומת ✓  (פרויקט {projectId}). זה אינו PASS של הכתבה עד שתמלול אמיתי מחזיר טקסט."
                : hasCreds
                    ? "פרטים קיימים אך החיבור לא נבדק. עד בדיקת חיבור ההכתבה תשתמש בלא־מקוון."
                    : "לא מוגדר. הזינו Project ID ובחרו קובץ הרשאות (JSON), או השתמשו בלא־מקוון.";
            // Active runtime config (R3 item 5) — what will actually run, plus an honest live-words note.
            GoogleActiveText.Text = string.IsNullOrEmpty(model)
                ? ""
                : $"פעיל: Google · מודל {model} · אזור {location} · שפה {language} · Recognizer {recognizer} · Auth {credentialMode} · "
                  + (verified ? "חיבור מאומת ✓" : "חיבור לא נבדק") + " · "
                  + (requestsLiveWords ? "מבקש מילים חיות; PASS רק אחרי interims/final בפועל" : "סופי בלבד או לא ידוע; PASS רק אחרי תמלול בפועל");
        });
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
        if (!await SetConfig("google.recognizer_id", string.IsNullOrEmpty(v) ? "_" : v))
        {
            await Finish(false);
            return;
        }
        await RefreshGoogleStatusAsync();
    }

    private async void OnLocationChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_loading) return;
        if (!await SetConfig("google.location", (LocationCombo.SelectedItem as ComboBoxItem)?.Tag as string ?? "eu"))
        {
            await Finish(false);
            return;
        }
        await LoadGoogleConfigAsync();   // resync picker from persisted/normalized runtime truth
    }

    private async void OnGoogleModelChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_loading) return;
        string tag = (GoogleModelCombo.SelectedItem as ComboBoxItem)?.Tag as string ?? "chirp_3";
        if (!await SetConfig("google.model", tag))
        {
            await Finish(false);
            return;
        }
        await RefreshLabelAsync();
        await LoadGoogleConfigAsync();   // resync picker from persisted/normalized runtime truth
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
            _loading = true;
            GoogleCard.Visibility = Visibility.Collapsed;
            SmartAutoCard.Visibility = Visibility.Collapsed;
            ChooseCard.Visibility = Visibility.Visible;
            BackupCard.Visibility = Visibility.Visible;
            if (ProviderCombo.SelectedItem == null) ProviderCombo.SelectedIndex = 0;
            _loading = false;
            await LoadSelectedProviderConfigAsync();
            await Finish(await ApplySelectedCloudProviderIfReadyAsync());
            return;
        }

        if (tag == "smart_auto")
        {
            GoogleCard.Visibility = Visibility.Collapsed;
            ChooseCard.Visibility = Visibility.Collapsed;
            SmartAutoCard.Visibility = Visibility.Visible;
            BackupCard.Visibility = Visibility.Collapsed;
            _loading = true;
            BackupToggle.IsOn = true;
            _loading = false;
            if (!await Finish(await ApplySmartAuto())) return;
            await LoadProviderStatusAsync();
            return;
        }

        if (tag == "recommended")
        {
            // Google STT V2 — a configurable cloud path. The card captures the exact runtime
            // tuple and offers Test connection, but dictation proof still requires a real
            // transcript from that tuple. If credentials are missing, the engine routes to
            // offline at the next start so the user is never stuck on a dead path.
            GoogleCard.Visibility = Visibility.Visible;
            ChooseCard.Visibility = Visibility.Collapsed;
            SmartAutoCard.Visibility = Visibility.Collapsed;
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
        SmartAutoCard.Visibility = Visibility.Collapsed;
        BackupCard.Visibility = Visibility.Collapsed;
        await Finish(await ApplyOffline());
    }

    /// <summary>Apply the offline (local Whisper) engine — the safe local baseline.</summary>
    private async Task<bool> ApplyOffline()
    {
        bool ok = await SetConfig("stt.provider", "whisper_local");
        ok &= await SetConfig("providers.whisper.enabled", true);
        ok &= await SetConfig("stt.mode", "local");
        return ok;
    }

    /// <summary>Smart Auto keeps provider choice in the engine and enables local Whisper as
    /// the fallback target. The model still has to be installed before backup/offline can work.</summary>
    private async Task<bool> ApplySmartAuto()
    {
        bool ok = await SetConfig("stt.provider", "google_v2");
        ok &= await SetConfig("providers.whisper.enabled", true);
        ok &= await SetConfig("stt.mode", "smart_auto");
        return ok;
    }

    private async void OnBackupToggled(object sender, RoutedEventArgs e)
    {
        if (_loading || OptOffline.IsChecked == true || OptSmart.IsChecked == true) return;   // offline/smart manage backup internally
        if (OptChoose.IsChecked == true)
        {
            await Finish(await ApplySelectedCloudProviderIfReadyAsync());
            return;
        }
        await Finish(await ApplyCloudMode());
    }

    private async void OnProviderChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_loading || OptChoose.IsChecked != true) return;
        await LoadSelectedProviderConfigAsync();
        await Finish(await ApplySelectedCloudProviderIfReadyAsync());
    }

    private async void OnDeepgramModelChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_loading) return;
        string tag = (DeepgramModelCombo.SelectedItem as ComboBoxItem)?.Tag as string ?? "nova-3";
        if (!await SetConfig("providers.deepgram.model", tag))
        {
            await Finish(false);
            return;
        }
        DispatcherQueue.TryEnqueue(() =>
            ProviderTestStatusText.Text = "מודל Deepgram שונה; הריצו ‘בדיקת חיבור’ שוב לפני השימוש.");
        await LoadProviderKeyStatusAsync();
        if (OptChoose.IsChecked == true)
            await Finish(await ApplySelectedCloudProviderIfReadyAsync());
    }

    private async void OnGroqModelChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_loading) return;
        string tag = (GroqModelCombo.SelectedItem as ComboBoxItem)?.Tag as string ?? "whisper-large-v3";
        if (!await SetConfig("providers.groq.model", tag))
        {
            await Finish(false);
            return;
        }
        DispatcherQueue.TryEnqueue(() =>
            ProviderTestStatusText.Text = "מודל Groq שונה; הריצו ‘בדיקת חיבור’ שוב לפני השימוש. Groq מחזיר טקסט סופי בלבד.");
        await LoadProviderKeyStatusAsync();
        if (OptChoose.IsChecked == true)
            await Finish(await ApplySelectedCloudProviderIfReadyAsync());
    }

    private async void OnTestProviderConnection(object sender, RoutedEventArgs e)
    {
        if (_host?.Client == null) return;
        string provider = SelectedProvider();
        if (provider != "deepgram" && provider != "groq")
        {
            DispatcherQueue.TryEnqueue(() =>
                ProviderTestStatusText.Text = $"{provider} אינו זמין לבדיקת מפתח API.");
            return;
        }
        DispatcherQueue.TryEnqueue(() =>
        {
            ProviderTestRing.IsActive = true;
            ProviderTestRing.Visibility = Visibility.Visible;
            TestProviderBtn.IsEnabled = false;
            ProviderTestStatusText.Text = $"בודק חיבור ל‑{provider}...";
        });
        bool ok = false;
        string msg = "";
        try
        {
            var r = await _host.Client.RpcAsync("testConnection", new { provider }, timeoutMs: 20000);
            ok = r.TryGetProperty("ok", out var o) && o.ValueKind == JsonValueKind.True;
            msg = Str(r, "message");
        }
        catch (Exception ex) { msg = $"{provider} test failed: " + ex.Message; }
        DispatcherQueue.TryEnqueue(() =>
        {
            ProviderTestRing.IsActive = false;
            ProviderTestRing.Visibility = Visibility.Collapsed;
            ProviderTestStatusText.Text = msg;
        });
        await LoadProviderKeyStatusAsync();
        await Finish(ok ? await ApplySelectedCloudProviderIfReadyAsync() : await ApplyOffline());
    }

    private async Task<bool> ApplySelectedCloudProviderIfReadyAsync()
    {
        string provider = SelectedProvider();
        if (provider != "deepgram" && provider != "groq")
        {
            DispatcherQueue.TryEnqueue(() =>
                ProviderTestStatusText.Text = $"{provider} is not available yet; the engine remains Offline.");
            return await ApplyOffline();
        }
        if (!await ProviderVerifiedAsync(provider))
        {
            DispatcherQueue.TryEnqueue(() =>
                ProviderTestStatusText.Text = $"{provider} requires an API key and Test connection before dictation.");
            return await ApplyOffline();
        }
        bool ok = await SetConfig("stt.provider", provider);
        ok &= await ApplyCloudMode();
        return ok;
    }

    private async Task<bool> ProviderVerifiedAsync(string provider)
    {
        if (_host?.Client == null) return false;
        try
        {
            var r = await _host.Client.RpcAsync("getProviderCredentialStatus", new { provider });
            return r.TryGetProperty("verified", out var v) && v.ValueKind == JsonValueKind.True;
        }
        catch { return false; }
    }

    private async Task LoadProviderKeyStatusAsync()
    {
        if (_host?.Client == null) return;
        string provider = SelectedProvider();
        try
        {
            var r = await _host.Client.RpcAsync("getProviderCredentialStatus", new { provider });
            bool supported = r.TryGetProperty("supported", out var sp) && sp.ValueKind == JsonValueKind.True;
            bool configured = r.TryGetProperty("configured", out var cf) && cf.ValueKind == JsonValueKind.True;
            bool stored = r.TryGetProperty("storedInKeyring", out var st) && st.ValueKind == JsonValueKind.True;
            bool plaintext = r.TryGetProperty("plaintextPresent", out var pt) && pt.ValueKind == JsonValueKind.True;
            bool keyring = r.TryGetProperty("keyringAvailable", out var ka) && ka.ValueKind == JsonValueKind.True;
            bool verified = r.TryGetProperty("verified", out var vf) && vf.ValueKind == JsonValueKind.True;
            string storage = Str(r, "storage");
            string message = Str(r, "message");
            string model = Str(r, "model");
            string language = Str(r, "language");
            bool finalOnly = r.TryGetProperty("finalOnly", out var fo) && fo.ValueKind == JsonValueKind.True;
            string statusExtra = (verified ? " · verified" : "")
                                 + (!string.IsNullOrEmpty(model) ? $" · model={model}" : "")
                                 + (!string.IsNullOrEmpty(language) ? $" · language={language}" : "");
            if (finalOnly) statusExtra += " · final-only";
            DispatcherQueue.TryEnqueue(() =>
            {
                ProviderKeyBox.Password = "";
                bool deepgram = provider == "deepgram";
                bool groq = provider == "groq";
                DeepgramModelRow.Visibility = deepgram ? Visibility.Visible : Visibility.Collapsed;
                GroqModelRow.Visibility = groq ? Visibility.Visible : Visibility.Collapsed;
                ProviderKeyBox.PlaceholderText = configured
                    ? "מפתח API נשמר; הערך אינו מוצג"
                    : "הדביקו מפתח API לשמירה במאגר המפתחות של המערכת";
                SaveProviderKeyBtn.IsEnabled = supported && keyring;
                ClearProviderKeyBtn.IsEnabled = supported && configured;
                TestProviderBtn.IsEnabled = (deepgram || groq) && configured;
                TestProviderBtn.Content = deepgram ? "בדיקת Deepgram" : (groq ? "בדיקת Groq" : "בדיקה לא זמינה");
                ProviderKeyStatusText.Text =
                    $"{provider}: {message} storage={storage}{statusExtra}"
                    + (stored ? " · keyring" : "")
                    + (plaintext ? " · legacy plaintext present" : "");
            });
        }
        catch
        {
            DispatcherQueue.TryEnqueue(() => ProviderKeyStatusText.Text = "");
        }
    }

    private async void OnSaveProviderKey(object sender, RoutedEventArgs e)
    {
        if (_host?.Client == null) return;
        string provider = SelectedProvider();
        string key = ProviderKeyBox.Password.Trim();
        if (string.IsNullOrEmpty(key))
        {
            DispatcherQueue.TryEnqueue(() => ProviderKeyStatusText.Text = $"{provider}: enter an API key before saving.");
            return;
        }
        DispatcherQueue.TryEnqueue(() => SaveProviderKeyBtn.IsEnabled = false);
        try
        {
            var r = await _host.Client.RpcAsync("setProviderApiKey", new { provider, apiKey = key });
            string message = Str(r, "message");
            bool ok = r.TryGetProperty("ok", out var o) && o.ValueKind == JsonValueKind.True;
            DispatcherQueue.TryEnqueue(() =>
            {
                ProviderKeyBox.Password = "";
                ProviderKeyStatusText.Text =
                    $"{provider}: {(string.IsNullOrEmpty(message) ? (ok ? "API key saved." : "Save failed.") : message)}";
            });
        }
        catch
        {
            DispatcherQueue.TryEnqueue(() => ProviderKeyStatusText.Text = $"{provider}: save failed.");
        }
        await LoadProviderKeyStatusAsync();
        if (OptChoose.IsChecked == true)
            await Finish(await ApplySelectedCloudProviderIfReadyAsync());
        else
            await LoadProviderStatusAsync();
    }

    private async void OnClearProviderKey(object sender, RoutedEventArgs e)
    {
        if (_host?.Client == null) return;
        string provider = SelectedProvider();
        DispatcherQueue.TryEnqueue(() => ClearProviderKeyBtn.IsEnabled = false);
        try
        {
            var r = await _host.Client.RpcAsync("clearProviderApiKey", new { provider });
            string message = Str(r, "message");
            DispatcherQueue.TryEnqueue(() =>
            {
                ProviderKeyBox.Password = "";
                ProviderKeyStatusText.Text =
                    $"{provider}: {(string.IsNullOrEmpty(message) ? "API key cleared." : message)}";
            });
        }
        catch
        {
            DispatcherQueue.TryEnqueue(() => ProviderKeyStatusText.Text = $"{provider}: clear failed.");
        }
        await LoadProviderKeyStatusAsync();
        if (OptChoose.IsChecked == true)
            await Finish(await ApplySelectedCloudProviderIfReadyAsync());
        else
            await LoadProviderStatusAsync();
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
        await LoadProviderStatusAsync();
        await LoadProviderKeyStatusAsync();
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

    private async Task LoadProviderStatusAsync()
    {
        if (_host?.Client == null) return;
        try
        {
            var r = await _host.Client.RpcAsync("getProviderStatus");
            string mode = Str(r, "mode");
            string configured = Str(r, "configuredProvider");
            string effective = Str(r, "effectiveProvider");
            string stream = Str(r, "stream");
            bool fallback = r.TryGetProperty("fallbackEnabled", out var fb) && fb.ValueKind == JsonValueKind.True;
            string routingText = "";
            string smartText = "";
            if (r.TryGetProperty("routing", out var routing) && routing.ValueKind == JsonValueKind.Object)
            {
                string summary = Str(routing, "summary");
                string message = Str(routing, "message");
                string backupMessage = Str(routing, "backupMessage");
                string startGate = Str(routing, "startGate");
                string smartPick = Str(routing, "smartAutoSelected");
                bool backupReady = routing.TryGetProperty("backupReady", out var br) && br.ValueKind == JsonValueKind.True;
                routingText = $"{summary} {message} {backupMessage} start={startGate}";
                if (mode == "smart_auto")
                {
                    smartText = $"{summary} {message} {backupMessage}"
                                + (!string.IsNullOrEmpty(smartPick) ? $" Selected={smartPick}." : "")
                                + $" Backup={(backupReady ? "ready" : "not ready")}.";
                }
            }
            var rows = new List<string>();
            if (r.TryGetProperty("providers", out var providers) && providers.ValueKind == JsonValueKind.Array)
            {
                foreach (var p in providers.EnumerateArray())
                {
                    string id = Str(p, "id");
                    string status = Str(p, "status");
                    bool ready = p.TryGetProperty("ready", out var rd) && rd.ValueKind == JsonValueKind.True;
                    bool eff = p.TryGetProperty("effective", out var ef) && ef.ValueKind == JsonValueKind.True;
                    if (string.IsNullOrEmpty(id)) continue;
                    rows.Add($"{id}:{(ready ? "ready" : status)}{(eff ? "*" : "")}");
                }
            }
            string text = !string.IsNullOrWhiteSpace(routingText)
                ? $"Routing: {routingText}"
                : $"מצב ספקים: mode {mode} · נבחר {configured} · בפועל {effective} · stream {stream}"
                  + (fallback ? " · fallback→whisper" : "");
            if (rows.Count > 0) text += " · " + string.Join(" | ", rows);
            DispatcherQueue.TryEnqueue(() =>
            {
                ProviderStatusText.Text = text;
                SmartAutoStatusText.Text = string.IsNullOrWhiteSpace(smartText)
                    ? "Smart Auto chooses among configured cloud providers and Offline, then shows the exact route here."
                    : smartText;
            });
        }
        catch
        {
            DispatcherQueue.TryEnqueue(() =>
            {
                ProviderStatusText.Text = "";
                SmartAutoStatusText.Text = "";
            });
        }
    }

    private static string Str(JsonElement o, string key)
        => o.TryGetProperty(key, out var v) && v.ValueKind == JsonValueKind.String ? v.GetString() ?? "" : "";
}
