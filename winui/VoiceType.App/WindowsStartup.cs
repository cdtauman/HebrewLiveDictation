using System;
using System.Diagnostics;
using Microsoft.Win32;

namespace VoiceType.Shell;

/// <summary>
/// "Start with Windows" for the unpackaged shell: a per-user HKCU\…\Run entry pointing at
/// this executable. Per-user (HKCU) needs no elevation. The registry is the source of truth
/// for the actual OS behavior, so Settings reads <see cref="IsEnabled"/> to reflect reality
/// rather than trusting only the saved config value.
/// </summary>
internal static class WindowsStartup
{
    private const string RunKeyPath = @"Software\Microsoft\Windows\CurrentVersion\Run";
    private const string ValueName = "VoiceType";

    /// <summary>True only when the Run entry exists AND points at *this* executable. A stale
    /// entry from an old install location counts as not-enabled, so toggling on rewrites it.</summary>
    public static bool IsEnabled()
    {
        try
        {
            using var key = Registry.CurrentUser.OpenSubKey(RunKeyPath);
            if (key?.GetValue(ValueName) is not string raw || string.IsNullOrEmpty(raw)) return false;
            string registered = raw.Trim().Trim('"');
            string current = CurrentExe();
            return !string.IsNullOrEmpty(current)
                && string.Equals(registered, current, StringComparison.OrdinalIgnoreCase);
        }
        catch { return false; }
    }

    private static string CurrentExe() => Process.GetCurrentProcess().MainModule?.FileName ?? "";

    /// <summary>Register or remove the auto-start entry. Returns true on success.</summary>
    public static bool Set(bool enabled)
    {
        try
        {
            using var key = Registry.CurrentUser.OpenSubKey(RunKeyPath, writable: true)
                           ?? Registry.CurrentUser.CreateSubKey(RunKeyPath);
            if (key == null) return false;
            if (enabled)
            {
                string exe = CurrentExe();
                if (string.IsNullOrEmpty(exe)) return false;
                key.SetValue(ValueName, "\"" + exe + "\"");
            }
            else
            {
                key.DeleteValue(ValueName, throwOnMissingValue: false);
            }
            return true;
        }
        catch { return false; }
    }
}
