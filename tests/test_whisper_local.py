import queue
import tempfile
import unittest

import numpy as np

from hebrew_live_dictation.config import Config
from hebrew_live_dictation.stt.whisper_local import WhisperLocalStream
from hebrew_live_dictation.stt_factory import create_stt_stream


def _speech_chunk():
    return np.full(1600, 5000, dtype=np.int16).tobytes()


def _silence_chunk():
    return np.zeros(1600, dtype=np.int16).tobytes()


class _FakeSeg:
    def __init__(self, text):
        self.text = text


class _FakeModel:
    def __init__(self):
        self.calls = []

    def transcribe(self, audio, language=None):
        self.calls.append((len(audio), language))
        return ([_FakeSeg(" שלום"), _FakeSeg(" עולם")], object())


def _make_stream(config, model):
    stream = WhisperLocalStream(config, on_event_callback=None)
    stream._ram_preflight = lambda: (True, "")
    stream._model_available = lambda: True   # a model is present (download flow done)
    stream._load_model = lambda: model
    return stream


class WhisperLocalProviderTests(unittest.TestCase):
    def _config(self, **overrides):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        config = Config(tmp.name)
        if overrides:
            config.update(overrides)
        return config

    def test_capabilities(self):
        config = self._config()
        stream = WhisperLocalStream(config)
        self.assertTrue(stream.capabilities.offline)
        self.assertTrue(stream.capabilities.fallback_target)
        self.assertFalse(stream.capabilities.interim)
        self.assertFalse(stream.capabilities.needs_credentials)

    def test_language_maps_iw_to_he(self):
        self.assertEqual(WhisperLocalStream(self._config())._language(), "he")
        self.assertEqual(
            WhisperLocalStream(self._config(**{"languages.primary": "en-US"}))._language(), "en"
        )

    def test_is_speech_detects_energy(self):
        stream = WhisperLocalStream(self._config())
        self.assertTrue(stream._is_speech(_speech_chunk()))
        self.assertFalse(stream._is_speech(_silence_chunk()))

    def test_segment_emitted_on_silence_gap(self):
        config = self._config(**{"providers.whisper.segment_silence_ms": 200})
        model = _FakeModel()
        events = []
        stream = _make_stream(config, model)
        stream.on_event_callback = events.append

        q = queue.Queue()
        for _ in range(5):  # 500 ms speech
            q.put(_speech_chunk())
        for _ in range(3):  # 300 ms silence -> triggers at 200 ms
            q.put(_silence_chunk())
        q.put(None)

        stream.start(q)
        stream.thread.join(timeout=5.0)

        finals = [e for e in events if e["type"] == "final"]
        self.assertEqual(len(finals), 1)
        self.assertEqual(finals[0]["text"], "שלום עולם")
        self.assertEqual(len(model.calls), 1)

    def test_remaining_speech_flushed_on_stop(self):
        config = self._config(**{"providers.whisper.segment_silence_ms": 5000})
        model = _FakeModel()
        events = []
        stream = _make_stream(config, model)
        stream.on_event_callback = events.append

        q = queue.Queue()
        for _ in range(4):  # speech, no trailing silence gap
            q.put(_speech_chunk())
        q.put(None)  # stop signal

        stream.start(q)
        stream.thread.join(timeout=5.0)

        finals = [e for e in events if e["type"] == "final"]
        self.assertEqual(len(finals), 1)
        self.assertEqual(finals[0]["text"], "שלום עולם")

    def test_ram_preflight_failure_emits_error_and_no_final(self):
        config = self._config()
        events = []
        stream = WhisperLocalStream(config, on_event_callback=events.append)
        stream._ram_preflight = lambda: (False, "not enough memory")
        stream._model_available = lambda: True
        stream._load_model = lambda: _FakeModel()  # should never be called

        q = queue.Queue()
        q.put(_speech_chunk())
        q.put(None)
        stream.start(q)
        stream.thread.join(timeout=5.0)

        self.assertTrue(any(e["type"] == "error" for e in events))
        self.assertFalse(any(e["type"] == "final" for e in events))

    def test_missing_model_refuses_and_never_loads(self):
        # Option A: with no explicitly-downloaded model, the provider must surface a clear,
        # routable error and NEVER call _load_model (which is where WhisperModel(...) would
        # implicitly auto-download). This is the choke point that also covers auto_fallback.
        from hebrew_live_dictation.stt import whisper_local as wl

        config = self._config()
        events = []
        loaded = []
        stream = WhisperLocalStream(config, on_event_callback=events.append)
        stream._ram_preflight = lambda: (True, "")
        stream._model_available = lambda: False                 # model NOT installed
        stream._load_model = lambda: loaded.append(True)        # must never run

        q = queue.Queue()
        q.put(_speech_chunk())
        q.put(None)
        stream.start(q)
        stream.thread.join(timeout=5.0)

        self.assertEqual(loaded, [])                            # no implicit download attempt
        errs = [e for e in events if e["type"] == "error"]
        self.assertTrue(errs)
        self.assertEqual(errs[0]["message"], wl.OFFLINE_MODEL_MISSING_MESSAGE)
        self.assertFalse(any(e["type"] == "final" for e in events))


class WhisperFactoryGateTests(unittest.TestCase):
    def test_disabled_whisper_falls_back_to_google(self):
        from hebrew_live_dictation.google_stt_v2_stream import GoogleSTTV2Stream

        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            config.update({"stt.provider": "whisper_local"})  # enabled defaults False
            stream = create_stt_stream(config, lambda e: None)
            self.assertIsInstance(stream, GoogleSTTV2Stream)

    def test_enabled_whisper_is_selected(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            config.update({"stt.provider": "whisper_local", "providers.whisper.enabled": True})
            stream = create_stt_stream(config, lambda e: None)
            self.assertIsInstance(stream, WhisperLocalStream)


if __name__ == "__main__":
    unittest.main()
