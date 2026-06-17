import unittest

from hebrew_live_dictation.app_logging import redact_sensitive
from hebrew_live_dictation.vad import VoiceActivityGate


def pcm16_frame(sample: int, samples: int = 1600) -> bytes:
    return int(sample).to_bytes(2, "little", signed=True) * samples


class VadAndPrivacyTests(unittest.TestCase):
    def test_vad_releases_pre_roll_and_speech_padding(self):
        gate = VoiceActivityGate(frame_ms=100, threshold=0.5, padding_ms=200, min_silence_ms=300)
        silence = pcm16_frame(0)
        speech = pcm16_frame(2000)

        self.assertEqual(gate.process(silence), [])
        self.assertEqual(gate.process(silence), [])
        self.assertEqual(gate.process(speech), [silence, silence, speech])
        self.assertEqual(gate.process(silence), [silence])
        self.assertEqual(gate.process(silence), [silence])
        self.assertEqual(gate.process(silence), [])

    def test_sensitive_windows_credential_paths_are_redacted(self):
        message = (
            "Using Google credentials from config: "
            "C:/Users/Alice/Documents/Google Keys/Hebrew/key.json"
        )

        redacted = redact_sensitive(message)

        self.assertIn("<redacted-path>", redacted)
        self.assertNotIn("Alice", redacted)
        self.assertNotIn("Google Keys", redacted)
        self.assertNotIn("key.json", redacted)


if __name__ == "__main__":
    unittest.main()
