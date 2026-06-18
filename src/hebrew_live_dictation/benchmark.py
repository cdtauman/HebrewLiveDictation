"""Word Error Rate (WER) benchmarking for STT providers.

Re-implements (in Python, not ported) the idea behind repo 1's benchmark suite:
run each provider over the same Hebrew audio samples and compare WER so provider
defaults / Smart Auto ordering are data-driven rather than assumed.

The WER core (normalization + word-level edit distance) is pure-stdlib and unit
tested. ``transcribe_file`` drives any registered provider over a WAV by feeding
its audio queue in frames and collecting ``final`` events, so it works for both
streaming (google/deepgram) and batch (groq/whisper_local) providers.
"""

import logging
import queue
import re
import threading
import wave


logger = logging.getLogger("Benchmark")


def normalize_hebrew(text: str) -> str:
    text = (text or "").strip().lower()
    # Drop punctuation/symbols, keep word characters (incl. Hebrew) and spaces.
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def _edit_distance(a, b) -> int:
    m, n = len(a), len(b)
    prev = list(range(n + 1))
    for i in range(1, m + 1):
        cur = [i] + [0] * n
        for j in range(1, n + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[n]


def word_error_rate(reference: str, hypothesis: str, normalize: bool = True) -> float:
    """WER = (S + D + I) / N over word tokens. May exceed 1.0 (insertions)."""
    if normalize:
        reference = normalize_hebrew(reference)
        hypothesis = normalize_hebrew(hypothesis)
    ref = reference.split()
    hyp = hypothesis.split()
    if not ref:
        return 0.0 if not hyp else 1.0
    return _edit_distance(ref, hyp) / len(ref)


def _read_wav_pcm16(path):
    with wave.open(path, "rb") as w:
        if w.getsampwidth() != 2 or w.getnchannels() != 1:
            raise ValueError("Benchmark expects 16-bit mono PCM WAV files.")
        rate = w.getframerate()
        frames = w.readframes(w.getnframes())
    return frames, rate


def transcribe_file(config, provider_name, wav_path, frame_ms=100, timeout=180, create=None):
    """Drive a provider over a WAV file; return (text, errors)."""
    if create is None:
        from .stt.registry import REGISTRY

        create = REGISTRY.create

    pcm, rate = _read_wav_pcm16(wav_path)
    bytes_per_frame = max(2, int(rate * frame_ms / 1000) * 2)

    finals = []
    errors = []

    def on_event(event):
        kind = event.get("type")
        if kind == "final":
            finals.append(event.get("text", ""))
        elif kind == "error":
            errors.append(event.get("message", ""))

    provider = create(provider_name, config, on_event)
    audio = queue.Queue()
    provider.start(audio)
    for i in range(0, len(pcm), bytes_per_frame):
        audio.put(pcm[i : i + bytes_per_frame])
    audio.put(None)

    thread = getattr(provider, "thread", None)
    if isinstance(thread, threading.Thread):
        thread.join(timeout=timeout)
    try:
        provider.stop()
    except Exception:
        pass

    return " ".join(t for t in finals if t).strip(), errors


def evaluate(config, provider_name, samples, create=None):
    """samples: list of (wav_path, reference_text). Returns a result dict."""
    rows = []
    for wav_path, reference in samples:
        try:
            hypothesis, errors = transcribe_file(config, provider_name, wav_path, create=create)
        except Exception as e:
            rows.append({"wav": wav_path, "wer": None, "error": str(e), "hypothesis": ""})
            continue
        if errors:
            rows.append({"wav": wav_path, "wer": None, "error": "; ".join(errors), "hypothesis": hypothesis})
            continue
        rows.append(
            {
                "wav": wav_path,
                "wer": word_error_rate(reference, hypothesis),
                "error": None,
                "hypothesis": hypothesis,
            }
        )
    scored = [r["wer"] for r in rows if r["wer"] is not None]
    mean_wer = sum(scored) / len(scored) if scored else None
    return {"provider": provider_name, "mean_wer": mean_wer, "rows": rows}
