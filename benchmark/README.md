# STT Provider Benchmark (WER)

Compares the dictation providers by **Word Error Rate** on Hebrew audio so that
provider defaults and Smart Auto ordering are *benchmark-driven*, not assumed.

## Samples

Put paired files in `benchmark/samples/`:

```
sample01.wav   # 16-bit mono PCM, 16 kHz
sample01.txt   # reference transcript (UTF-8, Hebrew)
sample02.wav
sample02.txt
...
```

Samples are intentionally **not** committed (they may contain personal audio).
See `samples/README.md`.

## Run

From the repo root:

```powershell
$env:PYTHONPATH = "src"
python benchmark/run_benchmark.py --samples benchmark/samples `
    --providers google_v2 deepgram groq whisper_local
```

- Cloud providers (`google_v2`, `deepgram`, `groq`) need credentials configured
  in the app (Google SA/ADC; Deepgram/Groq keys in the OS keyring).
- `whisper_local` needs `providers.whisper.enabled = true` and a model available.
- Providers that error (e.g. missing credentials) are reported as **SKIPPED**.

The tool prints per-provider mean WER, a ranking, and a recommended default.
Wiring a result back into Smart Auto's ordering (`stt/auto_select.py`) is a
manual, reviewed decision.

## Notes

- WER core (`hebrew_live_dictation.benchmark`) is unit-tested: word-level edit
  distance over normalized tokens (punctuation/case stripped).
- WER can exceed 1.0 when a hypothesis has many insertions.
