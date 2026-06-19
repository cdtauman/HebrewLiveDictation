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

    private void Apply()
    {
        LabelText.Text = Text ?? "";
        bool d = Palette.IsDark(this);
        switch ((State ?? "neutral").ToLowerInvariant())
        {
            case "ready":
                Dot.Fill = Palette.Ready(d);
                Root.Background = Palette.ReadySoft(d);
                break;
            case "attention":
                Dot.Fill = Palette.Attention(d);
                Root.Background = Palette.AttentionSoft(d);
                break;
            case "error":
                Dot.Fill = Palette.Error(d);
                Root.Background = Palette.ErrorSoft(d);
                break;
            default:
                Dot.Fill = Palette.Neutral(d);
                Root.Background = Palette.NeutralSoft(d);
                break;
        }
    }
}
