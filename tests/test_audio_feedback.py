import os
import tempfile
import unittest
import wave

from hebrew_live_dictation import audio_feedback
from hebrew_live_dictation.config import Config


class AudioFeedbackTests(unittest.TestCase):
    def test_generates_valid_nonsilent_wav(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = audio_feedback.tone_path(tmp, "start", 80)
            self.assertIsNotNone(path)
            self.assertTrue(os.path.exists(path))
            with wave.open(path, "rb") as w:
                self.assertEqual(w.getnchannels(), 1)
                self.assertEqual(w.getsampwidth(), 2)
                frames = w.readframes(w.getnframes())
            self.assertTrue(any(b != 0 for b in frames))  # not silent

    def test_caches_by_kind_and_volume(self):
        with tempfile.TemporaryDirectory() as tmp:
            p1 = audio_feedback.tone_path(tmp, "start", 50)
            p2 = audio_feedback.tone_path(tmp, "start", 50)
            p3 = audio_feedback.tone_path(tmp, "stop", 50)
            self.assertEqual(p1, p2)
            self.assertNotEqual(p1, p3)

    def test_config_defaults_and_normalization(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            self.assertFalse(config.get("audio.feedback_enabled"))
            self.assertEqual(config.get("audio.feedback_volume"), 50)
            config.update({"audio.feedback_volume": 999})
            self.assertEqual(config.get("audio.feedback_volume"), 100)
            config.update({"audio.feedback_volume": -5})
            self.assertEqual(config.get("audio.feedback_volume"), 0)


if __name__ == "__main__":
    unittest.main()
