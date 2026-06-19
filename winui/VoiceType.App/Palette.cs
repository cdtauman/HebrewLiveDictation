using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Media;
using Windows.UI;

namespace VoiceType.Shell;

/// <summary>
/// Theme-aware semantic colors for code that sets brushes dynamically (status dots,
/// chips, overlays) where the ThemeDictionary indexer isn't reachable. Mirrors the
/// values in Theme/Tokens.xaml; centralized so all dynamic surfaces stay consistent.
/// </summary>
public static class Palette
{
    private static SolidColorBrush B(byte r, byte g, byte b) => new(Color.FromArgb(255, r, g, b));

    public static bool IsDark(FrameworkElement el) => el.ActualTheme == ElementTheme.Dark;

    public static SolidColorBrush Ready(bool d) => d ? B(0x51, 0xCF, 0x66) : B(0x2F, 0x9E, 0x44);
    public static SolidColorBrush Attention(bool d) => d ? B(0xFF, 0xB8, 0x4D) : B(0xE8, 0x92, 0x0C);
    public static SolidColorBrush Error(bool d) => d ? B(0xFF, 0x6B, 0x6B) : B(0xE0, 0x31, 0x31);
    public static SolidColorBrush Accent(bool d) => d ? B(0x8C, 0x9C, 0xFF) : B(0x4C, 0x5B, 0xD4);
    public static SolidColorBrush Neutral(bool d) => d ? B(0x7B, 0x7F, 0x88) : B(0x8A, 0x8D, 0x94);

    public static SolidColorBrush ReadySoft(bool d) => d ? B(0x1B, 0x2A, 0x1F) : B(0xE7, 0xF5, 0xEA);
    public static SolidColorBrush AttentionSoft(bool d) => d ? B(0x2B, 0x24, 0x17) : B(0xFB, 0xF1, 0xE0);
    public static SolidColorBrush ErrorSoft(bool d) => d ? B(0x2C, 0x1C, 0x1C) : B(0xFB, 0xEA, 0xEA);
    public static SolidColorBrush NeutralSoft(bool d) => d ? B(0x16, 0x18, 0x1D) : B(0xF5, 0xF6, 0xF8);
}
