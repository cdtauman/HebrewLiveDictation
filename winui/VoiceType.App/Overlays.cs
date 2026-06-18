using System;
using Microsoft.UI.Text;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;
using Windows.Graphics;
using Windows.UI;

namespace VoiceType.Shell;

internal enum OverlayAnchor { BottomCenter, BottomRight }

internal static class Overlays
{
    private static SolidColorBrush Brush(byte a, byte r, byte g, byte b)
        => new(Color.FromArgb(a, r, g, b));

    /// <summary>Configure a frameless, always-on-top, no-activate overlay window and show it
    /// without stealing focus. clickThrough adds WS_EX_TRANSPARENT (display-only HUD).</summary>
    public static void Configure(Window window, IntPtr hwnd, bool clickThrough, int dipW, int dipH, OverlayAnchor anchor)
    {
        var presenter = OverlappedPresenter.CreateForToolWindow();
        presenter.IsAlwaysOnTop = true;
        presenter.IsResizable = false;
        presenter.SetBorderAndTitleBar(false, false);
        window.AppWindow.SetPresenter(presenter);

        double scale = Native.GetDpiForWindow(hwnd);
        scale = scale > 0 ? scale / 96.0 : 1.0;
        int w = (int)(dipW * scale), h = (int)(dipH * scale);
        var wa = DisplayArea.Primary.WorkArea;
        int x, y;
        if (anchor == OverlayAnchor.BottomCenter)
        {
            x = wa.X + (wa.Width - w) / 2;
            y = wa.Y + wa.Height - h - (int)(48 * scale);
        }
        else
        {
            x = wa.X + wa.Width - w - (int)(28 * scale);
            y = wa.Y + wa.Height - h - (int)(150 * scale);
        }
        window.AppWindow.MoveAndResize(new RectInt32(x, y, w, h));

        Native.MakeOverlay(hwnd, clickThrough);          // WS_EX_NOACTIVATE | TOPMOST | (TRANSPARENT)
        window.AppWindow.Show(activateWindow: false);     // show WITHOUT stealing focus
    }

    public static SolidColorBrush HudBg => Brush(235, 20, 25, 36);
    public static SolidColorBrush RemoteBg => Brush(238, 15, 23, 42);
    public static SolidColorBrush Edge => Brush(120, 148, 163, 184);
    public static SolidColorBrush Accent => Brush(255, 0xFD, 0xA4, 0xAF);
    public static SolidColorBrush Light => Brush(255, 0xF1, 0xF5, 0xF9);
}

/// <summary>Display-only "Voice HUD": status + live words, RTL, click-through, bottom-center.</summary>
public sealed class HudWindow
{
    public Window Window { get; }
    public IntPtr Hwnd { get; }
    private readonly TextBlock _status;
    private readonly TextBlock _words;

    public HudWindow()
    {
        _status = new TextBlock
        {
            Text = "מוכן", FontSize = 13, FontWeight = FontWeights.SemiBold,
            Foreground = Overlays.Accent, HorizontalAlignment = HorizontalAlignment.Center,
        };
        _words = new TextBlock
        {
            Text = "לחצו F8 כדי להכתיב", FontSize = 18, TextWrapping = TextWrapping.Wrap,
            Foreground = Overlays.Light, HorizontalAlignment = HorizontalAlignment.Center,
            TextAlignment = TextAlignment.Center,
        };
        var panel = new StackPanel { Spacing = 6 };
        panel.Children.Add(_status);
        panel.Children.Add(_words);
        var border = new Border
        {
            Background = Overlays.HudBg, CornerRadius = new CornerRadius(18),
            BorderBrush = Overlays.Edge, BorderThickness = new Thickness(1),
            Padding = new Thickness(22, 14, 22, 14), Child = panel,
        };
        var root = new Grid { FlowDirection = FlowDirection.RightToLeft };
        root.Children.Add(border);

        Window = new Window { Title = "VoiceType HUD" };
        Window.Content = root;
        Hwnd = WinRT.Interop.WindowNative.GetWindowHandle(Window);
        Overlays.Configure(Window, Hwnd, clickThrough: true, 700, 120, OverlayAnchor.BottomCenter);
    }

    public void SetStatus(string s) => _status.Text = string.IsNullOrEmpty(s) ? "מוכן" : s;
    public void SetWords(string w) => _words.Text = string.IsNullOrEmpty(w) ? "…" : w;
}

/// <summary>"Remote": draggable (by the handle), interactive Start/Stop, RTL, bottom-right.</summary>
public sealed class RemoteWindow
{
    public Window Window { get; }
    public IntPtr Hwnd { get; }

    public RemoteWindow(AppHost host)
    {
        var handle = new TextBlock
        {
            Text = "⠿  שלט", FontSize = 13, FontWeight = FontWeights.SemiBold,
            Foreground = Overlays.Light, VerticalAlignment = VerticalAlignment.Center,
            Margin = new Thickness(2, 0, 8, 0),
        };
        var start = new Button { Content = "התחל" };
        var stop = new Button { Content = "עצור" };
        start.Click += (s, e) => host.StartDictation();
        stop.Click += (s, e) => host.StopDictation();

        var row = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8, VerticalAlignment = VerticalAlignment.Center };
        row.Children.Add(handle);
        row.Children.Add(start);
        row.Children.Add(stop);
        var border = new Border
        {
            Background = Overlays.RemoteBg, CornerRadius = new CornerRadius(14),
            BorderBrush = Overlays.Edge, BorderThickness = new Thickness(1),
            Padding = new Thickness(14, 10, 14, 10), Child = row,
        };
        var root = new Grid { FlowDirection = FlowDirection.RightToLeft };
        root.Children.Add(border);

        Window = new Window { Title = "שלט" };
        Window.Content = root;
        Hwnd = WinRT.Interop.WindowNative.GetWindowHandle(Window);

        // Drag the whole window by the handle (classic WM_NCLBUTTONDOWN trick; works on no-activate windows).
        handle.PointerPressed += (s, e) =>
        {
            Native.ReleaseCapture();
            Native.SendMessageW(Hwnd, Native.WM_NCLBUTTONDOWN, new IntPtr(Native.HTCAPTION), IntPtr.Zero);
        };

        Overlays.Configure(Window, Hwnd, clickThrough: false, 260, 84, OverlayAnchor.BottomRight);
    }
}
