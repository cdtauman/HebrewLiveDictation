import base64
import hashlib
import json
import os
import tempfile
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from hebrew_live_dictation import updater
from hebrew_live_dictation.config import Config


def _keypair():
    priv = Ed25519PrivateKey.generate()
    raw_pub = priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return priv, base64.b64encode(raw_pub).decode()


class SignatureTests(unittest.TestCase):
    def test_valid_signature(self):
        priv, pub = _keypair()
        msg = b'{"version":"2.0.0"}'
        self.assertTrue(updater.verify_signature(msg, priv.sign(msg), pub))

    def test_tampered_message_fails(self):
        priv, pub = _keypair()
        self.assertFalse(updater.verify_signature(b"tampered", priv.sign(b"original"), pub))

    def test_wrong_key_fails(self):
        priv, _ = _keypair()
        _, other_pub = _keypair()
        self.assertFalse(updater.verify_signature(b"m", priv.sign(b"m"), other_pub))

    def test_empty_inputs_fail(self):
        self.assertFalse(updater.verify_signature(b"m", b"", "x"))
        self.assertFalse(updater.verify_signature(b"m", b"sig", ""))


class ShouldUpdateTests(unittest.TestCase):
    def test_newer_available(self):
        self.assertTrue(updater.should_update("1.0.0", {"version": "1.1.0"})[0])

    def test_same_version_no_update(self):
        self.assertFalse(updater.should_update("1.1.0", {"version": "1.1.0"})[0])

    def test_older_no_update(self):
        self.assertFalse(updater.should_update("2.0.0", {"version": "1.0.0"})[0])

    def test_disabled_kill_switch(self):
        self.assertFalse(updater.should_update("1.0.0", {"version": "9.9.9", "disabled": True})[0])


class CheckForUpdateTests(unittest.TestCase):
    def _config(self, **overrides):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        config = Config(tmp.name)
        if overrides:
            config.update(overrides)
        return config

    def _enabled_config(self, pub):
        return self._config(
            **{"updater.enabled": True, "updater.endpoint": "https://x/latest.json", "updater.public_key": pub}
        )

    def test_disabled_by_default(self):
        self.assertEqual(updater.check_for_update(self._config(), "1.0.0")["status"], "disabled")

    def test_not_configured_without_endpoint(self):
        config = self._config(**{"updater.enabled": True})
        self.assertEqual(updater.check_for_update(config, "1.0.0")["status"], "not_configured")

    def test_update_available_with_valid_signature(self):
        priv, pub = _keypair()
        manifest = json.dumps({"version": "2.0.0", "url": "https://x/app.exe", "notes": "hi"})
        sig = priv.sign(manifest.encode())

        def fetch(url, binary=False):
            return sig if url.endswith(".sig") else manifest

        result = updater.check_for_update(self._enabled_config(pub), "1.0.0", fetch=fetch)
        self.assertEqual(result["status"], "update_available")
        self.assertEqual(result["manifest"]["version"], "2.0.0")

    def test_tampered_manifest_is_untrusted(self):
        priv, pub = _keypair()
        sig = priv.sign(json.dumps({"version": "2.0.0"}).encode())
        tampered = json.dumps({"version": "9.9.9"})

        def fetch(url, binary=False):
            return sig if url.endswith(".sig") else tampered

        self.assertEqual(updater.check_for_update(self._enabled_config(pub), "1.0.0", fetch=fetch)["status"], "untrusted")

    def test_up_to_date(self):
        priv, pub = _keypair()
        manifest = json.dumps({"version": "1.0.0"})
        sig = priv.sign(manifest.encode())

        def fetch(url, binary=False):
            return sig if url.endswith(".sig") else manifest

        self.assertEqual(updater.check_for_update(self._enabled_config(pub), "1.0.0", fetch=fetch)["status"], "up_to_date")

    def test_network_error_is_reported(self):
        priv, pub = _keypair()

        def fetch(url, binary=False):
            raise OSError("no network")

        self.assertEqual(updater.check_for_update(self._enabled_config(pub), "1.0.0", fetch=fetch)["status"], "error")


class InstallerTests(unittest.TestCase):
    def test_sha256_verify(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "f.bin")
            with open(path, "wb") as f:
                f.write(b"hello")
            self.assertTrue(updater.verify_installer_sha256(path, hashlib.sha256(b"hello").hexdigest()))
            self.assertFalse(updater.verify_installer_sha256(path, "deadbeef"))

    def test_download_and_launch_verifies_and_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = b"installer-bytes"
            manifest = {"url": "https://x/app.exe", "sha256": hashlib.sha256(data).hexdigest()}
            launched = []
            ok, path = updater.download_and_launch(
                manifest, tmp, fetch=lambda url, binary=False: data, runner=launched.append
            )
            self.assertTrue(ok)
            self.assertEqual(launched, [path])

    def test_download_rejects_bad_sha(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = {"url": "https://x/app.exe", "sha256": "00"}
            ok, _ = updater.download_and_launch(
                manifest, tmp, fetch=lambda url, binary=False: b"x", runner=lambda p: None
            )
            self.assertFalse(ok)


class UpdaterConfigTests(unittest.TestCase):
    def test_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            self.assertFalse(config.get("updater.enabled"))
            self.assertEqual(config.get("updater.endpoint"), "")


if __name__ == "__main__":
    unittest.main()
