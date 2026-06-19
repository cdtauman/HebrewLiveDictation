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

    /// <summary>Build a per-launch unique pipe (short name + full \\.\pipe\ path).</summary>
    public static (string shortName, string fullName) NewPipe(string prefix = "voicetype")
    {
        string shortName = prefix + "-" + Guid.NewGuid().ToString("N");
        return (shortName, @"\\.\pipe\" + shortName);
    }

    /// <summary>python -u -m hebrew_live_dictation.bridge --pipe &lt;full&gt;, with PYTHONPATH=src.</summary>
    public static ProcessStartInfo SidecarStartInfo(string repo, string fullPipeName)
    {
        string py = Path.Combine(repo, ".venv", "Scripts", "python.exe");
        if (!File.Exists(py)) py = "python";
        var psi = new ProcessStartInfo
        {
            FileName = py,
            Arguments = $"-u -m hebrew_live_dictation.bridge --pipe \"{fullPipeName}\"",
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

    /// <summary>
    /// Start the sidecar on the given pipe and ALWAYS drain stdout/stderr async
    /// (otherwise the OS pipe buffers fill and the sidecar deadlocks on a log write).
    /// </summary>
    public static Process? StartSidecar(string repo, string fullPipeName, Action<string>? onLog = null)
    {
        Process? p;
        try { p = Process.Start(SidecarStartInfo(repo, fullPipeName)); }
        catch { return null; }
        if (p == null) return null;
        Action<string> log = onLog ?? (_ => { });
        p.OutputDataReceived += (s, e) => { if (e.Data != null) log(e.Data); };
        p.ErrorDataReceived += (s, e) => { if (e.Data != null) log(e.Data); };
        try { p.BeginOutputReadLine(); p.BeginErrorReadLine(); } catch { }
        return p;
    }
}
