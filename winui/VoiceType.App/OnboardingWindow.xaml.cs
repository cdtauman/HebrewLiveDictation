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
    private readonly AppHost _host;
    private bool _loading;
    private bool _engineApplied;   // did the user explicitly choose an engine?
    private bool _completing;      // re-entrancy guard for finish/skip/close
    private bool _done;            // completion succeeded -> a real close is allowed
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
            // who skips lands on a working product. Picking Recommended upgrades to Google
            // while keeping the offline backup, so they are never broken either way.
            OptOffline.IsChecked = true;

            if (hkMode == "push_to_talk") ModePtt.IsChecked = true; else ModeToggle.IsChecked = true;
            _loading = false;
        });
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
    /// fails the window stays open (not marked complete) and the user is told.</summary>
    private async void OnClosing(AppWindow sender, AppWindowClosingEventArgs args)
    {
        if (_done) return;            // a real close after successful completion
        args.Cancel = true;
        await CompleteAsync();
    }

    /// <summary>Finish / skip / close: guarantee a working engine (offline baseline if the
    /// user never chose one), then mark first-run complete. Only closes if BOTH persist;
    /// otherwise it reports the failure, resyncs from disk, and stays open so onboarding is
    /// never falsely marked done.</summary>
    private async Task CompleteAsync()
    {
        if (_completing) return;
        _completing = true;
        SetBusy(true);
        try
        {
            bool ok = _engineApplied || await ApplyOffline();
            ok = await Save("app.first_run_completed", true) && ok;
            if (!ok)
            {
                await ResyncAsync();
                return;               // stays open, NOT marked complete
            }
            _done = true;
            try { this.Close(); } catch { }
        }
        finally
        {
            if (!_done) SetBusy(false);
            _completing = false;
        }
    }

    private async void OnLanguageChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_loading) return;
        await Guarded(async () =>
        {
            string lang = (LanguageCombo.SelectedItem as FrameworkElement)?.Tag as string ?? "iw-IL";
            (string pack, string name) = LangPack.TryGetValue(lang, out var p) ? p : ("he", "עברית");
            bool ok = await Save("languages.primary", lang);
            ok = await Save("languages.command_pack", pack) && ok;   // pack follows language
            if (ok) PackLabel.Text = "פקודות קוליות: " + name;
            return ok;
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

    /// <summary>Apply an engine choice from the single-source-of-truth map (EngineConfig).</summary>
    private async Task<bool> ApplyEngine(string tag)
    {
        bool ok = true;
        foreach (var (key, value) in EngineConfig(tag))
            ok = await Save(key, value) && ok;
        return ok;
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

    /// <summary>Run a control's persistence with the wizard buttons disabled (no advancing
    /// mid-write); on failure, resync every control from the actually-saved config so the UI
    /// never shows a value the engine rejected.</summary>
    private async Task Guarded(Func<Task<bool>> action)
    {
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
        bool on = !busy;
        BackButton.IsEnabled = on;
        NextButton.IsEnabled = on;
        FinishButton.IsEnabled = on;
        SkipButton.IsEnabled = on;
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

    /// <summary>The plain-language -> config mapping for an engine choice — the single source
    /// of truth used by both ApplyEngine and the self-test, so the assertion can't drift from
    /// behavior. Offline is truly local; Recommended keeps the offline backup (auto_fallback +
    /// Whisper), never plain cloud (api) without credentials.</summary>
    internal static (string key, object value)[] EngineConfig(string tag) => tag == "recommended"
        ? new (string, object)[] { ("stt.provider", "google_v2"), ("google.model", "chirp_3"), ("providers.whisper.enabled", true), ("stt.mode", "auto_fallback") }
        : new (string, object)[] { ("stt.provider", "whisper_local"), ("providers.whisper.enabled", true), ("stt.mode", "local") };
}
