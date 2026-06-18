import tempfile
import unittest

from hebrew_live_dictation.config import Config
from hebrew_live_dictation.stt import auto_select
from hebrew_live_dictation.stt_factory import create_stt_stream


class AutoSelectTests(unittest.TestCase):
    def _config(self, **overrides):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        config = Config(tmp.name)
        if overrides:
            config.update(overrides)
        return config

    def _force_no_google(self):
        original = auto_select._google_available
        auto_select._google_available = lambda config: False
        self.addCleanup(lambda: setattr(auto_select, "_google_available", original))

    def test_prefers_deepgram_when_key_present(self):
        config = self._config(**{"providers.deepgram.api_key": "dg"})
        self.assertEqual(auto_select.select_provider(config), "deepgram")

    def test_google_when_adc(self):
        config = self._config(**{"google.credential_mode": "adc"})
        self.assertEqual(auto_select.select_provider(config), "google_v2")

    def test_groq_when_only_groq_key(self):
        self._force_no_google()
        config = self._config(**{"providers.groq.api_key": "gq"})
        self.assertEqual(auto_select.select_provider(config), "groq")

    def test_whisper_when_only_local_enabled(self):
        self._force_no_google()
        config = self._config(**{"providers.whisper.enabled": True})
        self.assertEqual(auto_select.select_provider(config), "whisper_local")

    def test_defaults_to_google_when_nothing_available(self):
        self._force_no_google()
        config = self._config()
        self.assertEqual(auto_select.select_provider(config), "google_v2")


class SmartAutoFactoryTests(unittest.TestCase):
    def test_smart_auto_selects_deepgram(self):
        from hebrew_live_dictation.stt.deepgram import DeepgramStream

        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            config.update({"stt.mode": "smart_auto", "providers.deepgram.api_key": "dg"})
            stream = create_stt_stream(config, lambda e: None)
            self.assertIsInstance(stream, DeepgramStream)

    def test_smart_auto_wraps_with_fallback_when_whisper_enabled(self):
        from hebrew_live_dictation.stt.fallback import FallbackSpeechClient

        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            config.update(
                {
                    "stt.mode": "smart_auto",
                    "providers.deepgram.api_key": "dg",
                    "providers.whisper.enabled": True,
                }
            )
            stream = create_stt_stream(config, lambda e: None)
            self.assertIsInstance(stream, FallbackSpeechClient)
            self.assertEqual(stream._primary_name, "deepgram")

    def test_smart_auto_uses_local_when_only_whisper(self):
        from hebrew_live_dictation.stt.whisper_local import WhisperLocalStream

        auto = __import__("hebrew_live_dictation.stt.auto_select", fromlist=["_google_available"])
        original = auto._google_available
        auto._google_available = lambda config: False
        try:
            with tempfile.TemporaryDirectory() as tmp:
                config = Config(tmp)
                config.update({"stt.mode": "smart_auto", "providers.whisper.enabled": True})
                stream = create_stt_stream(config, lambda e: None)
                self.assertIsInstance(stream, WhisperLocalStream)
        finally:
            auto._google_available = original


if __name__ == "__main__":
    unittest.main()
