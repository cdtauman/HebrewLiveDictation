using System;
using System.Collections.Generic;
using System.Text.Json;
using System.Threading.Tasks;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
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

    public ControlsPage() => this.InitializeComponent();

    protected override void OnNavigatedTo(NavigationEventArgs e)
    {
        _host = e.Parameter as AppHost;
        _ = LoadAsync();
    }

    private async Task LoadAsync()
    {
        string hotkey = await GetString("hotkeys.hotkey", "f8");
        string mode = await GetString("hotkeys.mode", "toggle");
        bool hud = await GetBool("app.show_overlay", true);
        bool remote = await GetBool("toolbar.enabled", false);

        DispatcherQueue.TryEnqueue(() =>
        {
            _loading = true;
            HotkeyText.Text = FormatHotkey(hotkey);
            if (mode == "push_to_talk") ModePtt.IsChecked = true; else ModeToggle.IsChecked = true;
            ApplyHotkeyHint(mode);
            HudToggle.IsOn = hud;
            RemoteToggle.IsOn = remote;
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

    private async void OnModeChoice(object sender, RoutedEventArgs e)
    {
        if (_loading) return;
        string mode = (sender as FrameworkElement)?.Tag as string ?? "toggle";
        ApplyHotkeyHint(mode);
        await Persist("hotkeys.mode", mode);   // applies on next launch (hotkey listener boots once)
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

    // Note: start/stop sounds are deferred — the WinUI engine path does not play them yet,
    // so the control is disabled in XAML rather than writing a setting that has no effect.

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

    private static string FormatHotkey(string raw)
        => string.IsNullOrWhiteSpace(raw) ? "—" : raw.ToUpperInvariant().Replace("+", " + ");

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
