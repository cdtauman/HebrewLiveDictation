import tempfile
import unittest

from hebrew_live_dictation import secrets_store
from hebrew_live_dictation.config import Config


class FakeKeyring:
    """In-memory keyring backend for tests (duck-types the keyring module)."""

    def __init__(self):
        self.store = {}

    def set_password(self, service, name, value):
        self.store[(service, name)] = value

    def get_password(self, service, name):
        return self.store.get((service, name))

    def delete_password(self, service, name):
        self.store.pop((service, name), None)


class FailingSetKeyring(FakeKeyring):
    def set_password(self, service, name, value):
        raise RuntimeError("backend write failed")


class SecretsStoreTests(unittest.TestCase):
    def test_set_get_has_delete_roundtrip(self):
        kr = FakeKeyring()
        self.assertFalse(secrets_store.has_secret("k", keyring_module=kr))
        self.assertTrue(secrets_store.set_secret("k", "v", keyring_module=kr))
        self.assertEqual(secrets_store.get_secret("k", keyring_module=kr), "v")
        self.assertTrue(secrets_store.has_secret("k", keyring_module=kr))
        self.assertTrue(secrets_store.delete_secret("k", keyring_module=kr))
        self.assertIsNone(secrets_store.get_secret("k", keyring_module=kr))

    def test_degraded_mode_when_backend_unusable(self):
        # An unusable backend (every call raises) must degrade gracefully:
        # reads -> None, writes -> False, availability -> False, never raises.
        bad = _NoneModule()
        self.assertFalse(secrets_store.set_secret("k", "v", keyring_module=bad))
        self.assertIsNone(secrets_store.get_secret("k", keyring_module=bad))
        self.assertFalse(secrets_store.has_secret("k", keyring_module=bad))
        self.assertFalse(secrets_store.delete_secret("k", keyring_module=bad))
        self.assertFalse(secrets_store.keyring_available(keyring_module=bad))

    def test_write_failure_is_reported(self):
        kr = FailingSetKeyring()
        self.assertFalse(secrets_store.set_secret("k", "v", keyring_module=kr))

    def test_provider_key_status_never_returns_secret(self):
        kr = FakeKeyring()
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            result = secrets_store.save_provider_api_key(config, "deepgram", "dg-secret", keyring_module=kr)
            self.assertTrue(result["ok"])

            status = secrets_store.provider_key_status(config, "deepgram", keyring_module=kr)

            self.assertTrue(status["configured"])
            self.assertTrue(status["storedInKeyring"])
            self.assertEqual(status["storage"], "keyring")
            self.assertNotIn("apiKey", status)
            self.assertNotIn("secret", jsonish(status).lower())

    def test_provider_api_key_normalizes_provider_name(self):
        kr = FakeKeyring()
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            secrets_store.save_provider_api_key(config, "deepgram", "dg-secret", keyring_module=kr)
            self.assertEqual(
                secrets_store.provider_api_key(config, "Deepgram", keyring_module=kr),
                "dg-secret",
            )

    def test_provider_save_rejects_unknown_or_empty_key(self):
        kr = FakeKeyring()
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            self.assertEqual(
                secrets_store.save_provider_api_key(config, "google_v2", "x", keyring_module=kr)["error"],
                "unsupported_provider",
            )
            self.assertEqual(
                secrets_store.save_provider_api_key(config, "deepgram", "   ", keyring_module=kr)["error"],
                "empty_key",
            )

    def test_provider_save_clears_legacy_plaintext_after_keyring_readback(self):
        kr = FakeKeyring()
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            config.update({"providers.deepgram.api_key": "legacy"})

            result = secrets_store.save_provider_api_key(config, "deepgram", "new-secret", keyring_module=kr)

            self.assertTrue(result["ok"])
            self.assertEqual(config.get("providers.deepgram.api_key", ""), "")
            self.assertEqual(
                secrets_store.get_secret("providers_deepgram_api_key", keyring_module=kr),
                "new-secret",
            )

    def test_provider_clear_removes_keyring_and_plaintext(self):
        kr = FakeKeyring()
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            config.update({"providers.groq.api_key": "legacy"})
            secrets_store.set_secret("providers_groq_api_key", "stored", keyring_module=kr)

            result = secrets_store.clear_provider_api_key(config, "groq", keyring_module=kr)
            status = secrets_store.provider_key_status(config, "groq", keyring_module=kr)

            self.assertTrue(result["ok"])
            self.assertFalse(status["configured"])
            self.assertEqual(config.get("providers.groq.api_key", ""), "")


class _NoneModule:
    """A fake that raises on use, exercising the error-handling paths."""

    def get_password(self, *a, **k):
        raise RuntimeError("no backend")

    def set_password(self, *a, **k):
        raise RuntimeError("no backend")

    def delete_password(self, *a, **k):
        raise RuntimeError("no backend")


def jsonish(value) -> str:
    import json
    return json.dumps(value, sort_keys=True)


class MigrationTests(unittest.TestCase):
    def test_migrates_plaintext_secret_and_clears_after_verified_readback(self):
        kr = FakeKeyring()
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            config.update({"providers.deepgram.api_key": "dg-secret-123"})

            migrated = secrets_store.migrate_plaintext_secrets(config, keyring_module=kr)

            self.assertIn("providers.deepgram.api_key", migrated)
            # Cleared from plaintext config...
            self.assertEqual(config.get("providers.deepgram.api_key", ""), "")
            # ...and present in the keyring under the flattened entry name.
            self.assertEqual(
                secrets_store.get_secret("providers_deepgram_api_key", keyring_module=kr),
                "dg-secret-123",
            )

    def test_migration_leaves_value_when_write_fails(self):
        kr = FailingSetKeyring()
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            config.update({"providers.groq.api_key": "groq-secret"})

            migrated = secrets_store.migrate_plaintext_secrets(config, keyring_module=kr)

            self.assertEqual(migrated, [])
            # Non-destructive: plaintext value is preserved on failure.
            self.assertEqual(config.get("providers.groq.api_key", ""), "groq-secret")

    def test_migration_noop_when_no_secrets_present(self):
        kr = FakeKeyring()
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            migrated = secrets_store.migrate_plaintext_secrets(config, keyring_module=kr)
            self.assertEqual(migrated, [])


if __name__ == "__main__":
    unittest.main()
