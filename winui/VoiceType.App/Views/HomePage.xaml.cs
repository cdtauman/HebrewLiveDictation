using System;
using System.Collections.Generic;
using System.Text.Json;
using System.Threading.Tasks;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media.Animation;
using Microsoft.UI.Xaml.Navigation;

namespace VoiceType.Shell.Views;

public sealed class RecentItem
{
    public string Text { get; set; } = "";
    public string When { get; set; } = "";
}

public sealed partial class HomePage : Page
{
    private AppHost? _host;
    private Storyboard? _pulse;
    private bool _healthLoaded;
    private string _prevState = "idle";

    public HomePage() => this.InitializeComponent();

    protected override void OnNavigatedTo(NavigationEventArgs e)
    {
        _host = e.Parameter as AppHost;
        if (_host == null) return;
        _host.StatusChanged += OnStatus;
        _prevState = _host.CurrentState;
        ApplyState(_host.CurrentState, _host.CurrentMessage);
        _ = LoadHealthAsync();
        _ = LoadRecentAsync();
    }

    protected override void OnNavigatedFrom(NavigationEventArgs e)
    {
        if (_host != null) _host.StatusChanged -= OnStatus;
        StopPulse();
    }

    private void OnStatus(string state, string message)
    {
        ApplyState(state, message);
        if (!_healthLoaded) _ = LoadHealthAsync();
        if (_prevState != "idle" && state == "idle") _ = LoadRecentAsync();  // session just ended
        _prevState = state;
    }

    private void OnPrimary(object sender, RoutedEventArgs e)
    {
        var s = _host?.CurrentState ?? "idle";
        if (s == "disconnected") { _host?.RestartEngine(); return; }
        if (s is "listening" or "stopping") _host?.StopDictation();
        else _host?.StartDictation();
    }

    private void ApplyState(string state, string message)
    {
        bool d = Palette.IsDark(this);
        bool listening = false;
        switch (state)
        {
            case "listening":
                StatusDot.Fill = Palette.Accent(d);
                StatusText.Text = "מקשיב";
                StatusHint.Text = "מדברים… הטקסט ייכתב לחלון היעד כשעוצרים.";
                PrimaryButton.Content = "עצור";
                listening = true;
                break;
            case "stopping":
                StatusDot.Fill = Palette.Attention(d);
                StatusText.Text = "כותב…";
                StatusHint.Text = "מסיים וכותב את הטקסט.";
                PrimaryButton.Content = "עצור";
                break;
            case "error":
                StatusDot.Fill = Palette.Error(d);
                StatusText.Text = "שגיאה";
                StatusHint.Text = string.IsNullOrEmpty(message) ? "משהו דורש תשומת לב." : message;
                PrimaryButton.Content = "התחל הכתבה";
                break;
            case "disconnected":
                StatusDot.Fill = Palette.Error(d);
                StatusText.Text = "המנוע אינו פעיל";
                StatusHint.Text = "המנוע נעצר. לחצו כדי להפעיל אותו מחדש.";
                PrimaryButton.Content = "הפעלה מחדש";
                break;
            case "connecting":
                StatusDot.Fill = Palette.Neutral(d);
                StatusText.Text = "מתחבר…";
                StatusHint.Text = "מתחבר למנוע…";
                PrimaryButton.Content = "מתחבר…";
                break;
            default:
                StatusDot.Fill = Palette.Ready(d);
                StatusText.Text = "מוכן";
                StatusHint.Text = "לחצו F8 בכל מקום, דברו, ועצרו — הטקסט הסופי ייכתב בחלון היעד.";
                PrimaryButton.Content = "התחל הכתבה";
                break;
        }
        PrimaryButton.IsEnabled = state != "connecting";
        if (listening) StartPulse();
        else StopPulse();
    }

    private async Task LoadHealthAsync()
    {
        if (_host?.Client == null) return;
        try
        {
            var h = await _host.Client.RpcAsync("getHealth");
            string engineLabel = h.TryGetProperty("engine", out var eng) && eng.TryGetProperty("label", out var lbl)
                ? lbl.GetString() ?? "" : "";
            bool micOk = h.TryGetProperty("microphone", out var mic) && mic.TryGetProperty("ok", out var mo) && mo.GetBoolean();
            bool offline = h.TryGetProperty("offline", out var off) && off.TryGetProperty("ready", out var orr) && orr.GetBoolean();

            DispatcherQueue.TryEnqueue(() =>
            {
                EngineChip.Text = string.IsNullOrEmpty(engineLabel) ? "מנוע" : "מנוע · " + engineLabel;
                EngineChip.State = "ready";
                MicChip.Text = micOk ? "מיקרופון" : "אין מיקרופון";
                MicChip.State = micOk ? "ready" : "error";
                OfflineChip.Text = offline ? "גיבוי לא־מקוון מוכן" : "גיבוי לא־מקוון";
                OfflineChip.State = offline ? "ready" : "neutral";
            });
            _healthLoaded = true;
        }
        catch { /* not connected yet — chips stay neutral, retried on first status */ }
    }

    private async Task LoadRecentAsync()
    {
        if (_host?.Client == null) return;
        try
        {
            var res = await _host.Client.RpcAsync("getHistory", new { count = 4 });
            var items = new List<RecentItem>();
            if (res.TryGetProperty("items", out var arr) && arr.ValueKind == JsonValueKind.Array)
            {
                foreach (var it in arr.EnumerateArray())
                {
                    string text = it.TryGetProperty("text", out var t) ? t.GetString() ?? "" : "";
                    double ts = it.TryGetProperty("ts", out var tsEl) && tsEl.TryGetDouble(out var dv) ? dv : 0;
                    if (!string.IsNullOrWhiteSpace(text))
                        items.Add(new RecentItem { Text = text, When = RelativeTime(ts) });
                }
            }
            DispatcherQueue.TryEnqueue(() =>
            {
                RecentList.ItemsSource = items;
                bool any = items.Count > 0;
                RecentList.Visibility = any ? Visibility.Visible : Visibility.Collapsed;
                RecentEmpty.Visibility = any ? Visibility.Collapsed : Visibility.Visible;
            });
        }
        catch { }
    }

    private static string RelativeTime(double unixSeconds)
    {
        if (unixSeconds <= 0) return "";
        var dt = DateTimeOffset.FromUnixTimeSeconds((long)unixSeconds).LocalDateTime;
        var span = DateTime.Now - dt;
        if (span.TotalMinutes < 1) return "הרגע";
        if (span.TotalMinutes < 60) return $"לפני {(int)span.TotalMinutes} דק׳";
        if (span.TotalHours < 24) return $"לפני {(int)span.TotalHours} שע׳";
        return dt.ToString("dd/MM");
    }

    private void StartPulse()
    {
        if (_pulse != null) return;
        var anim = new DoubleAnimation
        {
            From = 1.0,
            To = 0.35,
            Duration = new Duration(TimeSpan.FromMilliseconds(950)),
            AutoReverse = true,
            RepeatBehavior = RepeatBehavior.Forever,
        };
        Storyboard.SetTarget(anim, StatusDot);
        Storyboard.SetTargetProperty(anim, "Opacity");
        _pulse = new Storyboard();
        _pulse.Children.Add(anim);
        _pulse.Begin();
    }

    private void StopPulse()
    {
        if (_pulse != null) { _pulse.Stop(); _pulse = null; }
        StatusDot.Opacity = 1.0;
    }
}
