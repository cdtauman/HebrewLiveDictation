import tempfile
import unittest

from hebrew_live_dictation.config import Config
from hebrew_live_dictation.stt import verify as verify_mod
from hebrew_live_dictation import models


class _Resp:
    def __init__(self, code):
        self.status_code = code


def _get(code):
    def get(url, headers=None, timeout=None):
        return _Resp(code)

    return get


class VerifyTests(unittest.TestCase):
    def _config(self, **overrides):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        config = Config(tmp.name)
        if overrides:
            config.update(overrides)
        return config

    def test_deepgram_no_key(self):
        ok, msg = verify_mod.verify(self._config(), "deepgram", http_get=_get(200))
        self.assertFalse(ok)
        self.assertIn("No deepgram", msg)

    def test_deepgram_ok(self):
        config = self._config(**{"providers.deepgram.api_key": "k"})
        ok, msg = verify_mod.verify(config, "deepgram", http_get=_get(200))
        self.assertTrue(ok)

    def test_deepgram_rejected(self):
        config = self._config(**{"providers.deepgram.api_key": "k"})
        ok, msg = verify_mod.verify(config, "deepgram", http_get=_get(401))
        self.assertFalse(ok)
        self.assertIn("401", msg)

    def test_groq_ok(self):
        config = self._config(**{"providers.groq.api_key": "k"})
        ok, _ = verify_mod.verify(config, "groq", http_get=_get(200))
        self.assertTrue(ok)

    def test_google_with_service_account_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            creds = f"{tmp}/sa.json"
            with open(creds, "w", encoding="utf-8") as f:
                f.write('{"type": "service_account", "project_id": "proj-x"}')
            config.update(
                {"google.credential_mode": "service_account_json", "google.credentials_path": creds}
            )
            ok, msg = verify_mod.verify(config, "google_v2")
            self.assertTrue(ok)
            self.assertIn("proj-x", msg)

    def test_google_without_credentials(self):
        ok, _ = verify_mod.verify(self._config(**{"google.credential_mode": "service_account_json"}), "google_v2")
        self.assertFalse(ok)

    def test_whisper_blocked_by_ram(self):
        original = models._available_ram_mb
        models._available_ram_mb = lambda: 128
        try:
            ok, msg = verify_mod.verify(self._config(), "whisper_local")
            self.assertFalse(ok)
        finally:
            models._available_ram_mb = original

    def test_unknown_provider(self):
        ok, _ = verify_mod.verify(self._config(), "nope")
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
