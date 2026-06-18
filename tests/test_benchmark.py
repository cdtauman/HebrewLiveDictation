import os
import tempfile
import threading
import unittest
import wave

from hebrew_live_dictation import benchmark
from hebrew_live_dictation.config import Config


class WerTests(unittest.TestCase):
    def test_identical_is_zero(self):
        self.assertEqual(benchmark.word_error_rate("שלום עולם", "שלום עולם"), 0.0)

    def test_single_substitution(self):
        self.assertAlmostEqual(benchmark.word_error_rate("שלום עולם", "שלום כולם"), 0.5)

    def test_deletion(self):
        self.assertAlmostEqual(benchmark.word_error_rate("שלום עולם", "שלום"), 0.5)

    def test_insertion_can_exceed_logic(self):
        self.assertAlmostEqual(benchmark.word_error_rate("שלום", "שלום עולם"), 1.0)

    def test_empty_reference(self):
        self.assertEqual(benchmark.word_error_rate("", ""), 0.0)
        self.assertEqual(benchmark.word_error_rate("", "x"), 1.0)

    def test_normalization_strips_punctuation_and_case(self):
        self.assertEqual(benchmark.normalize_hebrew("Hello,  WORLD!"), "hello world")
        self.assertEqual(benchmark.word_error_rate("שלום, עולם.", "שלום עולם"), 0.0)


class _FakeProvider:
    def __init__(self, on_event, text):
        self.on_event = on_event
        self.text = text
        self.q = None
        self.thread = None
        self.frames = 0

    def start(self, q):
        self.q = q
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        while True:
            chunk = self.q.get()
            if chunk is None:
                break
            self.frames += 1
        self.on_event({"type": "final", "text": self.text})

    def stop(self):
        if self.q is not None:
            self.q.put(None)
        if self.thread is not None:
            self.thread.join(timeout=1.0)


def _make_create(text):
    def create(name, config, on_event):
        return _FakeProvider(on_event, text)

    return create


def _write_wav(path, seconds=0.3, rate=16000):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))


class TranscribeFileTests(unittest.TestCase):
    def test_drives_provider_over_file_and_collects_final(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            wav = os.path.join(tmp, "s.wav")
            _write_wav(wav)
            text, errors = benchmark.transcribe_file(
                config, "any", wav, create=_make_create("שלום עולם")
            )
            self.assertEqual(text, "שלום עולם")
            self.assertEqual(errors, [])

    def test_evaluate_computes_mean_wer(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            wav = os.path.join(tmp, "s.wav")
            _write_wav(wav)
            result = benchmark.evaluate(
                config, "any", [(wav, "שלום עולם")], create=_make_create("שלום")
            )
            self.assertEqual(result["provider"], "any")
            self.assertAlmostEqual(result["mean_wer"], 0.5)
            self.assertEqual(len(result["rows"]), 1)


if __name__ == "__main__":
    unittest.main()
