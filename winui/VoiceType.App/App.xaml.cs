using System;
using System.Linq;
using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml;

namespace VoiceType.Shell;

public partial class App : Application
{
    // Kept alive for the lifetime of the app (owns bridge, tray, windows).
    public static AppHost? Host { get; private set; }

    public App()
    {
        this.InitializeComponent();
    }

    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        var argv = Environment.GetCommandLineArgs();
        bool Has(string flag) => argv.Any(a => string.Equals(a, flag, StringComparison.OrdinalIgnoreCase));

        if (Has("--selftest"))
        {
            // Automated runtime verification, then exit. --expect-packaged-engine asserts the
            // packaged launch HARD: the bundled engine.exe must be present and actually spawned;
            // a missing/broken engine.exe (or a python fallback) fails the run.
            bool expectPackaged = Has("--expect-packaged-engine");
            DispatcherQueue.GetForCurrentThread().TryEnqueue(async () => await RuntimeSelfTest.RunAsync(expectPackaged));
            return;
        }

        // Interactive shell. The HUD + Remote show per config (Controls room); --show
        // forces both on regardless, for manual testing.
        bool showOverlays = Has("--show");
        Host = new AppHost();
        _ = Host.RunAsync(showOverlays);
    }
}
