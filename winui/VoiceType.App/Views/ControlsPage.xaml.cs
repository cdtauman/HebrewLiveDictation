using System;
using System.Collections.Generic;
using System.Text.Json;
using System.Threading.Tasks;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Controls.Primitives;
using Microsoft.UI.Xaml.Navigation;

namespace VoiceType.Shell.Views;

/// <summary>
/// Controls room: trigger (hotkey + toggle/push-to-talk), the on-screen surfaces
/// (Voice HUD + Remote — toggled LIVE through AppHost), and start/stop sounds. The
/// engine stays the single config writer; visibility toggles also take effect now.
/// </summary>
public sealed partial class ControlsPage : Page
{
    private AppHost? _host;
    private bool _loading;
    private string _savedPauseHotkey = "";

    public ControlsPage() => this.InitializeComponent();

    protected override void OnNavigatedTo(NavigationEventArgs e)
    {
        _host = e.Parameter as AppHost;
        _ = LoadAsync();
    }

    private async Task LoadAsync()
    {
        string hotkey = await GetString("hotkeys.hotkey", "f8");
        string pauseHotkey = await GetString("hotkeys.pause_hotkey", "");
        string mode = await GetString("hotkeys.mode", "toggle");
        bool hud = await GetBool("app.show_overlay", true);
        bool remote = await GetBool("toolbar.enabled", false);
        bool sound = await GetBool("audio.feedback_enabled", false);
        int soundVolume = await GetInt("audio.feedback_volume", 50);
        int frameMs = await GetInt("speech.frame_ms", 100);
        bool endpointing = await GetBool("speech.endpointing", true);
        bool autoStop = await GetBool("speech.auto_stop_on_silence", false);
        double startTimeout = await GetDouble("speech.speech_start_timeout_seconds", 5.0);
        double endTimeout = await GetDouble("speech.speech_end_timeout_seconds", 1.0);
        bool vad = await GetBool("speech.vad_enabled", false);
        double vadThreshold = await GetDouble("speech.vad_threshold", 0.5);
        int vadPadding = await GetInt("speech.vad_padding_ms", 240);
        int vadMinSilence = await GetInt("speech.vad_min_silence_ms", 500);
        int segmentSilence = await GetInt("providers.whisper.segment_silence_ms", 700);

        DispatcherQueue.TryEnqueue(() =>
        {
            _loading = true;
            PopulateHotkeys(hotkey);
            PopulatePauseHotkeys(pauseHotkey);
            if (mode == "push_to_talk") ModePtt.IsChecked = true; else ModeToggle.IsChecked = true;
            ApplyHotkeyHint(mode);
            HudToggle.IsOn = hud;
            RemoteToggle.IsOn = remote;
            SoundToggle.IsOn = sound;
            SoundVolumeSlider.Value = soundVolume;
            UpdateSoundVolumeLabel(soundVolume);
            ApplySoundAvailability();
            PopulateFrames(frameMs);
            EndpointToggle.IsOn = endpointing;
            AutoStopToggle.IsOn = autoStop;
            SpeechStartTimeoutBox.Value = startTimeout;
            SpeechEndTimeoutBox.Value = endTimeout;
            VadToggle.IsOn = vad;
            VadThresholdSlider.Value = vadThreshold;
            UpdateVadThresholdLabel(vadThreshold);
            VadPaddingBox.Value = vadPadding;
            VadMinSilenceBox.Value = vadMinSilence;
            SegmentSilenceBox.Value = segmentSilence;
            ApplyAudioAvailability();
            _loading = false;
        });

        await LoadMicrophonesAsync();
    }

    private async Task LoadMicrophonesAsync()
    {
        var items = new List<(int index, string name)>();
        if (_host?.Client != null)
        {
            try
            {
                var res = await _host.Client.RpcAsync("listMicrophones");
                if (res.TryGetProperty("items", out var arr) && arr.ValueKind == JsonValueKind.Array)
                    foreach (var it in arr.EnumerateArray())
                    {
                        int idx = it.TryGetProperty("index", out var ix) && ix.TryGetInt32(out var n) ? n : -1;
                        string name = it.TryGetProperty("name", out var nm) ? nm.GetString() ?? "" : "";
                        if (idx >= 0 && !string.IsNullOrEmpty(name)) items.Add((idx, name));
                    }
            }
            catch { }
        }
        int? current = await GetNullableInt("audio.microphone_device");

        DispatcherQueue.TryEnqueue(() =>
        {
            _loading = true;
            MicCombo.Items.Clear();
            MicCombo.Items.Add(new ComboBoxItem { Content = "ברירת המחדל של Windows", Tag = "" });
            foreach (var (index, name) in items)
                MicCombo.Items.Add(new ComboBoxItem { Content = name, Tag = index.ToString() });
            SelectMic(current);
            _loading = false;
        });
    }

    private void SelectMic(int? index)
    {
        string target = index?.ToString() ?? "";
        foreach (var obj in MicCombo.Items)
            if (obj is ComboBoxItem ci && (ci.Tag as string) == target) { MicCombo.SelectedItem = obj; return; }
        MicCombo.SelectedIndex = 0;   // saved device no longer present -> fall back to Windows default
    }

    private async void OnMicChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_loading) return;
        string tag = (MicCombo.SelectedItem as ComboBoxItem)?.Tag as string ?? "";
        // Empty tag = Windows default, persisted as null (the engine treats null as default).
        object? value = string.IsNullOrEmpty(tag) ? null : (int.TryParse(tag, out var n) ? n : null);
        await Persist("audio.microphone_device", value);
    }

    private static readonly (int value, string label)[] FramePresets =
    {
        (50, "50 ms"),
        (100, "100 ms"),
        (200, "200 ms"),
    };

    private void PopulateFrames(int current)
    {
        FrameCombo.Items.Clear();
        ComboBoxItem? selected = null;
        foreach (var (value, label) in FramePresets)
        {
            var item = new ComboBoxItem { Content = label, Tag = value.ToString() };
            FrameCombo.Items.Add(item);
            if (value == current) selected = item;
        }
        if (selected == null && current > 0)
        {
            selected = new ComboBoxItem { Content = $"{current} ms", Tag = current.ToString() };
            FrameCombo.Items.Add(selected);
        }
        FrameCombo.SelectedItem = selected ?? (FrameCombo.Items.Count > 0 ? FrameCombo.Items[1] : null);
    }

    private async void OnFrameChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_loading) return;
        string tag = (FrameCombo.SelectedItem as ComboBoxItem)?.Tag as string ?? "100";
        if (int.TryParse(tag, out var frameMs))
            await Persist("speech.frame_ms", frameMs);
    }

    private async void OnEndpointingToggled(object sender, RoutedEventArgs e)
    {
        if (_loading) return;
        ApplyAudioAvailability();
        await Persist("speech.endpointing", EndpointToggle.IsOn);
    }

    private async void OnAutoStopToggled(object sender, RoutedEventArgs e)
    {
        if (_loading) return;
        ApplyAudioAvailability();
        await Persist("speech.auto_stop_on_silence", AutoStopToggle.IsOn);
    }

    private async void OnVadToggled(object sender, RoutedEventArgs e)
    {
        if (_loading) return;
        ApplyAudioAvailability();
        await Persist("speech.vad_enabled", VadToggle.IsOn);
    }

    private async void OnVadThresholdChanged(object sender, RangeBaseValueChangedEventArgs e)
    {
        UpdateVadThresholdLabel(e.NewValue);
        if (_loading) return;
        await Persist("speech.vad_threshold", Math.Round(e.NewValue, 2));
    }

    private async void OnAudioIntChanged(NumberBox sender, NumberBoxValueChangedEventArgs args)
    {
        if (_loading) return;
        string key = sender.Tag as string ?? "";
        if (string.IsNullOrWhiteSpace(key)) return;
        int value = CoerceInt(sender, args.NewValue);
        sender.Value = value;
        await Persist(key, value);
    }

    private async void OnAudioDoubleChanged(NumberBox sender, NumberBoxValueChangedEventArgs args)
    {
        if (_loading) return;
        string key = sender.Tag as string ?? "";
        if (string.IsNullOrWhiteSpace(key)) return;
        double value = CoerceDouble(sender, args.NewValue);
        sender.Value = value;
        await Persist(key, value);
    }

    private static int CoerceInt(NumberBox box, double value)
    {
        if (double.IsNaN(value) || double.IsInfinity(value)) value = box.Minimum;
        return (int)Math.Round(Math.Clamp(value, box.Minimum, box.Maximum));
    }

    private static double CoerceDouble(NumberBox box, double value)
    {
        if (double.IsNaN(value) || double.IsInfinity(value)) value = box.Minimum;
        return Math.Round(Math.Clamp(value, box.Minimum, box.Maximum), 1);
    }

    private void UpdateVadThresholdLabel(double value)
        => VadThresholdValue.Text = Math.Round(value, 2).ToString("0.00");

    private void ApplyAudioAvailability()
    {
        bool endpointing = EndpointToggle.IsOn;
        bool autoStop = AutoStopToggle.IsOn;
        bool vad = VadToggle.IsOn;

        AutoStopToggle.IsEnabled = endpointing;
        SpeechStartTimeoutBox.IsEnabled = endpointing && autoStop;
        SpeechEndTimeoutBox.IsEnabled = endpointing && autoStop;

        VadThresholdSlider.IsEnabled = vad;
        VadPaddingBox.IsEnabled = vad;
        VadMinSilenceBox.IsEnabled = vad;
        SegmentSilenceBox.IsEnabled = vad;
    }

    // ---- runtime self-test hooks (render only; no RPC/audio) ----
    internal void RenderAudioAdvancedForTest(bool vad, bool endpointing, bool autoStop)
    {
        VadToggle.IsOn = vad;
        EndpointToggle.IsOn = endpointing;
        AutoStopToggle.IsOn = autoStop;
        ApplyAudioAvailability();
    }
    internal bool VadControlsEnabledForTest =>
        VadThresholdSlider.IsEnabled && VadPaddingBox.IsEnabled && VadMinSilenceBox.IsEnabled && SegmentSilenceBox.IsEnabled;
    internal bool AutoStopControlsEnabledForTest =>
        SpeechStartTimeoutBox.IsEnabled && SpeechEndTimeoutBox.IsEnabled;
    internal bool AutoStopToggleEnabledForTest => AutoStopToggle.IsEnabled;
    internal void RenderSoundForTest(bool enabled, int volume)
    {
        _loading = true;
        try
        {
            SoundToggle.IsOn = enabled;
            SoundVolumeSlider.Value = Math.Clamp(volume, 0, 100);
            UpdateSoundVolumeLabel(SoundVolumeSlider.Value);
            ApplySoundAvailability();
        }
        finally { _loading = false; }
    }
    internal bool SoundVolumeEnabledForTest => SoundVolumeSlider.IsEnabled;
    internal string SoundVolumeTextForTest => SoundVolumeValue.Text;

    private async void OnModeChoice(object sender, RoutedEventArgs e)
    {
        if (_loading) return;
        string mode = (sender as FrameworkElement)?.Tag as string ?? "toggle";
        ApplyHotkeyHint(mode);
        await Persist("hotkeys.mode", mode);   // applies on next launch (hotkey listener boots once)
    }

    // Curated, engine-supported hotkeys (the engine accepts function keys, the Copilot key, and
    // combos; we offer a safe shortlist plus whatever is currently saved). Tag = engine string.
    private static readonly (string tag, string label)[] HotkeyPresets =
    {
        ("f2", "F2"), ("f3", "F3"), ("f4", "F4"), ("f6", "F6"), ("f7", "F7"),
        ("f8", "F8"), ("f9", "F9"), ("f10", "F10"), ("f11", "F11"), ("f12", "F12"),
        ("copilot", "מקש Copilot"),
    };

    private static readonly (string tag, string label)[] PauseHotkeyPresets =
    {
        ("", "ללא"),
        ("f9", "F9"),
        ("f10", "F10"),
        ("f11", "F11"),
        ("f12", "F12"),
    };

    /// <summary>Build the hotkey list and select the saved value (adding it if it isn't a preset,
    /// e.g. a custom combo), so a rebind never silently loses the current binding.</summary>
    private void PopulateHotkeys(string current)
    {
        current = (current ?? "").Trim().ToLowerInvariant();
        HotkeyCombo.Items.Clear();
        bool matched = false;
        foreach (var (tag, label) in HotkeyPresets)
        {
            var item = new ComboBoxItem { Content = label, Tag = tag };
            HotkeyCombo.Items.Add(item);
            if (tag == current) { HotkeyCombo.SelectedItem = item; matched = true; }
        }
        if (!matched && current.Length > 0)
        {
            var item = new ComboBoxItem { Content = current.ToUpperInvariant().Replace("+", " + "), Tag = current };
            HotkeyCombo.Items.Add(item);
            HotkeyCombo.SelectedItem = item;
        }
        if (HotkeyCombo.SelectedItem == null && HotkeyCombo.Items.Count > 0) HotkeyCombo.SelectedIndex = 0;
        HotkeyConflict.Visibility = current == "copilot" ? Visibility.Visible : Visibility.Collapsed;
    }

    private void PopulatePauseHotkeys(string current)
    {
        current = (current ?? "").Trim().ToLowerInvariant();
        _savedPauseHotkey = current;
        PauseHotkeyCombo.Items.Clear();
        bool matched = false;
        foreach (var (tag, label) in PauseHotkeyPresets)
        {
            var item = new ComboBoxItem { Content = label, Tag = tag };
            PauseHotkeyCombo.Items.Add(item);
            if (tag == current) { PauseHotkeyCombo.SelectedItem = item; matched = true; }
        }
        if (!matched && current.Length > 0)
        {
            var item = new ComboBoxItem { Content = current.ToUpperInvariant().Replace("+", " + "), Tag = current };
            PauseHotkeyCombo.Items.Add(item);
            PauseHotkeyCombo.SelectedItem = item;
        }
        if (PauseHotkeyCombo.SelectedItem == null && PauseHotkeyCombo.Items.Count > 0) PauseHotkeyCombo.SelectedIndex = 0;
        PauseHotkeyConflict.Visibility = Visibility.Collapsed;
    }

    private string SelectedMainHotkey()
        => (HotkeyCombo.SelectedItem as ComboBoxItem)?.Tag as string ?? "f8";

    private string SelectedPauseHotkey()
        => (PauseHotkeyCombo.SelectedItem as ComboBoxItem)?.Tag as string ?? "";

    /// <summary>Persist the new hotkey AND apply it to the running listener immediately
    /// (reloadHotkeys), then surface any conflict (e.g. the Copilot key) so the user isn't
    /// left with a binding that silently never fires.</summary>
    private async void OnHotkeyChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_loading) return;
        string tag = SelectedMainHotkey();
        if (!await Persist("hotkeys.hotkey", tag)) return;
        if (!string.IsNullOrEmpty(_savedPauseHotkey) && _savedPauseHotkey == tag)
        {
            if (await Persist("hotkeys.pause_hotkey", ""))
            {
                _loading = true;
                PopulatePauseHotkeys("");
                _loading = false;
            }
        }
        bool conflict = await ReloadHotkeysAndMainConflictAsync();
        DispatcherQueue.TryEnqueue(() =>
            HotkeyConflict.Visibility = conflict ? Visibility.Visible : Visibility.Collapsed);
    }

    private async void OnPauseHotkeyChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_loading) return;
        string tag = SelectedPauseHotkey();
        string main = SelectedMainHotkey();
        if (!string.IsNullOrEmpty(tag) && tag == main)
        {
            PauseHotkeyConflict.Visibility = Visibility.Visible;
            await ShowMessageAsync("מקש כבר בשימוש", "מקש ההשהיה צריך להיות שונה ממקש ההתחלה/עצירה.");
            _loading = true;
            PopulatePauseHotkeys(_savedPauseHotkey);
            _loading = false;
            return;
        }
        if (!await Persist("hotkeys.pause_hotkey", tag)) return;
        _savedPauseHotkey = tag;
        PauseHotkeyConflict.Visibility = Visibility.Collapsed;
        await ReloadHotkeysAndMainConflictAsync();
    }

    private async Task<bool> ReloadHotkeysAndMainConflictAsync()
    {
        bool conflict = false;
        if (_host?.Client != null)
        {
            try
            {
                var r = await _host.Client.RpcAsync("reloadHotkeys");
                conflict = r.TryGetProperty("conflict", out var c) && c.ValueKind == JsonValueKind.True;
            }
            catch { }
        }
        return conflict;
    }

    private void ApplyHotkeyHint(string mode)
        => HotkeyHint.Text = mode == "push_to_talk"
            ? "החזקת המקש מקליטה; שחרורו עוצר ומכתיב."
            : "לחיצה מפעילה ולחיצה נוספת עוצרת — בכל מקום.";

    private async void OnHudToggled(object sender, RoutedEventArgs e)
    {
        if (_loading) return;
        if (await Persist("app.show_overlay", HudToggle.IsOn)) _host?.SetHudVisible(HudToggle.IsOn);
    }

    private async void OnRemoteToggled(object sender, RoutedEventArgs e)
    {
        if (_loading) return;
        if (await Persist("toolbar.enabled", RemoteToggle.IsOn)) _host?.SetRemoteVisible(RemoteToggle.IsOn);
    }

    private async void OnSoundToggled(object sender, RoutedEventArgs e)
    {
        if (_loading) return;
        ApplySoundAvailability();
        if (await Persist("audio.feedback_enabled", SoundToggle.IsOn))
            _host?.SetAudioFeedback(SoundToggle.IsOn, CurrentSoundVolume());
    }

    private async void OnSoundVolumeChanged(object sender, RangeBaseValueChangedEventArgs e)
    {
        int value = (int)Math.Round(e.NewValue);
        UpdateSoundVolumeLabel(value);
        if (_loading) return;
        if (await Persist("audio.feedback_volume", value))
            _host?.SetAudioFeedback(SoundToggle.IsOn, value);
    }

    private int CurrentSoundVolume()
        => (int)Math.Round(Math.Clamp(SoundVolumeSlider.Value, SoundVolumeSlider.Minimum, SoundVolumeSlider.Maximum));

    private void UpdateSoundVolumeLabel(double value)
        => SoundVolumeValue.Text = ((int)Math.Round(Math.Clamp(value, 0, 100))).ToString();

    private void ApplySoundAvailability()
        => SoundVolumeSlider.IsEnabled = SoundToggle.IsOn;

    /// <summary>Write a setting; on failure tell the user and resync the UI from the
    /// actually-persisted config so a control never *looks* set when it isn't.</summary>
    private async Task<bool> Persist(string key, object? value)
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
            if (r.TryGetProperty("value", out var v))
            {
                if (v.ValueKind == JsonValueKind.Number && v.TryGetInt32(out var n)) return n;
                if (v.ValueKind == JsonValueKind.String && int.TryParse(v.GetString(), out var s)) return s;
            }
        }
        catch { }
        return fallback;
    }

    private async Task<double> GetDouble(string key, double fallback)
    {
        if (_host?.Client == null) return fallback;
        try
        {
            var r = await _host.Client.RpcAsync("getConfig", new { key });
            if (r.TryGetProperty("value", out var v))
            {
                if (v.ValueKind == JsonValueKind.Number && v.TryGetDouble(out var n)) return n;
                if (v.ValueKind == JsonValueKind.String && double.TryParse(v.GetString(), out var s)) return s;
            }
        }
        catch { }
        return fallback;
    }

    private async Task<int?> GetNullableInt(string key)
    {
        if (_host?.Client == null) return null;
        try
        {
            var r = await _host.Client.RpcAsync("getConfig", new { key });
            if (r.TryGetProperty("value", out var v) && v.ValueKind == JsonValueKind.Number
                && v.TryGetInt32(out var n)) return n;
        }
        catch { }
        return null;
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
