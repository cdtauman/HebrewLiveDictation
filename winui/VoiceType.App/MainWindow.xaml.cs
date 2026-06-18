using System;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;

namespace VoiceType.Shell;

public sealed partial class MainWindow : Window
{
    private readonly AppHost _host;

    public MainWindow(AppHost host)
    {
        this.InitializeComponent();
        _host = host;
        this.Title = "VoiceType";
        // Hide-to-tray: cancel the close and hide instead, unless the app is really exiting.
        this.AppWindow.Closing += OnClosing;
    }

    private void OnClosing(AppWindow sender, AppWindowClosingEventArgs args)
    {
        if (!_host.IsExiting)
        {
            args.Cancel = true;
            this.AppWindow.Hide();
        }
    }

    public void SetBridgeStatus(string s) => BridgeStatus.Text = "גשר: " + s;
    public void SetEngineState(string s) => EngineState.Text = "מצב מנוע: " + s;

    public void Log(string line)
    {
        string entry = DateTime.Now.ToString("HH:mm:ss") + "  " + line;
        EventLog.Text = entry + "\n" + EventLog.Text;
        if (EventLog.Text.Length > 4000)
            EventLog.Text = EventLog.Text.Substring(0, 4000);
    }

    private void OnStartClick(object sender, RoutedEventArgs e) => _host.StartDictation();
    private void OnStopClick(object sender, RoutedEventArgs e) => _host.StopDictation();
    private void OnHideClick(object sender, RoutedEventArgs e) => this.AppWindow.Hide();
    private void OnExitClick(object sender, RoutedEventArgs e) => _host.Exit();
}
