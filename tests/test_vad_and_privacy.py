import queue
import tempfile
import unittest

from hebrew_live_dictation.app_logging import redact_secrets, redact_sensitive
from hebrew_live_dictation.config import Config
from hebrew_live_dictation.vad import VoiceActivityGate


# Synthetic token shapes for the redaction tests. These were never real credentials;
# they are assembled from short fragments at import time so no contiguous secret-shaped
# literal exists in the source file (keeps automated secret scanners from raising
# false positives on this test, while the runtime values still exercise the patterns).
_FAKE_DG_HEX = "0123456789ab" + "cdef01234567" + "89abcdef0123" + "4567"       # 40-hex Deepgram shape
_FAKE_GSK = "gsk_" + "A1b2C3d4E5f6" + "G7h8I9j0K1l2" + "M3n4O5p6Q7r8"           # Groq gsk_ shape
_FAKE_BEARER = "AbCdEf0123" + "456789AbCdEf" + "0123456789xyz"
_FAKE_HEADER_TOKEN = "abcd1234EFGH" + "5678ijkl9012" + "MNOP3456qrst"


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


class SecretRedactionTests(unittest.TestCase):
    """MF3: provider/API tokens must be scrubbed from logs, error strings, and
    diagnostics — not just credential file paths."""

    def test_authorization_header_token_is_redacted(self):
        token = _FAKE_HEADER_TOKEN
        out = redact_secrets(f"sent Authorization: Token {token} to deepgram")
        self.assertNotIn(token, out)
        self.assertIn("<redacted-secret>", out)
        self.assertIn("Authorization", out)  # label preserved, value gone

    def test_bearer_token_is_redacted(self):
        token = _FAKE_BEARER
        out = redact_secrets(f"Bearer {token} was rejected (401)")
        self.assertNotIn(token, out)
        self.assertIn("<redacted-secret>", out)

    def test_known_provider_key_prefixes_are_redacted(self):
        groq = _FAKE_GSK
        deepgram = _FAKE_DG_HEX
        out = redact_secrets(f"groq={groq} deepgram={deepgram}")
        self.assertNotIn(groq, out)
        self.assertNotIn(deepgram, out)

    def test_redact_sensitive_also_strips_tokens(self):
        # The central formatter path (redact_sensitive) must scrub tokens too, so any
        # third-party log line that echoes a request header is safe.
        token = _FAKE_DG_HEX
        self.assertNotIn(token, redact_sensitive(f"Authorization: Token {token}"))

    def test_deepgram_exception_message_is_redacted(self):
        from hebrew_live_dictation.stt.deepgram import DeepgramStream

        token = _FAKE_DG_HEX
        events = []
        with tempfile.TemporaryDirectory() as tmp:
            stream = DeepgramStream(Config(tmp), on_event_callback=events.append)
            stream._resolve_key = lambda: "k"

            def boom(url, key):
                raise RuntimeError(f"handshake 403: Authorization Token {token} rejected")

            stream._connect = boom
            stream.start(queue.Queue())
            stream.thread.join(timeout=3.0)

        errs = [e for e in events if e.get("type") == "error"]
        self.assertTrue(errs, "expected a terminal error event")
        self.assertNotIn(token, errs[0]["message"])
        self.assertIn("<redacted-secret>", errs[0]["message"])

    def test_groq_exception_message_is_redacted(self):
        import numpy as np

        from hebrew_live_dictation.stt.groq import GroqStream

        token = _FAKE_GSK + "s9"
        events = []
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            config.update({"providers.whisper.segment_silence_ms": 200})
            stream = GroqStream(config, on_event_callback=events.append)
            stream._resolve_key = lambda: "k"

            def boom(wav_bytes, key):
                raise RuntimeError(f"401 Unauthorized (Authorization: Bearer {token})")

            stream._post = boom
            q = queue.Queue()
            for _ in range(5):
                q.put(np.full(1600, 5000, dtype=np.int16).tobytes())
            for _ in range(3):
                q.put(np.zeros(1600, dtype=np.int16).tobytes())
            q.put(None)
            stream.start(q)
            stream.thread.join(timeout=5.0)

        errs = [e for e in events if e.get("type") == "error"]
        self.assertTrue(errs, "expected a terminal error event")
        self.assertNotIn(token, errs[0]["message"])
        self.assertIn("<redacted-secret>", errs[0]["message"])

    def test_diagnostics_snapshot_contains_no_raw_token(self):
        import json

        from hebrew_live_dictation.bridge import sidecar

        token = _FAKE_GSK + "Z9" + _FAKE_DG_HEX[:12]
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            # Even a legacy plaintext key in config must never echo into diagnostics.
            config.update({
                "providers.deepgram.api_key": token,
                "providers.groq.api_key": token,
            })
            snap = sidecar.diagnostics_snapshot(config, state="idle", config_dir=tmp)
            blob = json.dumps(snap, ensure_ascii=False)
        self.assertNotIn(token, blob)


if __name__ == "__main__":
    unittest.main()
