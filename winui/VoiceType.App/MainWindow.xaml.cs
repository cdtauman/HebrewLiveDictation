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
    }

    public AppHost Host => _host;

    private void OnClosing(AppWindow sender, AppWindowClosingEventArgs args)
    {
        // Hide-to-tray: cancel the close and hide instead, unless really exiting.
        if (!_host.IsExiting)
        {
            args.Cancel = true;
            this.AppWindow.Hide();
        }
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

    public void SetBridgeStatus(string s) => BridgeStatus.Text = "גשר: " + s;
    public void SetEngineState(string s) => EngineState.Text = "מצב מנוע: " + s;
    public void Log(string line) => AppLog.Add(line);
}
