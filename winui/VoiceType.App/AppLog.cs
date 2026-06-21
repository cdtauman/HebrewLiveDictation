using System;
using System.Collections.Generic;
using System.IO;

namespace VoiceType.Shell;

/// <summary>Shell-side diagnostics. Keeps an in-memory ring buffer (surfaced in Settings →
/// Diagnostics) AND appends durably to <c>%APPDATA%\VoiceType\shell.log</c>, so a frozen-engine
/// crash or a bridge launch error that happens before the engine's own Python logging starts is
/// still recoverable from disk. Engine stdout/stderr (drained as "sidecar: …") and bridge launch
/// failures both flow through <see cref="Add"/>, so they are persisted too.</summary>
public static class AppLog
{
    private const int Cap = 400;
    private const long MaxBytes = 1_000_000;   // rotate the diagnostic log so it can't grow unbounded
    private static readonly object Gate = new();
    private static readonly LinkedList<string> _lines = new();
    private static readonly string? _file = ResolveLogPath();

    private static string? ResolveLogPath()
    {
        try
        {
            string dir = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "VoiceType");
            Directory.CreateDirectory(dir);
            return Path.Combine(dir, "shell.log");
        }
        catch { return null; }
    }

    /// <summary>Path of the durable shell log (for Diagnostics/support text), or null if unavailable.</summary>
    public static string? FilePath => _file;

    public static void Add(string line)
    {
        string entry = DateTime.Now.ToString("HH:mm:ss") + "  " + line;
        lock (Gate)
        {
            _lines.AddFirst(entry);
            while (_lines.Count > Cap) _lines.RemoveLast();
            WriteFile(DateTime.Now.ToString("yyyy-MM-dd ") + entry);
        }
    }

    // Called under Gate. Best-effort: diagnostics must never throw into the app.
    private static void WriteFile(string entry)
    {
        if (_file == null) return;
        try
        {
            var fi = new FileInfo(_file);
            if (fi.Exists && fi.Length > MaxBytes)
            {
                string bak = _file + ".1";
                try { if (File.Exists(bak)) File.Delete(bak); File.Move(_file, bak); } catch { }
            }
            File.AppendAllText(_file, entry + Environment.NewLine);
        }
        catch { /* swallow: a logging failure must not affect the shell */ }
    }

    public static IReadOnlyList<string> Snapshot()
    {
        lock (Gate) return new List<string>(_lines);
    }
}
