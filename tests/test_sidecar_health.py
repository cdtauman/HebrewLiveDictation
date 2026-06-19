import tempfile
import unittest

from hebrew_live_dictation.bridge.sidecar import compute_health, engine_label, recent_history


class _FakeConfig:
    def __init__(self, d, config_dir=None):
        self.d = d
        if config_dir is not None:
            self.config_dir = config_dir

    def get(self, key, default=None):
        return self.d.get(key, default)


class HealthTests(unittest.TestCase):
    def test_engine_label_google_pretty(self):
        c = _FakeConfig({"stt.provider": "google_v2", "stt.mode": "api", "google.model": "chirp_3"})
        self.assertEqual(engine_label(c), "Google · Chirp 3")

    def test_engine_label_offline(self):
        self.assertIn("Whisper", engine_label(_FakeConfig({"stt.mode": "local"})))
        self.assertIn("Whisper", engine_label(_FakeConfig({"stt.provider": "whisper_local"})))

    def test_engine_label_other_providers(self):
        self.assertEqual(engine_label(_FakeConfig({"stt.provider": "deepgram"})), "Deepgram")
        self.assertEqual(engine_label(_FakeConfig({"stt.provider": "groq"})), "Groq")

    def test_health_offline_ready(self):
        self.assertTrue(compute_health(_FakeConfig({"providers.whisper.enabled": True}))["offline"]["ready"])
        self.assertTrue(compute_health(_FakeConfig({"stt.mode": "auto_fallback"}))["offline"]["ready"])
        self.assertFalse(compute_health(_FakeConfig({}))["offline"]["ready"])

    def test_health_shape(self):
        h = compute_health(_FakeConfig({"stt.provider": "google_v2", "google.model": "chirp_2"}))
        self.assertEqual(h["engine"]["label"], "Google · Chirp 2")
        self.assertIn("ok", h["microphone"])
        self.assertIn("ready", h["offline"])

    def test_recent_history_empty_and_safe(self):
        # Empty config dir -> no history file -> empty list, never raises.
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(recent_history(_FakeConfig({}, config_dir=tmp), 5), [])


if __name__ == "__main__":
    unittest.main()
