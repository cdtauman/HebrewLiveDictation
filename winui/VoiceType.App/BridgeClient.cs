using System;
using System.Collections.Concurrent;
using System.IO;
using System.IO.Pipes;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace VoiceType.Shell;

/// <summary>
/// WinUI-side client for the Python engine bridge. Connects to the named pipe
/// \\.\pipe\voicetype-bridge and speaks newline-delimited JSON-RPC. .NET pipes
/// use overlapped I/O, so concurrent read/write is safe (unlike a naive sync client).
/// </summary>
public sealed class BridgeClient : IDisposable
{
    public const string PipeName = "voicetype-bridge";

    private readonly NamedPipeClientStream _pipe = new(".", PipeName, PipeDirection.InOut, PipeOptions.Asynchronous);
    private StreamWriter? _writer;
    private int _id;
    private readonly ConcurrentDictionary<int, TaskCompletionSource<JsonElement>> _pending = new();
    private readonly object _writeLock = new();

    /// <summary>Raised for server-pushed events (status/text/error/heartbeat/hotkey).</summary>
    public event Action<JsonElement>? EventReceived;

    public async Task ConnectAsync(int timeoutMs)
    {
        await _pipe.ConnectAsync(timeoutMs);
        _writer = new StreamWriter(_pipe, new UTF8Encoding(false)) { AutoFlush = true, NewLine = "\n" };
        _ = Task.Run(ReadLoopAsync);
    }

    private async Task ReadLoopAsync()
    {
        using var reader = new StreamReader(_pipe, new UTF8Encoding(false));
        string? line;
        while ((line = await reader.ReadLineAsync()) != null)
        {
            line = line.Trim();
            if (line.Length == 0) continue;
            JsonElement msg;
            try { msg = JsonDocument.Parse(line).RootElement; }
            catch { continue; }

            if (msg.TryGetProperty("method", out var m) && m.GetString() == "event")
            {
                if (msg.TryGetProperty("params", out var p))
                    EventReceived?.Invoke(p.Clone());
            }
            else if (msg.TryGetProperty("id", out var idEl) && idEl.TryGetInt32(out var id)
                     && _pending.TryRemove(id, out var tcs))
            {
                if (msg.TryGetProperty("result", out var res)) tcs.TrySetResult(res.Clone());
                else if (msg.TryGetProperty("error", out var err))
                    tcs.TrySetException(new Exception(err.ToString()));
                else tcs.TrySetResult(default);
            }
        }
        // pipe closed: fail any outstanding calls
        foreach (var kv in _pending)
            kv.Value.TrySetException(new IOException("bridge pipe closed"));
        _pending.Clear();
    }

    public async Task<JsonElement> RpcAsync(string method, object? prms = null, int timeoutMs = 8000)
    {
        if (_writer == null) throw new InvalidOperationException("not connected");
        int id = Interlocked.Increment(ref _id);
        var tcs = new TaskCompletionSource<JsonElement>(TaskCreationOptions.RunContinuationsAsynchronously);
        _pending[id] = tcs;
        var payload = JsonSerializer.Serialize(new { jsonrpc = "2.0", id, method, @params = prms ?? new { } });
        lock (_writeLock) { _writer.WriteLine(payload); }
        using var cts = new CancellationTokenSource(timeoutMs);
        await using (cts.Token.Register(() => { if (_pending.TryRemove(id, out var t)) t.TrySetException(new TimeoutException(method)); }))
            return await tcs.Task;
    }

    public void Dispose()
    {
        try { _writer?.Dispose(); } catch { }
        try { _pipe.Dispose(); } catch { }
    }
}
