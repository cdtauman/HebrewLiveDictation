using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading.Tasks;

namespace VoiceType.Shell;

/// <summary>
/// Best-effort start/stop feedback tones for the WinUI shell. The Python/Qt app
/// already generates the same cached WAV tones; the WinUI shell plays them itself
/// so no audio asset or engine round-trip is needed at status-change time.
/// </summary>
internal sealed class AudioFeedbackPlayer
{
    private const int Rate = 16000;
    private const int DurationMs = 90;
    private const int BitsPerSample = 16;
    private const int Channels = 1;
    private const int SND_ASYNC = 0x0001;
    private const int SND_NODEFAULT = 0x0002;
    private const int SND_FILENAME = 0x00020000;

    private readonly string _directory;
    private bool _enabled;
    private int _volumePercent = 50;

    public AudioFeedbackPlayer(string? directory = null)
    {
        _directory = string.IsNullOrWhiteSpace(directory) ? DefaultDirectory() : directory;
    }

    public void Configure(bool enabled, int volumePercent)
    {
        _enabled = enabled;
        _volumePercent = NormalizeVolume(volumePercent);
    }

    public void Play(string kind)
    {
        if (!_enabled) return;
        int volume = _volumePercent;
        Task.Run(() =>
        {
            try
            {
                string? path = TonePath(_directory, kind, volume);
                if (!string.IsNullOrWhiteSpace(path))
                    PlaySound(path, IntPtr.Zero, SND_FILENAME | SND_ASYNC | SND_NODEFAULT);
            }
            catch (Exception ex)
            {
                AppLog.Add("audio feedback failed: " + ex.Message);
            }
        });
    }

    internal static int NormalizeVolume(int value) => Math.Clamp(value, 0, 100);

    internal static string? TonePath(string directory, string kind, int volumePercent)
    {
        try
        {
            Directory.CreateDirectory(directory);
            int volume = NormalizeVolume(volumePercent);
            string safeKind = kind == "stop" ? "stop" : "start";
            string path = Path.Combine(directory, $"tone_{safeKind}_{volume}.wav");
            if (!File.Exists(path))
                WriteTone(path, safeKind == "stop" ? 440 : 880, volume);
            return path;
        }
        catch (Exception ex)
        {
            AppLog.Add("audio feedback tone generation failed: " + ex.Message);
            return null;
        }
    }

    internal static bool IsToneFileForTest(string path)
    {
        try
        {
            byte[] b = File.ReadAllBytes(path);
            return b.Length > 44
                   && b[0] == (byte)'R' && b[1] == (byte)'I' && b[2] == (byte)'F' && b[3] == (byte)'F'
                   && b[8] == (byte)'W' && b[9] == (byte)'A' && b[10] == (byte)'V' && b[11] == (byte)'E'
                   && b.AsSpan(44).IndexOfAnyExcept((byte)0) >= 0;
        }
        catch { return false; }
    }

    private static void WriteTone(string path, int frequency, int volumePercent)
    {
        int samples = Rate * DurationMs / 1000;
        int dataBytes = samples * Channels * BitsPerSample / 8;
        int fade = Math.Max(1, Rate * 5 / 1000);
        double volume = NormalizeVolume(volumePercent) / 100.0;

        using var fs = File.Create(path);
        using var w = new BinaryWriter(fs);
        w.Write("RIFF"u8.ToArray());
        w.Write(36 + dataBytes);
        w.Write("WAVE"u8.ToArray());
        w.Write("fmt "u8.ToArray());
        w.Write(16);
        w.Write((short)1);
        w.Write((short)Channels);
        w.Write(Rate);
        w.Write(Rate * Channels * BitsPerSample / 8);
        w.Write((short)(Channels * BitsPerSample / 8));
        w.Write((short)BitsPerSample);
        w.Write("data"u8.ToArray());
        w.Write(dataBytes);

        for (int i = 0; i < samples; i++)
        {
            double env = Math.Min(1.0, Math.Min((double)i / fade, (double)(samples - i) / fade));
            short sample = (short)Math.Clamp(
                volume * env * short.MaxValue * Math.Sin(2 * Math.PI * frequency * i / Rate),
                short.MinValue,
                short.MaxValue);
            w.Write(sample);
        }
    }

    private static string DefaultDirectory()
    {
        string appData = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
        return Path.Combine(appData, "VoiceType");
    }

    [DllImport("winmm.dll", CharSet = CharSet.Unicode, SetLastError = false)]
    private static extern bool PlaySound(string pszSound, IntPtr hmod, int fdwSound);
}
