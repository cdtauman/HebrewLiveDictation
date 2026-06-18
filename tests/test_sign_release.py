import importlib.util
import os
import tempfile
import unittest

from hebrew_live_dictation import updater


def _load_script():
    path = os.path.join(os.path.dirname(__file__), "..", "scripts", "sign_release.py")
    spec = importlib.util.spec_from_file_location("sign_release", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SignReleaseTests(unittest.TestCase):
    def test_keygen_sign_verify_roundtrip(self):
        sign_release = _load_script()
        with tempfile.TemporaryDirectory() as tmp:
            priv_path, pub_b64 = sign_release.keygen(tmp)
            self.assertTrue(os.path.exists(priv_path))
            self.assertTrue(pub_b64)

            manifest_path = os.path.join(tmp, "latest.json")
            payload = b'{"version":"2.0.0","url":"https://x/app.exe","sha256":"ab"}'
            with open(manifest_path, "wb") as f:
                f.write(payload)
            sig_path = os.path.join(tmp, "latest.json.sig")
            sign_release.sign(priv_path, manifest_path, sig_path)

            with open(sig_path, "rb") as f:
                signature = f.read()
            # The signature produced by the helper must verify with the app's updater.
            self.assertTrue(updater.verify_signature(payload, signature, pub_b64))
            # And the standalone pubkey command matches keygen's output.
            self.assertEqual(sign_release.pubkey(priv_path), pub_b64)

    def test_signature_rejects_tampered_manifest(self):
        sign_release = _load_script()
        with tempfile.TemporaryDirectory() as tmp:
            priv_path, pub_b64 = sign_release.keygen(tmp)
            manifest_path = os.path.join(tmp, "latest.json")
            with open(manifest_path, "wb") as f:
                f.write(b'{"version":"2.0.0"}')
            sig_path = os.path.join(tmp, "latest.json.sig")
            sign_release.sign(priv_path, manifest_path, sig_path)
            with open(sig_path, "rb") as f:
                signature = f.read()
            self.assertFalse(updater.verify_signature(b'{"version":"9.9.9"}', signature, pub_b64))


if __name__ == "__main__":
    unittest.main()
