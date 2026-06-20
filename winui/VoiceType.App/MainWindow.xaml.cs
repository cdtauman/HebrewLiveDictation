using System;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using VoiceType.Shell.Views;
using Windows.Graphics;

namespace VoiceType.Shell;

/// <summary>
/// The product shell: an RTL NavigationView over a Mica backdrop, with the six
/// task rooms. Hosts hide-to-tray and forwards engine status into the pane footer.
/// </summary>
public sealed partial class MainWindow : Window
{
    private readonly AppHost _host;

    public MainWindow(AppHost host)
    {
        this.InitializeComponent();
        _host = host;
        this.Title = "VoiceType";
        this.SystemBackdrop = new MicaBackdrop();
        this.AppWindow.Resize(new SizeInt32(1180, 800));
        this.AppWindow.Closing += OnClosing;

        Nav.SelectedItem = Nav.MenuItems[0];   // Home
        Navigate("home");

        // Offline start refused for lack of a model: route the user to the Engine room, where
        // the model card offers the explicit download (Option A: no silent auto-download).
        _host.OfflineModelRequired += NavigateToEngine;
        this.Closed += (_, __) => _host.OfflineModelRequired -= NavigateToEngine;
    }

    public AppHost Host => _host;

    /// <summary>Select the Engine room (its NavigationViewItem, so the pane highlights too),
    /// which surfaces the offline-model download card.</summary>
    public void NavigateToEngine()
    {
        foreach (var mi in Nav.MenuItems)
            if (mi is NavigationViewItem it && (it.Tag as string) == "engine") { Nav.SelectedItem = it; return; }
        Navigate("engine");
    }

    private void OnClosing(AppWindow sender, AppWindowClosingEventArgs args)
    {
        if (_host.IsExiting) return;                  // a real teardown is in progress
        args.Cancel = true;
        // Honor the user's choice (Settings room): hide to tray, or fully exit on close.
        if (_host.MinimizeOnClose) this.AppWindow.Hide();
        else _host.Exit();
    }

    /// <summary>Apply the chosen color theme to the whole shell live (Settings room).
    /// "default" follows the system theme.</summary>
    public void ApplyTheme(string theme)
    {
        if (Content is FrameworkElement fe)
            fe.RequestedTheme = theme switch
            {
                "dark" => ElementTheme.Dark,
                "light" => ElementTheme.Light,
                _ => ElementTheme.Default,
            };
    }

    private void OnNavSelectionChanged(NavigationView sender, NavigationViewSelectionChangedEventArgs args)
    {
        if (args.SelectedItem is NavigationViewItem item && item.Tag is string tag)
            Navigate(tag);
    }

    private void Navigate(string tag)
    {
        Type page = tag switch
        {
            "home" => typeof(HomePage),
            "dictation" => typeof(DictationPage),
            "engine" => typeof(EnginePage),
            "controls" => typeof(ControlsPage),
            "history" => typeof(HistoryPage),
            "settings" => typeof(SettingsPage),
            _ => typeof(HomePage),
        };
        ContentFrame.Navigate(page, _host);
    }

    /// <summary>Calm engine indicator in the pane footer — friendly Hebrew state + a
    /// semantic dot. No technical "bridge"/raw-state language.</summary>
    public void SetEngineStatus(string state, string message)
    {
        bool d = Palette.IsDark(Nav);
        string text;
        SolidColorBrush dot;
        switch (state)
        {
            case "listening": text = "מקשיב"; dot = Palette.Accent(d); break;
            case "stopping": text = "כותב…"; dot = Palette.Attention(d); break;
            case "error": text = "שגיאה"; dot = Palette.Error(d); break;
            case "disconnected": text = "המנוע אינו פעיל"; dot = Palette.Error(d); break;
            case "connecting": text = "מתחבר…"; dot = Palette.Neutral(d); break;
            default: text = "מוכן"; dot = Palette.Ready(d); break;
        }
        FooterText.Text = text;
        FooterDot.Fill = dot;
    }

    public void Log(string line) => AppLog.Add(line);
}
