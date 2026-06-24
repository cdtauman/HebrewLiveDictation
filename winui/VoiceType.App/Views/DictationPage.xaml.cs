using System;
using System.Collections.Generic;
using System.Linq;
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
/// session; the engine stays the single config writer. Language changes choose a sane
/// command pack, and users can override it.
/// </summary>
public sealed partial class DictationPage : Page
{
    private AppHost? _host;
    private bool _loading;

    // iw-IL is Google's documented Hebrew code. he-IL is exposed only as a diagnostic alias so
    // runtime logs/probes can prove whether Google accepts it for a given project/model/region.
    internal static readonly (string tag, string label)[] Languages =
    {
        ("iw-IL", "עברית (iw-IL)"),
        ("he-IL", "עברית (he-IL · ניסיוני)"),
        ("en-US", "English (US)"),
        ("ar-XA", "العربية"),
        ("ru-RU", "Русский"),
        ("fr-FR", "Français"),
        ("es-ES", "Español"),
    };

    internal static readonly (string tag, string label)[] CommandPacks =
    {
        ("he", "Hebrew"),
        ("en", "English"),
        ("ar", "Arabic"),
        ("ru", "Russian"),
        ("fr", "French"),
        ("es", "Spanish"),
    };

    // language code -> (command pack key, Hebrew pack name for the caption)
    private static readonly Dictionary<string, (string pack, string name)> LangPack = new()
    {
        ["iw-IL"] = ("he", "עברית"),
        ["he-IL"] = ("he", "עברית"),   // alt Hebrew code for Google; Offline maps it to 'he' too
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
        string commandPack = await GetString("languages.command_pack", PackForLanguage(lang));
        bool autoPunct = await GetBool("google.automatic_punctuation", true);
        bool spokenPunct = await GetBool("google.enable_spoken_punctuation", false);
        bool spokenEmoji = await GetBool("google.enable_spoken_emoji", false);
        double phraseBoost = await GetDouble("google.phrase_boost", 15.0);
        var customPhrases = await GetStringList("languages.custom_phrases");

        DispatcherQueue.TryEnqueue(() =>
        {
            _loading = true;
            PopulateLanguages();
            PopulateCommandPacks();
            SelectLanguage(lang);
            SelectCommandPack(commandPack);
            AutoPunctToggle.IsOn = autoPunct;
            SpokenPunctToggle.IsOn = spokenPunct;
            SpokenEmojiToggle.IsOn = spokenEmoji;
            PhraseBoostSlider.Value = CoercePhraseBoost(phraseBoost);
            UpdatePhraseBoostLabel(PhraseBoostSlider.Value);
            CustomPhrasesBox.Text = string.Join(Environment.NewLine, customPhrases);
            PackLabel.Text = "Voice commands: " + PackNameForPack(commandPack);
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
        await LoadAsync();   // resync from persisted/normalized truth before showing pack/commands
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

    private async void OnSpokenEmojiToggled(object sender, RoutedEventArgs e)
    {
        if (_loading) return;
        await Persist("google.enable_spoken_emoji", SpokenEmojiToggle.IsOn);
    }

    private async void OnCommandPackChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_loading) return;
        string pack = SelectedCommandPack();
        if (!await Persist("languages.command_pack", pack)) return;
        PackLabel.Text = "Voice commands: " + PackNameForPack(pack);
        await LoadCommandsAsync();
    }

    private async void OnPhraseBoostChanged(object sender, Microsoft.UI.Xaml.Controls.Primitives.RangeBaseValueChangedEventArgs e)
    {
        UpdatePhraseBoostLabel(e.NewValue);
        if (_loading) return;
        await Persist("google.phrase_boost", CoercePhraseBoost(e.NewValue));
    }

    private async void OnCustomPhrasesLostFocus(object sender, RoutedEventArgs e)
    {
        if (_loading) return;
        var phrases = ParseCustomPhrases(CustomPhrasesBox.Text);
        if (await Persist("languages.custom_phrases", phrases))
            CustomPhrasesBox.Text = string.Join(Environment.NewLine, phrases);
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

    private void SelectCommandPack(string pack)
    {
        foreach (var obj in CommandPackCombo.Items)
            if (obj is FrameworkElement fe && fe.Tag as string == pack) { CommandPackCombo.SelectedItem = obj; return; }
        CommandPackCombo.SelectedIndex = 0;
    }

    private string SelectedLanguage() => (LanguageCombo.SelectedItem as FrameworkElement)?.Tag as string ?? "iw-IL";

    private static string PackName(string lang) => LangPack.TryGetValue(lang, out var p) ? p.name : "עברית";

    private string SelectedCommandPack() => (CommandPackCombo.SelectedItem as FrameworkElement)?.Tag as string ?? "he";

    private static string PackForLanguage(string lang) => LangPack.TryGetValue(lang, out var p) ? p.pack : "he";

    private static string PackNameForPack(string pack)
        => CommandPacks.FirstOrDefault(p => p.tag == pack).label ?? PackName("iw-IL");

    private void PopulateLanguages()
    {
        if (LanguageCombo.Items.Count > 0) return;
        foreach (var (tag, label) in Languages)
            LanguageCombo.Items.Add(new ComboBoxItem { Content = label, Tag = tag });
    }

    private void PopulateCommandPacks()
    {
        if (CommandPackCombo.Items.Count > 0) return;
        foreach (var (tag, label) in CommandPacks)
            CommandPackCombo.Items.Add(new ComboBoxItem { Content = label, Tag = tag });
    }

    private static double CoercePhraseBoost(double value)
    {
        if (double.IsNaN(value) || double.IsInfinity(value)) return 15.0;
        return Math.Clamp(Math.Round(value), 0.0, 20.0);
    }

    private void UpdatePhraseBoostLabel(double value) => PhraseBoostValue.Text = CoercePhraseBoost(value).ToString("0");

    private static string[] ParseCustomPhrases(string text)
        => (text ?? "")
            .Split(new[] { "\r\n", "\n" }, StringSplitOptions.None)
            .Select(p => p.Trim())
            .Where(p => p.Length > 0)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .Take(100)
            .ToArray();

    internal void RenderLanguageAssistForTest(string pack, bool spokenEmoji, double phraseBoost, string[] phrases)
    {
        _loading = true;
        PopulateCommandPacks();
        SelectCommandPack(pack);
        SpokenEmojiToggle.IsOn = spokenEmoji;
        PhraseBoostSlider.Value = CoercePhraseBoost(phraseBoost);
        UpdatePhraseBoostLabel(PhraseBoostSlider.Value);
        CustomPhrasesBox.Text = string.Join(Environment.NewLine, phrases);
        _loading = false;
    }

    internal string SelectedCommandPackForTest => SelectedCommandPack();
    internal bool SpokenEmojiForTest => SpokenEmojiToggle.IsOn;
    internal string PhraseBoostTextForTest => PhraseBoostValue.Text;
    internal string CustomPhrasesTextForTest => CustomPhrasesBox.Text;

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

    private async Task<double> GetDouble(string key, double fallback)
    {
        if (_host?.Client == null) return fallback;
        try
        {
            var r = await _host.Client.RpcAsync("getConfig", new { key });
            if (r.TryGetProperty("value", out var v))
            {
                if (v.ValueKind == JsonValueKind.Number && v.TryGetDouble(out var d)) return d;
                if (v.ValueKind == JsonValueKind.String && double.TryParse(v.GetString(), out var parsed)) return parsed;
            }
        }
        catch { }
        return fallback;
    }

    private async Task<List<string>> GetStringList(string key)
    {
        var values = new List<string>();
        if (_host?.Client == null) return values;
        try
        {
            var r = await _host.Client.RpcAsync("getConfig", new { key });
            if (!r.TryGetProperty("value", out var v)) return values;
            if (v.ValueKind == JsonValueKind.Array)
            {
                foreach (var item in v.EnumerateArray())
                {
                    string text = item.GetString() ?? "";
                    if (!string.IsNullOrWhiteSpace(text)) values.Add(text.Trim());
                }
            }
            else if (v.ValueKind == JsonValueKind.String)
            {
                values.AddRange(ParseCustomPhrases(v.GetString() ?? ""));
            }
        }
        catch { }
        return values;
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
