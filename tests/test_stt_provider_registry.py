import tempfile
import unittest

from hebrew_live_dictation.config import Config
from hebrew_live_dictation.stt.base import ProviderCapabilities, SpeechClientBase, STTErrorKind
from hebrew_live_dictation.stt.registry import REGISTRY, ProviderRegistry
from hebrew_live_dictation.stt_factory import DEFAULT_PROVIDER, create_stt_stream


class STTRegistryTests(unittest.TestCase):
    def test_google_v2_registered_with_streaming_capabilities(self):
        self.assertIn("google_v2", REGISTRY.known())
        caps = REGISTRY.capabilities("google_v2")
        self.assertTrue(caps.streaming)
        self.assertTrue(caps.interim)
        self.assertFalse(caps.offline)
        self.assertFalse(caps.fallback_target)
        self.assertTrue(caps.needs_credentials)

    def test_registry_caps_match_class_caps(self):
        # Registry declares google_v2 capabilities standalone (lazy import), so
        # guard against drift from the class's own declaration.
        from hebrew_live_dictation.google_stt_v2_stream import GoogleSTTV2Stream

        self.assertEqual(REGISTRY.capabilities("google_v2"), GoogleSTTV2Stream.capabilities)

    def test_unknown_provider_raises_clear_error(self):
        with self.assertRaises(ValueError) as ctx:
            REGISTRY.capabilities("does-not-exist")
        self.assertIn("Unknown STT provider", str(ctx.exception))
        with self.assertRaises(ValueError):
            REGISTRY.create("does-not-exist", config=None)

    def test_register_and_create_roundtrip(self):
        reg = ProviderRegistry()
        captured = {}

        def fake_factory(config, on_event_callback):
            captured["config"] = config
            captured["cb"] = on_event_callback
            return "FAKE"

        reg.register(
            "fake",
            fake_factory,
            ProviderCapabilities(name="fake", batch=True, offline=True, fallback_target=True),
        )
        self.assertTrue(reg.is_registered("fake"))
        self.assertEqual(reg.known(), ["fake"])
        self.assertTrue(reg.capabilities("fake").offline)

        obj = reg.create("fake", config={"k": 1}, on_event_callback="CB")
        self.assertEqual(obj, "FAKE")
        self.assertEqual(captured["config"], {"k": 1})
        self.assertEqual(captured["cb"], "CB")


class SpeechClientBaseTests(unittest.TestCase):
    def test_base_contract_and_cancel_defaults_to_stop(self):
        stops = []

        class Dummy(SpeechClientBase):
            capabilities = ProviderCapabilities(name="dummy", batch=True)

            def start(self, audio_queue):
                self.active = True

            def stop(self):
                self.active = False
                stops.append(True)

        events = []
        d = Dummy(config=None, on_event_callback=events.append)
        d.start(audio_queue=None)
        self.assertTrue(d.active)
        d.cancel()  # default cancel -> stop
        self.assertFalse(d.active)
        self.assertEqual(stops, [True])
        self.assertIsNone(d.restart_stream())

        d._emit_event({"type": "status", "message": "ok"})
        self.assertEqual(events, [{"type": "status", "message": "ok"}])

    def test_error_kinds_exist(self):
        self.assertEqual(STTErrorKind.TERMINAL.value, "terminal")
        self.assertEqual(STTErrorKind.RETRYABLE.value, "retryable")


class STTConfigTests(unittest.TestCase):
    def test_defaults_have_google_v2_provider_and_api_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            self.assertEqual(config.get("stt.provider"), "google_v2")
            self.assertEqual(config.get("stt.mode"), "api")
            # Phase A must not bump the schema version (pinned by other tests).
            self.assertEqual(config.get("schema_version"), 4)

    def test_invalid_stt_mode_normalizes_to_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            config.update({"stt.mode": "bogus"})
            self.assertEqual(config.get("stt.mode"), "api")

    def test_blank_provider_normalizes_to_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            config.update({"stt.provider": "   "})
            self.assertEqual(config.get("stt.provider"), "google_v2")

    def test_valid_custom_mode_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            config.update({"stt.mode": "auto_fallback"})
            self.assertEqual(config.get("stt.mode"), "auto_fallback")


class STTFactoryTests(unittest.TestCase):
    def test_factory_default_config_creates_google_stream(self):
        from hebrew_live_dictation.google_stt_v2_stream import GoogleSTTV2Stream

        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            events = []
            cb = events.append
            stream = create_stt_stream(config, cb)
            self.assertIsInstance(stream, GoogleSTTV2Stream)
            self.assertIs(stream.on_event_callback, cb)

    def test_factory_unknown_provider_falls_back_to_google(self):
        from hebrew_live_dictation.google_stt_v2_stream import GoogleSTTV2Stream

        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            # A non-empty but unregistered provider survives normalization;
            # the factory must fall back gracefully rather than raise.
            config.update({"stt.provider": "nonexistent"})
            stream = create_stt_stream(config, lambda e: None)
            self.assertIsInstance(stream, GoogleSTTV2Stream)

    def test_default_provider_constant(self):
        self.assertEqual(DEFAULT_PROVIDER, "google_v2")


if __name__ == "__main__":
    unittest.main()
