using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;

namespace VoiceType.Shell.Views;

public sealed partial class HomePage : Page
{
    private AppHost? _host;

    public HomePage() => this.InitializeComponent();

    protected override void OnNavigatedTo(NavigationEventArgs e) => _host = e.Parameter as AppHost;

    private void OnStart(object sender, RoutedEventArgs e) => _host?.StartDictation();
    private void OnStop(object sender, RoutedEventArgs e) => _host?.StopDictation();
}
