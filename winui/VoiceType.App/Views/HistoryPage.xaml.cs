using System;
using System.Collections.Generic;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;
using Windows.ApplicationModel.DataTransfer;
using Windows.Storage;
using Windows.Storage.Pickers;

namespace VoiceType.Shell.Views;

public sealed class TranscriptItem
{
    public string Text { get; set; } = "";
    public string When { get; set; } = "";
    public string Target { get; set; } = "";
}

/// <summary>
/// History room: the user's complete transcript record, live from the engine. Full
/// (untruncated) text, copy per item, export to TXT, and a confirmed clear-all.
/// First of the live task rooms — establishes the IPC-driven page pattern.
/// </summary>
public sealed partial class HistoryPage : Page
{
    private AppHost? _host;

    public HistoryPage() => this.InitializeComponent();

    protected override void OnNavigatedTo(NavigationEventArgs e)
    {
        _host = e.Parameter as AppHost;
        _ = LoadAsync();
    }

    private async Task LoadAsync()
    {
        var items = new List<TranscriptItem>();
        if (_host?.Client != null)
        {
            try
            {
                var res = await _host.Client.RpcAsync("getTranscripts", new { count = 200 });
                if (res.TryGetProperty("items", out var arr) && arr.ValueKind == JsonValueKind.Array)
                {
                    foreach (var it in arr.EnumerateArray())
                    {
                        string text = it.TryGetProperty("text", out var t) ? t.GetString() ?? "" : "";
                        if (string.IsNullOrWhiteSpace(text)) continue;
                        double ts = it.TryGetProperty("ts", out var tsEl) && tsEl.TryGetDouble(out var dv) ? dv : 0;
                        string target = it.TryGetProperty("target", out var tg) ? tg.GetString() ?? "" : "";
                        items.Add(new TranscriptItem { Text = text, When = FormatWhen(ts), Target = FriendlyTarget(target) });
                    }
                }
            }
            catch { /* not connected — show empty state */ }
        }

        DispatcherQueue.TryEnqueue(() =>
        {
            List.ItemsSource = items;
            bool any = items.Count > 0;
            List.Visibility = any ? Visibility.Visible : Visibility.Collapsed;
            EmptyCard.Visibility = any ? Visibility.Collapsed : Visibility.Visible;
            Actions.Visibility = any ? Visibility.Visible : Visibility.Collapsed;
        });
    }

    private void OnCopyItem(object sender, RoutedEventArgs e)
    {
        if (sender is FrameworkElement fe && fe.Tag is string text && !string.IsNullOrEmpty(text))
        {
            var dp = new DataPackage();
            dp.SetText(text);
            Clipboard.SetContent(dp);
        }
    }

    private async void OnExport(object sender, RoutedEventArgs e)
    {
        if (_host?.Console == null || List.ItemsSource is not List<TranscriptItem> items || items.Count == 0) return;

        var picker = new FileSavePicker
        {
            SuggestedFileName = "VoiceType-history",
            SuggestedStartLocation = PickerLocationId.DocumentsLibrary,
        };
        picker.FileTypeChoices.Add("טקסט", new List<string> { ".txt" });
        // Unpackaged WinUI: a picker must be associated with the owning window's HWND.
        WinRT.Interop.InitializeWithWindow.Initialize(picker, WinRT.Interop.WindowNative.GetWindowHandle(_host.Console));

        StorageFile? file = await picker.PickSaveFileAsync();
        if (file == null) return;

        var sb = new StringBuilder();
        foreach (var it in items)
        {
            if (!string.IsNullOrEmpty(it.When)) sb.Append('[').Append(it.When).Append("]  ");
            sb.AppendLine(it.Text);
            sb.AppendLine();
        }
        await FileIO.WriteTextAsync(file, sb.ToString());
    }

    private async void OnClear(object sender, RoutedEventArgs e)
    {
        if (_host?.Client == null) return;
        var dialog = new ContentDialog
        {
            Title = "לנקות את ההיסטוריה?",
            Content = "כל התמלולים יימחקו מהמכשיר. אי אפשר לבטל פעולה זו.",
            PrimaryButtonText = "נקה הכל",
            CloseButtonText = "ביטול",
            DefaultButton = ContentDialogButton.Close,
            XamlRoot = this.XamlRoot,
            FlowDirection = FlowDirection.RightToLeft,
        };
        if (await dialog.ShowAsync() != ContentDialogResult.Primary) return;
        try { await _host.Client.RpcAsync("clearHistory"); } catch { }
        await LoadAsync();
    }

    private static string FormatWhen(double unixSeconds)
    {
        if (unixSeconds <= 0) return "";
        return DateTimeOffset.FromUnixTimeSeconds((long)unixSeconds).LocalDateTime.ToString("dd/MM/yyyy HH:mm");
    }

    /// <summary>Turn "C:\\...\\winword.exe" into a calm "· Word"-style label (empty if none).</summary>
    private static string FriendlyTarget(string raw)
    {
        if (string.IsNullOrWhiteSpace(raw)) return "";
        string name = raw;
        int slash = name.LastIndexOfAny(new[] { '\\', '/' });
        if (slash >= 0) name = name[(slash + 1)..];
        if (name.EndsWith(".exe", StringComparison.OrdinalIgnoreCase)) name = name[..^4];
        return name.Length == 0 ? "" : "· " + name;
    }
}
