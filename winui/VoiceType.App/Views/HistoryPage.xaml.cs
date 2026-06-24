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
    public string Id { get; set; } = "";
    public string Text { get; set; } = "";
    public string When { get; set; } = "";
    public string Target { get; set; } = "";
    public string Meta { get; set; } = "";
}

/// <summary>
/// History room: the user's complete transcript record, live from the engine. Full
/// (untruncated) text, copy per item, export to TXT, and a confirmed clear-all.
/// First of the live task rooms — establishes the IPC-driven page pattern.
/// </summary>
public sealed partial class HistoryPage : Page
{
    private AppHost? _host;
    private int _loadSerial;

    public HistoryPage() => this.InitializeComponent();

    protected override void OnNavigatedTo(NavigationEventArgs e)
    {
        _host = e.Parameter as AppHost;
        _ = LoadAsync();
    }

    private const int DisplayCount = 200;
    private const int ExportAllCount = 100000;   // engine clamps to the store cap = "all"

    /// <summary>Fetch transcripts fresh from the engine. The list is the source of truth;
    /// export re-fetches the full set rather than reusing the display page.</summary>
    private async Task<List<TranscriptItem>> FetchAsync(int count, string query = "")
    {
        var items = new List<TranscriptItem>();
        if (_host?.Client == null) return items;
        try
        {
            var res = await _host.Client.RpcAsync("getTranscripts", new { count, query });
            if (res.TryGetProperty("items", out var arr) && arr.ValueKind == JsonValueKind.Array)
            {
                foreach (var it in arr.EnumerateArray())
                {
                    string id = it.TryGetProperty("id", out var idEl) ? idEl.GetString() ?? "" : "";
                    string text = it.TryGetProperty("text", out var t) ? t.GetString() ?? "" : "";
                    if (string.IsNullOrWhiteSpace(text)) continue;
                    double ts = it.TryGetProperty("ts", out var tsEl) && tsEl.TryGetDouble(out var dv) ? dv : 0;
                    string target = it.TryGetProperty("target", out var tg) ? tg.GetString() ?? "" : "";
                    int chars = it.TryGetProperty("chars", out var ch) && ch.TryGetInt32(out var cv) ? cv : text.Length;
                    items.Add(new TranscriptItem
                    {
                        Id = id,
                        Text = text,
                        When = FormatWhen(ts),
                        Target = FriendlyTarget(target),
                        Meta = chars > 0 ? $"{chars} תווים" : "",
                    });
                }
            }
        }
        catch { /* not connected — caller shows empty state */ }
        return items;
    }

    private async Task<(bool enabled, int maxEntries, int count)> FetchStatusAsync()
    {
        if (_host?.Client == null) return (true, 500, 0);
        try
        {
            var res = await _host.Client.RpcAsync("getHistoryStatus");
            bool enabled = !res.TryGetProperty("enabled", out var en) || en.ValueKind == JsonValueKind.True;
            int maxEntries = res.TryGetProperty("maxEntries", out var mx) && mx.TryGetInt32(out var mv) ? mv : 500;
            int count = res.TryGetProperty("count", out var ct) && ct.TryGetInt32(out var cv) ? cv : 0;
            return (enabled, maxEntries, count);
        }
        catch { return (true, 500, 0); }
    }

    private async Task LoadAsync()
    {
        int serial = ++_loadSerial;
        string query = SearchBox.Text?.Trim() ?? "";
        var status = await FetchStatusAsync();
        var items = await FetchAsync(DisplayCount, query);
        DispatcherQueue.TryEnqueue(() =>
        {
            if (serial != _loadSerial) return;
            List.ItemsSource = items;
            bool any = items.Count > 0;
            List.Visibility = any ? Visibility.Visible : Visibility.Collapsed;
            EmptyCard.Visibility = any ? Visibility.Collapsed : Visibility.Visible;
            Actions.Visibility = status.count > 0 ? Visibility.Visible : Visibility.Collapsed;
            PrivacyStatusText.Text = HistoryStatusText(status.enabled, status.maxEntries, status.count);
            if (!any && !string.IsNullOrWhiteSpace(query))
            {
                EmptyTitle.Text = "לא נמצאו תמלולים";
                EmptyBody.Text = "נסו חיפוש אחר או נקו את שורת החיפוש.";
            }
            else
            {
                EmptyTitle.Text = "אין עדיין תמלולים";
                EmptyBody.Text = "כשתתחילו להכתיב, מה שתאמרו יישמר כאן — וניתן יהיה לייצא ל־TXT.";
            }
        });
    }

    private void OnSearchChanged(object sender, TextChangedEventArgs e) => _ = LoadAsync();

    private void OnRefresh(object sender, RoutedEventArgs e) => _ = LoadAsync();

    private void OnCopyItem(object sender, RoutedEventArgs e)
    {
        if (sender is FrameworkElement fe && fe.Tag is string text && !string.IsNullOrEmpty(text))
        {
            var dp = new DataPackage();
            dp.SetText(text);
            Clipboard.SetContent(dp);
        }
    }

    private async void OnDeleteItem(object sender, RoutedEventArgs e)
    {
        if (_host?.Client == null) return;
        if (sender is not FrameworkElement fe || fe.Tag is not string id || string.IsNullOrWhiteSpace(id)) return;
        var dialog = new ContentDialog
        {
            Title = "למחוק את התמלול?",
            Content = "התמלול יימחק מהיסטוריית המכשיר. אי אפשר לבטל פעולה זו.",
            PrimaryButtonText = "מחק",
            CloseButtonText = "ביטול",
            DefaultButton = ContentDialogButton.Close,
            XamlRoot = this.XamlRoot,
            FlowDirection = FlowDirection.RightToLeft,
        };
        if (await dialog.ShowAsync() != ContentDialogResult.Primary) return;

        bool deleted = false;
        try
        {
            var res = await _host.Client.RpcAsync("deleteTranscript", new { id, confirm = true });
            deleted = res.TryGetProperty("deleted", out var d) && d.ValueKind == JsonValueKind.True;
        }
        catch { }
        if (!deleted)
        {
            await ShowMessageAsync("לא ניתן למחוק את התמלול כרגע.", "נסו שוב בעוד רגע.");
            return;
        }
        await LoadAsync();
    }

    private async void OnExport(object sender, RoutedEventArgs e)
    {
        if (_host?.Console == null || _host.Client == null) return;

        var picker = new FileSavePicker
        {
            SuggestedFileName = "VoiceType-history",
            SuggestedStartLocation = PickerLocationId.DocumentsLibrary,
        };
        picker.FileTypeChoices.Add("מסמך Word", new List<string> { ".docx" });
        picker.FileTypeChoices.Add("טקסט", new List<string> { ".txt" });
        // Unpackaged WinUI: a picker must be associated with the owning window's HWND.
        WinRT.Interop.InitializeWithWindow.Initialize(picker, WinRT.Interop.WindowNative.GetWindowHandle(_host.Console));

        StorageFile? file = await picker.PickSaveFileAsync();
        if (file == null) return;

        // The engine writes the file — one source of truth, and it produces RTL-correct DOCX (python-docx,
        // w:bidi/w:rtl) or plain UTF-8 TXT, exporting ALL stored transcripts.
        string fmt = string.Equals(file.FileType, ".docx", StringComparison.OrdinalIgnoreCase) ? "docx" : "txt";
        bool ok = false; string err = "";
        try
        {
            var r = await _host.Client.RpcAsync("exportHistory", new { format = fmt, path = file.Path });
            ok = r.TryGetProperty("ok", out var o) && o.ValueKind == JsonValueKind.True;
            if (!ok) err = r.TryGetProperty("error", out var er) ? er.GetString() ?? "" : "";
        }
        catch (Exception ex) { err = ex.Message; }
        if (!ok)
            await ShowMessageAsync("הייצוא נכשל", string.IsNullOrEmpty(err) ? "נסו שוב מאוחר יותר." : err);
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

        bool cleared = false;
        try
        {
            var res = await _host.Client.RpcAsync("clearHistory", new { confirm = true });
            cleared = res.TryGetProperty("cleared", out var c) && c.GetBoolean();
        }
        catch { /* cleared stays false -> show failure */ }

        if (!cleared) { await ShowMessageAsync("לא ניתן לנקות את ההיסטוריה כעת.", "נסו שוב בעוד רגע."); return; }
        await LoadAsync();
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

    private static string HistoryStatusText(bool enabled, int maxEntries, int count)
        => enabled
            ? $"שמירת היסטוריה פעילה. נשמרו {count} מתוך {maxEntries} תמלולים אחרונים."
            : $"שמירת היסטוריה כבויה. {count} תמלולים קיימים נשארים במכשיר עד מחיקה.";

    internal void RenderHistoryForTest(bool enabled, int maxEntries, int count, int visibleItems, string query = "")
    {
        PrivacyStatusText.Text = HistoryStatusText(enabled, maxEntries, count);
        Actions.Visibility = count > 0 ? Visibility.Visible : Visibility.Collapsed;
        List.Visibility = visibleItems > 0 ? Visibility.Visible : Visibility.Collapsed;
        EmptyCard.Visibility = visibleItems > 0 ? Visibility.Collapsed : Visibility.Visible;
        if (visibleItems == 0 && !string.IsNullOrWhiteSpace(query))
        {
            EmptyTitle.Text = "לא נמצאו תמלולים";
            EmptyBody.Text = "נסו חיפוש אחר או נקו את שורת החיפוש.";
        }
        else
        {
            EmptyTitle.Text = "אין עדיין תמלולים";
            EmptyBody.Text = "כשתתחילו להכתיב, מה שתאמרו יישמר כאן — וניתן יהיה לייצא ל־TXT.";
        }
    }

    internal string PrivacyStatusForTest => PrivacyStatusText.Text;
    internal bool HistoryActionsVisibleForTest => Actions.Visibility == Visibility.Visible;
    internal bool HistoryEmptyVisibleForTest => EmptyCard.Visibility == Visibility.Visible;
    internal string EmptyTitleForTest => EmptyTitle.Text;

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
