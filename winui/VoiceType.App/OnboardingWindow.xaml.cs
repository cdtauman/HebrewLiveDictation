using System;
using System.Collections.Generic;
using System.Text.Json;
using System.Threading.Tasks;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Windows.Graphics;

namespace VoiceType.Shell;

/// <summary>
/// First-run wizard (§6). Sequences setup by payoff, not by config schema: language,
/// microphone, engine, hotkey, ready. Every choice persists immediately through the
/// engine (the single config writer) via setConfig — no engine module is touched.
///
/// Honesty: the plan's step-2 "magic moment" (live mic-level meter + an in-wizard first
/// word) is intentionally NOT faked here — it needs an audio-level signal the engine does
/// not yet expose and a bundled-model decision. Step 2 does the real, useful part (mic
/// selection) and says the live test is coming. Skipping always leaves a WORKING offline
/// product: if the user never picks an engine we apply the offline baseline at completion.
/// </summary>
public sealed partial class OnboardingWindow : Window
{
    private readonly AppHost? _host;
    private bool _loading;
    private bool _engineApplied;   // did the user explicitly choose an engine?
    private bool _completing;      // re-entrancy guard for finish/skip/close
    private bool _done;            // completion succeeded -> a real close is allowed
    private bool _busy;            // a save is in flight (single-writer guard)
    private int _step;

    private FrameworkElement[] _steps = Array.Empty<FrameworkElement>();
    private static readonly (string title, string subtitle)[] _copy =
    {
        ("ברוכים הבאים", "כמה צעדים קצרים ואפשר להכתיב."),
        ("מיקרופון", "באיזה מיקרופון להשתמש?"),
        ("בחירת מנוע", "איך תרצו שההכתבה תעבוד?"),
        ("מקש ההפעלה", "איך להפעיל ולעצור הכתבה?"),
        ("כמעט מוכן", "עוד לחיצה אחת."),
    };

    // language code -> (command pack key, Hebrew pack name) — mirrors the Dictation room.
    private static readonly Dictionary<string, (string pack, string name)> LangPack = new()
    {
        ["iw-IL"] = ("he", "עברית"),
        ["en-US"] = ("en", "אנגלית"),
        ["ar-XA"] = ("ar", "ערבית"),
        ["ru-RU"] = ("ru", "רוסית"),
        ["fr-FR"] = ("fr", "צרפתית"),
        ["es-ES"] = ("es", "ספרדית"),
    };

    public OnboardingWindow(AppHost host)
    {
        this.InitializeComponent();
        _host = host;
        this.Title = "הגדרת VoiceType";
        this.SystemBackdrop = new MicaBackdrop();

        var presenter = OverlappedPresenter.Create();
        presenter.IsResizable = false;
        presenter.IsMaximizable = false;
        presenter.IsMinimizable = false;
        this.AppWindow.SetPresenter(presenter);
        this.AppWindow.Closing += OnClosing;   // X behaves like Skip-with-safe-baseline

        // Live model-download progress (the download runs in the engine, off this window).
        if (_host != null) _host.ModelDownloadChanged += OnModelDownloadChanged;
        this.Closed += (_, __) => { if (_host != null) _host.ModelDownloadChanged -= OnModelDownloadChanged; };

        var wa = DisplayArea.Primary.WorkArea;
        int w = 660, h = 720;
        this.AppWindow.MoveAndResize(new RectInt32(wa.X + (wa.Width - w) / 2, wa.Y + (wa.Height - h) / 2, w, h));

        _steps = new FrameworkElement[] { Step0, Step1, Step2, Step3, Step4 };
        ShowStep(0);
        _ = LoadAsync();
    }

    private async Task LoadAsync()
    {
        string lang = await GetConfigString("languages.primary", "iw-IL");
        string hkMode = await GetConfigString("hotkeys.mode", "toggle");
        int? mic = await GetNullableInt("audio.microphone_device");

        var mics = await LoadMicrophonesAsync();
        bool modelReady = await IsOfflineModelReadyAsync();

        DispatcherQueue.TryEnqueue(() =>
        {
            _loading = true;
            SelectByTag(LanguageCombo, lang);
            PackLabel.Text = "פקודות קוליות: " + PackName(lang);

            MicCombo.Items.Clear();
            MicCombo.Items.Add(new ComboBoxItem { Content = "ברירת המחדל של Windows", Tag = "" });
            foreach (var (index, name) in mics)
                MicCombo.Items.Add(new ComboBoxItem { Content = name, Tag = index.ToString() });
            SelectMic(mic);

            // First run defaults to the offline-first path (works with no setup), so a user
            // who skips lands on a working product. Both engine choices run offline now;
            // Google is configured later in the Engine room, never claimed working here.
            OptOffline.IsChecked = true;

            if (hkMode == "push_to_talk") ModePtt.IsChecked = true; else ModeToggle.IsChecked = true;

            RenderOfflineReadiness(modelReady ? "ready" : "absent");
            _loading = false;
        });
    }

    /// <summary>Reflect offline-model readiness honestly. "ready" only when the model is on
    /// disk; otherwise we offer the one-time download (recommended). Offline dictation requires
    /// the model to be installed via this explicit flow — it is NEVER silently auto-downloaded on
    /// first use (Option A), so the copy never implies "just start and it will work".</summary>
    private void RenderOfflineReadiness(string state)
    {
        switch (state)
        {
            case "ready":
                OfflineReadyNote.Text = "מודל לא־מקוון מותקן ✓ — הכתבה לא־מקוונת מוכנה.";
                DownloadModelButton.Visibility = Visibility.Collapsed;
                DownloadRing.IsActive = false; DownloadRing.Visibility = Visibility.Collapsed;
                break;
            case "downloading":
                OfflineReadyNote.Text = "מוריד מודל לא־מקוון… (פעם אחת, דרוש אינטרנט). אפשר להמשיך בינתיים.";
                DownloadModelButton.Visibility = Visibility.Collapsed;
                DownloadRing.IsActive = true; DownloadRing.Visibility = Visibility.Visible;
                break;
            case "error":
                OfflineReadyNote.Text = "הורדת המודל נכשלה. הכתבה לא־מקוונת דורשת התקנת המודל — נסו שוב.";
                DownloadModelButton.Content = "נסו שוב";
                DownloadModelButton.Visibility = Visibility.Visible;
                DownloadRing.IsActive = false; DownloadRing.Visibility = Visibility.Collapsed;
                break;
            default: // "absent"
                OfflineReadyNote.Text = "הכתבה לא־מקוונת דורשת מודל (התקנה חד־פעמית, דרוש אינטרנט). התקינו אותו עכשיו כדי שההכתבה הלא־מקוונת תעבוד.";
                DownloadModelButton.Content = "התקן מודל לא־מקוון עכשיו (מומלץ)";
                DownloadModelButton.Visibility = Visibility.Visible;
                DownloadRing.IsActive = false; DownloadRing.Visibility = Visibility.Collapsed;
                break;
        }
    }

    private async void OnDownloadModel(object sender, RoutedEventArgs e)
    {
        RenderOfflineReadiness("downloading");
        if (_host?.Client == null) { RenderOfflineReadiness("error"); return; }
        try
        {
            var r = await _host.Client.RpcAsync("downloadModel");
            bool started = r.TryGetProperty("started", out var s) && s.GetBoolean();
            bool busy = r.TryGetProperty("busy", out var b) && b.GetBoolean();
            // running/done/error then arrive as ModelDownloadChanged events. Only revert if
            // the engine neither started nor was already downloading.
            if (!started && !busy) RenderOfflineReadiness("absent");
        }
        catch { RenderOfflineReadiness("error"); }
    }

    /// <summary>Live download progress from the engine. On "done" we re-query the authoritative
    /// model status rather than assume ready — so the ready copy can never show if the model is
    /// somehow still missing.</summary>
    private async void OnModelDownloadChanged(string state, string message)
    {
        if (state == "done")
        {
            bool ready = await IsOfflineModelReadyAsync();
            DispatcherQueue.TryEnqueue(() => RenderOfflineReadiness(ready ? "ready" : "absent"));
            return;
        }
        DispatcherQueue.TryEnqueue(() => RenderOfflineReadiness(
            state switch { "running" => "downloading", "error" => "error", _ => "absent" }));
    }

    private void ShowStep(int index)
    {
        _step = Math.Clamp(index, 0, _steps.Length - 1);
        for (int i = 0; i < _steps.Length; i++)
            _steps[i].Visibility = i == _step ? Visibility.Visible : Visibility.Collapsed;

        StepCounter.Text = $"שלב {_step + 1} מתוך {_steps.Length}";
        StepTitle.Text = _copy[_step].title;
        StepSubtitle.Text = _copy[_step].subtitle;

        bool last = _step == _steps.Length - 1;
        BackButton.Visibility = _step == 0 ? Visibility.Collapsed : Visibility.Visible;
        NextButton.Visibility = last ? Visibility.Collapsed : Visibility.Visible;
        FinishButton.Visibility = last ? Visibility.Visible : Visibility.Collapsed;
        SkipButton.Visibility = last ? Visibility.Collapsed : Visibility.Visible;
    }

    private void OnNext(object sender, RoutedEventArgs e) => ShowStep(_step + 1);
    private void OnBack(object sender, RoutedEventArgs e) => ShowStep(_step - 1);
    private async void OnSkip(object sender, RoutedEventArgs e) => await CompleteAsync();
    private async void OnFinish(object sender, RoutedEventArgs e) => await CompleteAsync();

    /// <summary>The X button funnels through the same completion as Skip, so closing can
    /// never leave a half-set state: we cancel the raw close, ensure a working offline
    /// baseline + the first-run flag persist, and only then close for real. If persistence
    /// fails — or a per-control save is still in flight — the window stays open (not marked
    /// complete) and the user can retry.</summary>
    private async void OnClosing(AppWindow sender, AppWindowClosingEventArgs args)
    {
        if (_done) return;            // a real close after successful completion
        args.Cancel = true;
        if (_busy || _completing) return;   // a save is in flight; don't race a second writer
        await CompleteAsync();
    }

    /// <summary>Finish / skip / close: guarantee a working engine (offline baseline if the
    /// user never chose one) and ONLY THEN mark first-run complete. The flag is written
    /// strictly after the baseline persists — if the baseline (or the flag) fails to save we
    /// report it, resync from disk, and stay open, so onboarding is never falsely marked done
    /// and the user is never left on a non-working engine.</summary>
    private async Task CompleteAsync()
    {
        if (_completing || _busy) return;
        _completing = true;
        SetBusy(true);
        try
        {
            // 1) Safe baseline first. MayMarkComplete encodes the ordering invariant.
            bool baselineOk = _engineApplied || await ApplyOffline();
            if (!MayMarkComplete(baselineOk)) { await ResyncAsync(); return; }

            // 2) Only now the first-run flag.
            if (!await Save("app.first_run_completed", true)) { await ResyncAsync(); return; }

            _done = true;
            try { this.Close(); } catch { }
        }
        finally
        {
            if (!_done) SetBusy(false);
            _completing = false;
        }
    }

    /// <summary>The first-run flag may be written ONLY after the safe baseline persisted.
    /// Pure + exposed so the self-test can pin the ordering against regressions.</summary>
    internal static bool MayMarkComplete(bool baselineSaved) => baselineSaved;

    private async void OnLanguageChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_loading) return;
        await Guarded(async () =>
        {
            string lang = (LanguageCombo.SelectedItem as FrameworkElement)?.Tag as string ?? "iw-IL";
            (string pack, string name) = LangPack.TryGetValue(lang, out var p) ? p : ("he", "עברית");
            // Stop on the first failure so we don't push a second key on top of an already
            // failed write; Guarded() then resyncs the UI from the actually-saved config.
            if (!await Save("languages.primary", lang)) return false;
            if (!await Save("languages.command_pack", pack)) return false;   // pack follows language
            PackLabel.Text = "פקודות קוליות: " + name;
            return true;
        });
    }

    private async void OnMicChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_loading) return;
        await Guarded(async () =>
        {
            string tag = (MicCombo.SelectedItem as FrameworkElement)?.Tag as string ?? "";
            object? value = int.TryParse(tag, out int idx) ? idx : (object?)null;
            return await Save("audio.microphone_device", value);
        });
    }

    private async void OnEngineChoice(object sender, RoutedEventArgs e)
    {
        if (_loading) return;
        string tag = (sender as FrameworkElement)?.Tag as string ?? "offline";
        await Guarded(async () =>
        {
            bool ok = tag == "recommended" ? await ApplyRecommended() : await ApplyOffline();
            // Only treat the engine as user-chosen once it actually persisted; otherwise a
            // later skip/close still applies the safe offline baseline.
            _engineApplied = ok;
            return ok;
        });
    }

    private Task<bool> ApplyRecommended() => ApplyEngine("recommended");
    private Task<bool> ApplyOffline() => ApplyEngine("offline");

    /// <summary>Apply an engine choice from the single-source-of-truth map (EngineConfig),
    /// stopping on the first failed write to minimize partial state.</summary>
    private async Task<bool> ApplyEngine(string tag)
    {
        foreach (var (key, value) in EngineConfig(tag))
            if (!await Save(key, value)) return false;
        return true;
    }

    private async void OnModeChanged(object sender, RoutedEventArgs e)
    {
        if (_loading) return;
        await Guarded(async () =>
        {
            string mode = (sender as FrameworkElement)?.Tag as string ?? "toggle";
            return await Save("hotkeys.mode", mode);   // takes effect next launch (listener boots once)
        });
    }

    private string PackName(string lang) => LangPack.TryGetValue(lang, out var p) ? p.name : "עברית";

    private void SelectByTag(ComboBox combo, string tag)
    {
        foreach (var obj in combo.Items)
            if (obj is FrameworkElement fe && (fe.Tag as string) == tag) { combo.SelectedItem = obj; return; }
        if (combo.Items.Count > 0) combo.SelectedIndex = 0;
    }

    private void SelectMic(int? saved)
    {
        if (saved is int idx)
            foreach (var obj in MicCombo.Items)
                if (obj is FrameworkElement fe && (fe.Tag as string) == idx.ToString()) { MicCombo.SelectedItem = obj; return; }
        MicCombo.SelectedIndex = 0;   // Windows default (or stale saved device falls back here)
    }

    private async Task<List<(int index, string name)>> LoadMicrophonesAsync()
    {
        var list = new List<(int, string)>();
        if (_host?.Client == null) return list;
        try
        {
            var r = await _host.Client.RpcAsync("listMicrophones");
            if (r.TryGetProperty("items", out var items) && items.ValueKind == JsonValueKind.Array)
                foreach (var it in items.EnumerateArray())
                {
                    int index = it.TryGetProperty("index", out var ix) ? ix.GetInt32() : -1;
                    string name = it.TryGetProperty("name", out var nm) ? nm.GetString() ?? "" : "";
                    if (index >= 0 && !string.IsNullOrWhiteSpace(name)) list.Add((index, name));
                }
        }
        catch { }
        return list;
    }

    /// <summary>Whether the local Whisper model is actually present on disk (getModelStatus).
    /// The single source of truth for the offline-readiness note — a config flag never proves
    /// offline works. Unknown (bridge issue) reads as not-ready, so we never over-promise.</summary>
    private async Task<bool> IsOfflineModelReadyAsync()
    {
        if (_host?.Client == null) return false;
        try
        {
            var r = await _host.Client.RpcAsync("getModelStatus");
            return r.TryGetProperty("downloaded", out var d) && d.ValueKind == JsonValueKind.True;
        }
        catch { return false; }
    }

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

    private async Task<int?> GetNullableInt(string key)
    {
        if (_host?.Client == null) return null;
        try
        {
            var r = await _host.Client.RpcAsync("getConfig", new { key });
            if (r.TryGetProperty("value", out var v) && v.ValueKind == JsonValueKind.Number) return v.GetInt32();
        }
        catch { }
        return null;
    }

    private async Task<bool> SetConfig(string key, object? value)
    {
        if (_host?.Client == null) return false;
        try
        {
            var r = await _host.Client.RpcAsync("setConfig", new { key, value });
            return r.TryGetProperty("saved", out var s) && s.GetBoolean();
        }
        catch { return false; }
    }

    /// <summary>Persist one key and surface a failure: the engine is the single writer, so
    /// if it reports the value was not saved we tell the user instead of silently advancing.</summary>
    private async Task<bool> Save(string key, object? value)
    {
        bool ok = await SetConfig(key, value);
        if (!ok) await ShowError();
        return ok;
    }

    /// <summary>Run a control's persistence as the single writer (no overlapping saves, and
    /// no advancing mid-write); on failure, resync every control from the actually-saved
    /// config so the UI never shows a value the engine rejected.</summary>
    private async Task Guarded(Func<Task<bool>> action)
    {
        if (_busy || _completing) return;
        SetBusy(true);
        try
        {
            if (!await action()) await ResyncAsync();
        }
        finally { SetBusy(false); }
    }

    private async Task ResyncAsync()
    {
        await LoadAsync();   // _loading guard suppresses write-back while re-selecting
    }

    /// <summary>Disable navigation while a write is in flight so the user can't advance,
    /// finish, or skip on top of a pending (or failed) save.</summary>
    private void SetBusy(bool busy)
    {
        _busy = busy;
        bool on = !busy;
        // Navigation.
        BackButton.IsEnabled = on;
        NextButton.IsEnabled = on;
        FinishButton.IsEnabled = on;
        SkipButton.IsEnabled = on;
        // Step inputs too, so a visible selection can't change on top of an in-flight save
        // (and so the shown value never diverges from what is actually being persisted).
        LanguageCombo.IsEnabled = on;
        MicCombo.IsEnabled = on;
        OptOffline.IsEnabled = on;
        OptRecommended.IsEnabled = on;
        ModeToggle.IsEnabled = on;
        ModePtt.IsEnabled = on;
    }

    private async Task ShowError()
    {
        if (this.Content?.XamlRoot == null) return;
        var dialog = new ContentDialog
        {
            Title = "לא ניתן לשמור כעת",
            Content = "בדקו שהמנוע פעיל ונסו שוב.",
            CloseButtonText = "סגור",
            XamlRoot = this.Content.XamlRoot,
            FlowDirection = FlowDirection.RightToLeft,
        };
        try { await dialog.ShowAsync(); } catch { }
    }

    // --- runtime self-test hooks ---
    internal int StepCountForTest => _steps.Length;
    internal int CurrentStepForTest => _step;
    internal void NextForTest() => ShowStep(_step + 1);
    internal void BackForTest() => ShowStep(_step - 1);
    internal bool FinishVisibleForTest => FinishButton.Visibility == Visibility.Visible;
    internal void RenderReadinessForTest(string state) => RenderOfflineReadiness(state);
    internal string OfflineNoteForTest => OfflineReadyNote.Text;
    internal bool DownloadButtonVisibleForTest => DownloadModelButton.Visibility == Visibility.Visible;
    internal bool DownloadRingActiveForTest => DownloadRing.IsActive;

    /// <summary>The plain-language -> config mapping for an engine choice — the single source
    /// of truth used by both ApplyEngine and the self-test, so the assertion can't drift from
    /// behavior.
    ///
    /// BOTH choices run truly offline (whisper_local / local) right now. Recommended does NOT
    /// switch to Google here: without credentials the cloud provider throws at startup before
    /// auto_fallback can engage, so claiming offline-via-fallback would be false. Recommended
    /// only pre-seeds the Google model so that when the user adds a key in the Engine room the
    /// upgrade is one step. We never persist api/auto_fallback without credentials.</summary>
    internal static (string key, object value)[] EngineConfig(string tag) => tag == "recommended"
        ? new (string, object)[] { ("stt.provider", "whisper_local"), ("providers.whisper.enabled", true), ("stt.mode", "local"), ("google.model", "chirp_3") }
        : new (string, object)[] { ("stt.provider", "whisper_local"), ("providers.whisper.enabled", true), ("stt.mode", "local") };
}
