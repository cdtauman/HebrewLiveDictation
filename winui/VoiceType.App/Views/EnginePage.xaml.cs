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
        _ = LoadAsync();
    }

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

        switch (tag)
        {
            case "recommended":
                await SetConfig("stt.provider", "google_v2");
                await SetConfig("google.model", "chirp_3");
                await SetConfig("stt.mode", BackupToggle.IsOn ? "auto_fallback" : "api");
                break;
            case "offline":
                await SetConfig("stt.provider", "whisper_local");
                await SetConfig("providers.whisper.enabled", true);
                await SetConfig("stt.mode", "local");
                break;
            default: // choose
                await SetConfig("stt.provider", SelectedProvider());
                await SetConfig("stt.mode", BackupToggle.IsOn ? "auto_fallback" : "api");
                break;
        }
        await RefreshLabelAsync();
    }

    private async void OnBackupToggled(object sender, RoutedEventArgs e)
    {
        if (_loading || OptOffline.IsChecked == true) return;   // offline has no cloud to back up
        await SetConfig("stt.mode", BackupToggle.IsOn ? "auto_fallback" : "api");
        await RefreshLabelAsync();
    }

    private async void OnProviderChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_loading || OptChoose.IsChecked != true) return;
        await SetConfig("stt.provider", SelectedProvider());
        await RefreshLabelAsync();
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

    private async Task SetConfig(string key, object value)
    {
        if (_host?.Client == null) return;
        try { await _host.Client.RpcAsync("setConfig", new { key, value }); } catch { }
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
