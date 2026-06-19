using System;
using System.Collections.Generic;

namespace VoiceType.Shell;

/// <summary>In-memory diagnostics ring buffer (surfaced in Settings → Diagnostics later).</summary>
public static class AppLog
{
    private const int Cap = 400;
    private static readonly object Gate = new();
    private static readonly LinkedList<string> _lines = new();

    public static void Add(string line)
    {
        string entry = DateTime.Now.ToString("HH:mm:ss") + "  " + line;
        lock (Gate)
        {
            _lines.AddFirst(entry);
            while (_lines.Count > Cap) _lines.RemoveLast();
        }
    }

    public static IReadOnlyList<string> Snapshot()
    {
        lock (Gate) return new List<string>(_lines);
    }
}
