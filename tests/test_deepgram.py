import json
import queue
import tempfile
import time
import unittest

from hebrew_live_dictation.config import Config
from hebrew_live_dictation.stt.deepgram import DeepgramStream
from hebrew_live_dictation.stt_factory import create_stt_stream


class FakeConn:
    def __init__(self, messages):
        self._messages = list(messages)
        self.sent = []
        self.closed = False

    def recv(self, timeout=None):
        if self._messages:
            return self._messages.pop(0)
        return None

    def send(self, data):
        self.sent.append(data)

    def close(self):
        self.closed = True


class DeepgramUnitTests(unittest.TestCase):
    def _config(self, **overrides):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        config = Config(tmp.name)
        if overrides:
            config.update(overrides)
        return config

    def test_capabilities(self):
        stream = DeepgramStream(self._config())
        self.assertTrue(stream.capabilities.streaming)
        self.assertTrue(stream.capabilities.interim)
        self.assertTrue(stream.capabilities.needs_credentials)
        self.assertFalse(stream.capabilities.offline)

    def test_build_url_contains_expected_params(self):
        url = DeepgramStream(self._config())._build_url()
        self.assertIn("model=nova-3", url)
        self.assertIn("language=he", url)
        self.assertIn("encoding=linear16", url)
        self.assertIn("sample_rate=16000", url)
        self.assertIn("interim_results=true", url)
        self.assertIn("punctuate=true", url)

    def test_build_url_uses_provider_specific_flags(self):
        url = DeepgramStream(
            self._config(
                **{
                    "google.interim_results": True,
                    "google.automatic_punctuation": True,
                    "providers.deepgram.interim_results": False,
                    "providers.deepgram.punctuate": False,
                }
            )
        )._build_url()
        self.assertIn("interim_results=false", url)
        self.assertIn("punctuate=false", url)

    def test_language_maps_hebrew_aliases_to_deepgram_he(self):
        self.assertIn("language=he", DeepgramStream(self._config(**{"languages.primary": "he-IL"}))._build_url())
        self.assertIn("language=he", DeepgramStream(self._config(**{"languages.primary": "iw-IL"}))._build_url())

    def test_handle_message_final_and_interim(self):
        events = []
        stream = DeepgramStream(self._config(), on_event_callback=events.append)
        stream._handle_message(json.dumps({"channel": {"alternatives": [{"transcript": "שלום", "confidence": 0.8}]}, "is_final": False}))
        stream._handle_message(json.dumps({"channel": {"alternatives": [{"transcript": "שלום עולם", "confidence": 0.9}]}, "is_final": True}))
        self.assertEqual([e["type"] for e in events], ["interim", "final"])
        self.assertEqual(events[1]["text"], "שלום עולם")

    def test_handle_message_ignores_empty_and_malformed(self):
        events = []
        stream = DeepgramStream(self._config(), on_event_callback=events.append)
        stream._handle_message("not json")
        stream._handle_message(json.dumps({"metadata": {"x": 1}}))
        stream._handle_message(json.dumps({"channel": {"alternatives": [{"transcript": ""}]}}))
        self.assertEqual(events, [])

    def test_resolve_key_from_config_fallback(self):
        config = self._config(**{"providers.deepgram.api_key": "dgkey"})
        self.assertEqual(DeepgramStream(config)._resolve_key(), "dgkey")

    def test_no_key_emits_terminal_error_and_does_not_connect(self):
        events = []
        stream = DeepgramStream(self._config(), on_event_callback=events.append)
        stream._resolve_key = lambda: ""
        connected = []
        stream._connect = lambda url, key: connected.append(True)
        stream.start(queue.Queue())
        stream.thread.join(timeout=3.0)
        self.assertTrue(any(e["type"] == "error" for e in events))
        self.assertEqual(connected, [])

    def test_streaming_loop_emits_from_fake_connection(self):
        events = []
        stream = DeepgramStream(self._config(), on_event_callback=events.append)
        stream._resolve_key = lambda: "k"
        msg = json.dumps({"channel": {"alternatives": [{"transcript": "שלום"}]}, "is_final": True})
        fake = FakeConn([msg])
        stream._connect = lambda url, key: fake
        audio = queue.Queue()
        audio.put(None)  # end the sender immediately
        stream.start(audio)
        stream.thread.join(timeout=3.0)
        self.assertTrue(any(e["type"] == "final" and e["text"] == "שלום" for e in events))


class DeepgramFactoryTests(unittest.TestCase):
    def test_factory_selects_deepgram(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            config.update({"stt.provider": "deepgram"})
            stream = create_stt_stream(config, lambda e: None)
            self.assertIsInstance(stream, DeepgramStream)


if __name__ == "__main__":
    unittest.main()
