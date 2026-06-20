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
    private int _step;

    private FrameworkElement[] _steps = Array.Empty<FrameworkElement>();
    private static readonly (string title, string subtitle)[] _copy =
    {
        ("ברוכים הבאים", "כמה צעדים קצרים ואפשר להכתיב."),
        ("מיקרופון", "באיזה מיקרופון להשתמש?"),
        ("בחירת מנוע", "איך תרצו שההכתבה תעבוד?"),
        ("מקש ההפעלה", "איך להפעיל ולעצור הכתבה?"),
        ("מוכן", "אפשר להתחיל."),
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

    /// <summary>Finish or skip: guarantee a working engine (offline baseline if the user
    /// never chose one), mark first run complete, and close.</summary>
    private async Task CompleteAsync()
    {
        if (!_engineApplied)
            await ApplyOffline();
        await SetConfig("app.first_run_completed", true);
        try { this.Close(); } catch { }
    }

    private async void OnLanguageChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_loading) return;
        string lang = (LanguageCombo.SelectedItem as FrameworkElement)?.Tag as string ?? "iw-IL";
        (string pack, string name) = LangPack.TryGetValue(lang, out var p) ? p : ("he", "עברית");
        await SetConfig("languages.primary", lang);
        await SetConfig("languages.command_pack", pack);
        PackLabel.Text = "פקודות קוליות: " + name;
    }

    private async void OnMicChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_loading) return;
        string tag = (MicCombo.SelectedItem as FrameworkElement)?.Tag as string ?? "";
        object? value = int.TryParse(tag, out int idx) ? idx : (object?)null;
        await SetConfig("audio.microphone_device", value);
    }

    private async void OnEngineChoice(object sender, RoutedEventArgs e)
    {
        if (_loading) return;
        string tag = (sender as FrameworkElement)?.Tag as string ?? "offline";
        _engineApplied = true;
        if (tag == "recommended")
        {
            // Google Chirp 3, but keep offline backup on so the product works NOW and
            // upgrades once the user adds the Google key in the Engine room — never broken.
            await SetConfig("stt.provider", "google_v2");
            await SetConfig("google.model", "chirp_3");
            await SetConfig("providers.whisper.enabled", true);
            await SetConfig("stt.mode", "auto_fallback");
        }
        else
        {
            await ApplyOffline();
        }
    }

    private async Task ApplyOffline()
    {
        await SetConfig("stt.provider", "whisper_local");
        await SetConfig("providers.whisper.enabled", true);
        await SetConfig("stt.mode", "local");
    }

    private async void OnModeChanged(object sender, RoutedEventArgs e)
    {
        if (_loading) return;
        string mode = (sender as FrameworkElement)?.Tag as string ?? "toggle";
        await SetConfig("hotkeys.mode", mode);   // applies on next launch (the hotkey listener boots once)
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

    // --- runtime self-test hooks (navigation only; no config writes) ---
    internal int StepCountForTest => _steps.Length;
    internal int CurrentStepForTest => _step;
    internal void NextForTest() => ShowStep(_step + 1);
    internal void BackForTest() => ShowStep(_step - 1);
    internal bool FinishVisibleForTest => FinishButton.Visibility == Visibility.Visible;
}
