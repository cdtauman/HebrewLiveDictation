using System;
using System.Diagnostics;
using System.IO;

namespace VoiceType.Shell;

/// <summary>
/// Locates and launches the engine sidecar. Two modes:
///  * Packaged: a frozen <c>engine\engine.exe</c> sits next to <c>VoiceType.exe</c> — spawn it
///    directly (no Python, no repo tree). This is the shipped path.
///  * Dev fallback: no packaged engine present — run the package as a module from the repo
///    (<c>.venv</c> or system <c>python -m hebrew_live_dictation.bridge</c>, PYTHONPATH=src).
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

    /// <summary>Full path to the bundled, frozen engine (<c>engine\engine.exe</c> next to the
    /// shell), or null when running from the dev tree. Single source of truth for "are we
    /// packaged?" — used by the launcher and the packaged-layout self-test.</summary>
    public static string? PackagedEnginePath()
    {
        string exe = Path.Combine(AppContext.BaseDirectory, "engine", "engine.exe");
        return File.Exists(exe) ? exe : null;
    }

    /// <summary>"packaged" when a frozen engine.exe is present, else "dev" (python -m).</summary>
    public static string EngineLaunchMode() => PackagedEnginePath() != null ? "packaged" : "dev";

    /// <summary>Build a per-launch unique pipe (short name + full \\.\pipe\ path).</summary>
    public static (string shortName, string fullName) NewPipe(string prefix = "voicetype")
    {
        string shortName = prefix + "-" + Guid.NewGuid().ToString("N");
        return (shortName, @"\\.\pipe\" + shortName);
    }

    /// <summary>How to launch the sidecar: the packaged engine.exe if present, else the dev
    /// <c>python -u -m hebrew_live_dictation.bridge --pipe &lt;full&gt;</c> (PYTHONPATH=src).</summary>
    public static ProcessStartInfo SidecarStartInfo(string repo, string fullPipeName)
    {
        // Packaged path: spawn the frozen engine directly — no Python, no PYTHONPATH, no repo.
        string? engineExe = PackagedEnginePath();
        if (engineExe != null)
        {
            return new ProcessStartInfo
            {
                FileName = engineExe,
                Arguments = $"--pipe \"{fullPipeName}\"",
                UseShellExecute = false,
                CreateNoWindow = true,             // console=True child, but no visible window
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                WorkingDirectory = Path.GetDirectoryName(engineExe)!,
            };
        }

        // Dev fallback: run the package as a module from the repo tree.
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
