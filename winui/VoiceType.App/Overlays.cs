using System;
using Microsoft.UI.Text;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Animation;
using Microsoft.UI.Xaml.Shapes;
using Windows.Graphics;
using Windows.UI;

namespace VoiceType.Shell;

internal enum OverlayAnchor { BottomCenter, BottomRight }

/// <summary>
/// Shared chrome + design language for the two signature surfaces (Voice HUD and
/// Remote). Both float over arbitrary app content, so they carry their own premium
/// dark "glass" surface — but the semantic state colors (the status orb) come from
/// the one <see cref="Palette"/> source the console uses, so all surfaces speak the
/// same visual language. No second set of brand colors lives here.
/// </summary>
internal static class Overlays
{
    private static SolidColorBrush Glass(byte a, byte r, byte g, byte b)
        => new(Color.FromArgb(a, r, g, b));

    // Glass chrome only (alpha surfaces — intentionally overlay-local). All *state*
    // color comes from Palette.*(dark:true), the same values Tokens.xaml uses in dark.
    public static SolidColorBrush Surface => Glass(238, 17, 21, 31);
    public static SolidColorBrush Edge => Glass(110, 140, 156, 200);
    public static SolidColorBrush Light => Glass(255, 0xF1, 0xF5, 0xF9);
    public static SolidColorBrush Muted => Glass(255, 0xAA, 0xB2, 0xC0);

    /// <summary>Map an engine state to its overlay treatment: orb color, label, and
    /// whether the orb should pulse. Kept in one place so HUD and Remote agree.</summary>
    public static (SolidColorBrush dot, string label, bool pulse) Treat(string state)
        => state switch
        {
            "listening" => (Palette.Accent(true), "מקשיב", true),
            "stopping" => (Palette.Attention(true), "כותב…", false),
            "error" => (Palette.Error(true), "שגיאה", false),
            "disconnected" => (Palette.Error(true), "המנוע אינו פעיל", false),
            "connecting" => (Palette.Neutral(true), "מתחבר…", false),
            _ => (Palette.Ready(true), "מוכן", false),
        };

    /// <summary>Configure a frameless, always-on-top, no-activate overlay window. The window
    /// is positioned + styled but left HIDDEN — the owner shows it (no-activate) only once the
    /// configured visibility is known, so a disabled overlay never flashes at startup.
    /// clickThrough adds WS_EX_TRANSPARENT (display-only HUD).</summary>
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
        // Intentionally NOT shown here — the owner shows it (no-activate) after reading config.
    }

    /// <summary>A small status orb that pulses (opacity) while listening — the same
    /// symbol the console and tray use, so users learn one mark.</summary>
    public static Storyboard MakePulse(UIElement target)
    {
        var anim = new DoubleAnimation
        {
            From = 1.0,
            To = 0.3,
            Duration = new Duration(TimeSpan.FromMilliseconds(950)),
            AutoReverse = true,
            RepeatBehavior = RepeatBehavior.Forever,
            EnableDependentAnimation = true,
        };
        Storyboard.SetTarget(anim, target);
        Storyboard.SetTargetProperty(anim, "Opacity");
        var sb = new Storyboard();
        sb.Children.Add(anim);
        return sb;
    }
}

/// <summary>
/// Display-only "Voice HUD" — the brand at the cursor. State-morphing: a semantic
/// status orb + calm Hebrew label, with live RTL words while listening. Problem
/// states get a calm colored treatment, never a raw exception wall. Click-through,
/// no-activate, bottom-center.
/// </summary>
public sealed class HudWindow
{
    public Window Window { get; }
    public IntPtr Hwnd { get; }

    private readonly Ellipse _dot;
    private readonly TextBlock _status;
    private readonly TextBlock _words;
    private readonly TextBlock _target;
    private Storyboard? _pulse;
    private string _state = "idle";

    public HudWindow()
    {
        _dot = new Ellipse
        {
            Width = 11, Height = 11, Fill = Palette.Ready(true),
            VerticalAlignment = VerticalAlignment.Center,
        };
        _status = new TextBlock
        {
            Text = "מוכן", FontSize = 13, FontWeight = FontWeights.SemiBold,
            Foreground = Palette.Ready(true), VerticalAlignment = VerticalAlignment.Center,
        };
        var head = new StackPanel
        {
            Orientation = Orientation.Horizontal, Spacing = 8,
            HorizontalAlignment = HorizontalAlignment.Center,
        };
        head.Children.Add(_dot);
        head.Children.Add(_status);

        _words = new TextBlock
        {
            Text = "לחצו F8 כדי להכתיב", FontSize = 19, TextWrapping = TextWrapping.Wrap,
            Foreground = Overlays.Light, HorizontalAlignment = HorizontalAlignment.Center,
            TextAlignment = TextAlignment.Center,
        };
        // Target reassurance ("→ {app}") — where the text will land. Hidden until listening
        // with a known target, so the user sees we will type into the right window.
        _target = new TextBlock
        {
            Text = "", FontSize = 12, Foreground = Overlays.Muted,
            HorizontalAlignment = HorizontalAlignment.Center, TextAlignment = TextAlignment.Center,
            Visibility = Visibility.Collapsed,
        };

        var panel = new StackPanel { Spacing = 8 };
        panel.Children.Add(head);
        panel.Children.Add(_words);
        panel.Children.Add(_target);

        var border = new Border
        {
            Background = Overlays.Surface, CornerRadius = new CornerRadius(20),
            BorderBrush = Overlays.Edge, BorderThickness = new Thickness(1),
            Padding = new Thickness(24, 15, 24, 16), Child = panel,
        };
        var root = new Grid { FlowDirection = FlowDirection.RightToLeft };
        root.Children.Add(border);

        Window = new Window { Title = "VoiceType HUD" };
        Window.Content = root;
        Hwnd = WinRT.Interop.WindowNative.GetWindowHandle(Window);
        Overlays.Configure(Window, Hwnd, clickThrough: true, 700, 130, OverlayAnchor.BottomCenter);
    }

    /// <summary>Morph to a new engine state. The orb + label always reflect state; the
    /// words area shows the friendly message for problem states and the idle hint at rest.</summary>
    public void SetState(string state, string message = "")
    {
        string prev = _state;
        _state = string.IsNullOrEmpty(state) ? "idle" : state;
        var (dot, label, pulse) = Overlays.Treat(_state);
        _dot.Fill = dot;
        _status.Foreground = dot;
        _status.Text = label;

        // The target reassurance only makes sense while listening; clear it otherwise.
        // While listening it's populated by SetTarget from the status event.
        if (_state != "listening") { _target.Text = ""; _target.Visibility = Visibility.Collapsed; }

        switch (_state)
        {
            case "listening":
                _words.Foreground = Overlays.Light;
                // Only clear on entering listening (fresh session). Repeated "listening"
                // status refreshes must keep the live words — otherwise they flicker to "…".
                if (prev != "listening") _words.Text = "…";
                break;
            case "stopping":
                _words.Foreground = Overlays.Muted;   // keep last words, dimmed while placing
                break;
            case "error":
            case "disconnected":
                _words.Foreground = Overlays.Muted;
                _words.Text = string.IsNullOrEmpty(message) ? "אפשר לנסות שוב." : message;
                break;
            case "connecting":
                _words.Foreground = Overlays.Muted;
                _words.Text = "מתחבר למנוע…";
                break;
            default: // idle / ready
                _words.Foreground = Overlays.Muted;
                _words.Text = "לחצו F8 כדי להכתיב";
                break;
        }

        if (pulse) StartPulse();
        else StopPulse();
    }

    /// <summary>Show where text will land while listening — the focus-safety promise made
    /// visible. The engine sends the app name only when it matches the injector's real,
    /// safe target; when that's unknown/unsafe it sends "", and we show a calm non-naming
    /// state ("יעד: החלון הפעיל") rather than a confident — possibly wrong — claim. Hidden
    /// when not listening.</summary>
    public void SetTarget(string app)
    {
        if (_state != "listening")
        {
            _target.Text = "";
            _target.Visibility = Visibility.Collapsed;
            return;
        }
        _target.Text = string.IsNullOrWhiteSpace(app) ? "יעד: החלון הפעיל" : "יעד: " + app;
        _target.Visibility = Visibility.Visible;
    }

    /// <summary>Current target line — for the runtime self-test.</summary>
    internal string CurrentTargetForTest => _target.Text;

    /// <summary>Live words while listening (ignored in non-speaking states).</summary>
    public void SetWords(string w)
    {
        if (_state is not ("listening" or "stopping")) return;
        _words.Foreground = Overlays.Light;
        _words.Text = string.IsNullOrWhiteSpace(w) ? "…" : w;
    }

    /// <summary>Current displayed words — for the runtime self-test (word preservation).</summary>
    internal string CurrentWordsForTest => _words.Text;

    private void StartPulse()
    {
        if (_pulse != null) return;
        _pulse = Overlays.MakePulse(_dot);
        _pulse.Begin();
    }

    private void StopPulse()
    {
        if (_pulse != null) { _pulse.Stop(); _pulse = null; }
        _dot.Opacity = 1.0;
    }
}

/// <summary>
/// "Remote" — the floating control. A status orb + one state-aware primary action
/// (Start ⇄ Stop), draggable by its handle. Interactive (not click-through),
/// no-activate, bottom-right. Same design tokens as the HUD and console.
/// </summary>
public sealed class RemoteWindow
{
    public Window Window { get; }
    public IntPtr Hwnd { get; }

    private readonly AppHost _host;
    private readonly Ellipse _dot;
    private readonly Button _primary;
    private Storyboard? _pulse;
    private string _state = "idle";

    public RemoteWindow(AppHost host)
    {
        _host = host;

        var handle = new TextBlock
        {
            Text = "⠿", FontSize = 15, FontWeight = FontWeights.SemiBold,
            Foreground = Overlays.Muted, VerticalAlignment = VerticalAlignment.Center,
            Margin = new Thickness(2, 0, 4, 0),
        };
        _dot = new Ellipse
        {
            Width = 10, Height = 10, Fill = Palette.Ready(true),
            VerticalAlignment = VerticalAlignment.Center,
        };
        _primary = new Button { Content = "התחל", MinWidth = 76 };
        _primary.Click += (s, e) => OnPrimary();

        var row = new StackPanel
        {
            Orientation = Orientation.Horizontal, Spacing = 10,
            VerticalAlignment = VerticalAlignment.Center,
        };
        row.Children.Add(handle);
        row.Children.Add(_dot);
        row.Children.Add(_primary);

        var border = new Border
        {
            Background = Overlays.Surface, CornerRadius = new CornerRadius(16),
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

        Overlays.Configure(Window, Hwnd, clickThrough: false, 220, 76, OverlayAnchor.BottomRight);
    }

    private void OnPrimary()
    {
        if (_state is "listening" or "stopping") _host.StopDictation();
        else if (_state is "idle" or "error") _host.StartDictation();
        // connecting/disconnected: button is disabled, nothing to do
    }

    /// <summary>Morph the orb + primary action to the current engine state.</summary>
    public void SetState(string state)
    {
        _state = string.IsNullOrEmpty(state) ? "idle" : state;
        var (dot, _, pulse) = Overlays.Treat(_state);
        _dot.Fill = dot;

        switch (_state)
        {
            case "listening": _primary.Content = "עצור"; _primary.IsEnabled = true; break;
            case "stopping": _primary.Content = "כותב…"; _primary.IsEnabled = false; break;
            case "connecting": _primary.Content = "מתחבר…"; _primary.IsEnabled = false; break;
            case "disconnected": _primary.Content = "אין מנוע"; _primary.IsEnabled = false; break;
            default: _primary.Content = "התחל"; _primary.IsEnabled = true; break;
        }

        if (pulse) StartPulse();
        else StopPulse();
    }

    private void StartPulse()
    {
        if (_pulse != null) return;
        _pulse = Overlays.MakePulse(_dot);
        _pulse.Begin();
    }

    private void StopPulse()
    {
        if (_pulse != null) { _pulse.Stop(); _pulse = null; }
        _dot.Opacity = 1.0;
    }
}
