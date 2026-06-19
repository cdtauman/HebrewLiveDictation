using System;
using System.Collections.Generic;
using System.Text.Json;
using System.Threading.Tasks;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;

namespace VoiceType.Shell.Views;

public sealed class CommandRow
{
    public string Say { get; set; } = "";
    public string Effect { get; set; } = "";
}

/// <summary>
/// Dictation room: language, punctuation behavior, and a live voice-command reference
/// (from the engine's active command pack). Config changes apply to the next dictation
/// session; the engine stays the single config writer. Command pack follows the language.
/// </summary>
public sealed partial class DictationPage : Page
{
    private AppHost? _host;
    private bool _loading;

    // language code -> (command pack key, Hebrew pack name for the caption)
    private static readonly Dictionary<string, (string pack, string name)> LangPack = new()
    {
        ["iw-IL"] = ("he", "עברית"),
        ["en-US"] = ("en", "אנגלית"),
        ["ar-XA"] = ("ar", "ערבית"),
        ["ru-RU"] = ("ru", "רוסית"),
        ["fr-FR"] = ("fr", "צרפתית"),
        ["es-ES"] = ("es", "ספרדית"),
    };

    public DictationPage() => this.InitializeComponent();

    protected override void OnNavigatedTo(NavigationEventArgs e)
    {
        _host = e.Parameter as AppHost;
        _ = LoadAsync();
    }

    private async Task LoadAsync()
    {
        string lang = await GetString("languages.primary", "iw-IL");
        bool autoPunct = await GetBool("google.automatic_punctuation", true);
        bool spokenPunct = await GetBool("google.enable_spoken_punctuation", false);

        DispatcherQueue.TryEnqueue(() =>
        {
            _loading = true;
            SelectLanguage(lang);
            AutoPunctToggle.IsOn = autoPunct;
            SpokenPunctToggle.IsOn = spokenPunct;
            PackLabel.Text = "פקודות קוליות: " + PackName(lang);
            _loading = false;
        });

        await LoadCommandsAsync();
    }

    private async void OnLanguageChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_loading) return;
        string lang = SelectedLanguage();
        (string pack, string name) = LangPack.TryGetValue(lang, out var p) ? p : ("he", "עברית");
        bool ok = await Persist("languages.primary", lang);
        ok &= await Persist("languages.command_pack", pack);   // keep the pack consistent with language
        if (!ok) return;
        PackLabel.Text = "פקודות קוליות: " + name;
        await LoadCommandsAsync();
    }

    private async void OnAutoPunctToggled(object sender, RoutedEventArgs e)
    {
        if (_loading) return;
        await Persist("google.automatic_punctuation", AutoPunctToggle.IsOn);
    }

    private async void OnSpokenPunctToggled(object sender, RoutedEventArgs e)
    {
        if (_loading) return;
        await Persist("google.enable_spoken_punctuation", SpokenPunctToggle.IsOn);
    }

    private async Task LoadCommandsAsync()
    {
        var punct = new List<CommandRow>();
        var actions = new List<CommandRow>();
        if (_host?.Client != null)
        {
            try
            {
                var res = await _host.Client.RpcAsync("getCommands");
                Fill(res, "punctuation", "inserts", punct);
                Fill(res, "actions", "does", actions);
            }
            catch { }
        }
        DispatcherQueue.TryEnqueue(() =>
        {
            PunctuationList.ItemsSource = punct;
            ActionsList.ItemsSource = actions;
        });
    }

    private static void Fill(JsonElement res, string array, string effectKey, List<CommandRow> into)
    {
        if (!res.TryGetProperty(array, out var arr) || arr.ValueKind != JsonValueKind.Array) return;
        foreach (var it in arr.EnumerateArray())
        {
            string say = it.TryGetProperty("say", out var s) ? s.GetString() ?? "" : "";
            string effect = it.TryGetProperty(effectKey, out var ef) ? ef.GetString() ?? "" : "";
            if (!string.IsNullOrEmpty(say)) into.Add(new CommandRow { Say = say, Effect = effect });
        }
    }

    private void SelectLanguage(string code)
    {
        foreach (var obj in LanguageCombo.Items)
            if (obj is FrameworkElement fe && fe.Tag as string == code) { LanguageCombo.SelectedItem = obj; return; }
        LanguageCombo.SelectedIndex = 0;
    }

    private string SelectedLanguage() => (LanguageCombo.SelectedItem as FrameworkElement)?.Tag as string ?? "iw-IL";

    private static string PackName(string lang) => LangPack.TryGetValue(lang, out var p) ? p.name : "עברית";

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
