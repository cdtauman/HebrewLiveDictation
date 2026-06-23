import io
import queue
import tempfile
import unittest
import wave
from unittest import mock

import numpy as np

from hebrew_live_dictation.config import Config
from hebrew_live_dictation.stt.groq import GroqStream
from hebrew_live_dictation.stt_factory import create_stt_stream


def _speech():
    return np.full(1600, 5000, dtype=np.int16).tobytes()


def _silence():
    return np.zeros(1600, dtype=np.int16).tobytes()


class GroqUnitTests(unittest.TestCase):
    def _config(self, **overrides):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        config = Config(tmp.name)
        if overrides:
            config.update(overrides)
        return config

    def test_capabilities(self):
        stream = GroqStream(self._config())
        self.assertFalse(stream.capabilities.streaming)
        self.assertTrue(stream.capabilities.batch)
        self.assertTrue(stream.capabilities.needs_credentials)

    def test_to_wav_roundtrips(self):
        stream = GroqStream(self._config())
        pcm = _speech()
        wav_bytes = stream._to_wav(pcm)
        with wave.open(io.BytesIO(wav_bytes), "rb") as w:
            self.assertEqual(w.getnchannels(), 1)
            self.assertEqual(w.getsampwidth(), 2)
            self.assertEqual(w.getframerate(), 16000)
            self.assertEqual(w.getnframes(), 1600)

    def test_transcribe_segment_uses_post(self):
        stream = GroqStream(self._config())
        captured = {}

        def fake_post(wav_bytes, key):
            captured["wav"] = wav_bytes
            captured["key"] = key
            return " שלום עולם "

        stream._post = fake_post
        text = stream._transcribe_segment(_speech(), "k")
        self.assertEqual(text, "שלום עולם")
        self.assertTrue(captured["wav"].startswith(b"RIFF"))

    def test_language_maps_hebrew_aliases_to_groq_he(self):
        self.assertEqual(GroqStream(self._config(**{"languages.primary": "iw-IL"}))._language(), "he")
        self.assertEqual(GroqStream(self._config(**{"languages.primary": "he-IL"}))._language(), "he")

    def test_post_uses_selected_model_and_language(self):
        config = self._config(**{
            "providers.groq.model": "whisper-large-v3-turbo",
            "languages.primary": "iw-IL",
        })
        stream = GroqStream(config)
        resp = mock.Mock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"text": "שלום"}
        with mock.patch("requests.post", return_value=resp) as post:
            self.assertEqual(stream._post(b"RIFF", "secret"), "שלום")
        data = post.call_args.kwargs["data"]
        self.assertEqual(data["model"], "whisper-large-v3-turbo")
        self.assertEqual(data["language"], "he")
        self.assertEqual(data["response_format"], "json")

    def test_unknown_model_falls_back_to_default(self):
        config = self._config(**{"providers.groq.model": "not-a-model"})
        stream = GroqStream(config)
        resp = mock.Mock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"text": "שלום"}
        with mock.patch("requests.post", return_value=resp) as post:
            stream._post(b"RIFF", "secret")
        self.assertEqual(post.call_args.kwargs["data"]["model"], "whisper-large-v3")

    def test_no_key_emits_terminal_error(self):
        events = []
        stream = GroqStream(self._config(), on_event_callback=events.append)
        stream._resolve_key = lambda: ""
        posted = []
        stream._post = lambda *a, **k: posted.append(True)
        stream.start(queue.Queue())
        stream.thread.join(timeout=3.0)
        self.assertTrue(any(e["type"] == "error" for e in events))
        self.assertEqual(posted, [])

    def test_segment_emitted_on_silence_gap(self):
        config = self._config(**{"providers.whisper.segment_silence_ms": 200})
        events = []
        stream = GroqStream(config, on_event_callback=events.append)
        stream._resolve_key = lambda: "k"
        calls = []
        stream._post = lambda wav_bytes, key: calls.append(1) or "טקסט"

        q = queue.Queue()
        for _ in range(5):
            q.put(_speech())
        for _ in range(3):
            q.put(_silence())
        q.put(None)
        stream.start(q)
        stream.thread.join(timeout=5.0)

        finals = [e for e in events if e["type"] == "final"]
        self.assertEqual(len(finals), 1)
        self.assertEqual(finals[0]["text"], "טקסט")
        self.assertEqual(len(calls), 1)


class GroqFactoryTests(unittest.TestCase):
    def test_factory_selects_groq(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            config.update({"stt.provider": "groq"})
            stream = create_stt_stream(config, lambda e: None)
            self.assertIsInstance(stream, GroqStream)


if __name__ == "__main__":
    unittest.main()
