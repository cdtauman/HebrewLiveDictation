using System;
using System.Diagnostics;
using System.IO;

namespace VoiceType.Shell;

/// <summary>
/// Locates the repository and launches the engine sidecar. The Python package is not
/// pip-installed, so we run it as a module with PYTHONPATH pointing at src/.
/// </summary>
internal static class RepoPaths
{
    public static string FindRoot()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir != null)
        {
            if (Directory.Exists(Path.Combine(dir.FullName, "src")) &&
                Directory.Exists(Path.Combine(dir.FullName, "winui")))
                return dir.FullName;
            dir = dir.Parent;
        }
        return AppContext.BaseDirectory;
    }

    /// <summary>python -u -m hebrew_live_dictation.bridge, with PYTHONPATH=src.</summary>
    public static ProcessStartInfo SidecarStartInfo(string repo)
    {
        string py = Path.Combine(repo, ".venv", "Scripts", "python.exe");
        if (!File.Exists(py)) py = "python";
        var psi = new ProcessStartInfo
        {
            FileName = py,
            Arguments = "-u -m hebrew_live_dictation.bridge",
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            WorkingDirectory = repo,
        };
        string src = Path.Combine(repo, "src");
        string existing = Environment.GetEnvironmentVariable("PYTHONPATH") ?? "";
        psi.Environment["PYTHONPATH"] = existing.Length == 0 ? src : src + Path.PathSeparator + existing;
        return psi;
    }
}
