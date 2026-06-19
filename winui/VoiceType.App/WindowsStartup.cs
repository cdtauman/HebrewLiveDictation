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

    public static bool IsEnabled()
    {
        try
        {
            using var key = Registry.CurrentUser.OpenSubKey(RunKeyPath);
            return key?.GetValue(ValueName) != null;
        }
        catch { return false; }
    }

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
                string exe = Process.GetCurrentProcess().MainModule?.FileName ?? "";
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
