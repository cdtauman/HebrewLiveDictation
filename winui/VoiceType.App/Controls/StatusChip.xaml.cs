using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Windows.UI;

namespace VoiceType.Shell.Controls;

/// <summary>
/// A calm status pill: a state-colored dot + label. State drives the dot color and
/// a soft background. Reused across Home (health strip), Engine, and Controls.
/// Colors are computed from ActualTheme so they adapt to light/dark without relying
/// on theme-dictionary indexer lookups (which the top-level Resources indexer can't reach).
/// </summary>
public sealed partial class StatusChip : UserControl
{
    public StatusChip()
    {
        this.InitializeComponent();
        this.Loaded += (s, e) => Apply();
        this.ActualThemeChanged += (s, e) => Apply();
    }

    public static readonly DependencyProperty TextProperty =
        DependencyProperty.Register(nameof(Text), typeof(string), typeof(StatusChip),
            new PropertyMetadata("", OnChanged));

    public static readonly DependencyProperty StateProperty =
        DependencyProperty.Register(nameof(State), typeof(string), typeof(StatusChip),
            new PropertyMetadata("neutral", OnChanged));

    /// <summary>"ready" | "attention" | "error" | "neutral".</summary>
    public string State
    {
        get => (string)GetValue(StateProperty);
        set => SetValue(StateProperty, value);
    }

    public string Text
    {
        get => (string)GetValue(TextProperty);
        set => SetValue(TextProperty, value);
    }

    private static void OnChanged(DependencyObject d, DependencyPropertyChangedEventArgs e)
        => ((StatusChip)d).Apply();

    private static SolidColorBrush B(byte r, byte g, byte b) => new(Color.FromArgb(255, r, g, b));

    private void Apply()
    {
        LabelText.Text = Text ?? "";
        bool dark = this.ActualTheme == ElementTheme.Dark;
        switch ((State ?? "neutral").ToLowerInvariant())
        {
            case "ready":
                Dot.Fill = dark ? B(0x51, 0xCF, 0x66) : B(0x2F, 0x9E, 0x44);
                Root.Background = dark ? B(0x1B, 0x2A, 0x1F) : B(0xE7, 0xF5, 0xEA);
                break;
            case "attention":
                Dot.Fill = dark ? B(0xFF, 0xB8, 0x4D) : B(0xE8, 0x92, 0x0C);
                Root.Background = dark ? B(0x2B, 0x24, 0x17) : B(0xFB, 0xF1, 0xE0);
                break;
            case "error":
                Dot.Fill = dark ? B(0xFF, 0x6B, 0x6B) : B(0xE0, 0x31, 0x31);
                Root.Background = dark ? B(0x2C, 0x1C, 0x1C) : B(0xFB, 0xEA, 0xEA);
                break;
            default:
                Dot.Fill = dark ? B(0x7B, 0x7F, 0x88) : B(0x8A, 0x8D, 0x94);
                Root.Background = dark ? B(0x16, 0x18, 0x1D) : B(0xF5, 0xF6, 0xF8);
                break;
        }
    }
}
