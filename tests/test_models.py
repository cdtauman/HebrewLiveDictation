import os
import tempfile
import unittest

from hebrew_live_dictation import models
from hebrew_live_dictation.config import Config


def _write_weights(model_dir, size=2048):
    """Write a non-trivial model.bin so the dir looks like a complete model."""
    with open(os.path.join(model_dir, "model.bin"), "wb") as f:
        f.write(b"\x00" * size)


class ModelsTests(unittest.TestCase):
    def test_known_models_include_defaults(self):
        names = models.known_models()
        self.assertIn("small", names)
        self.assertIn("large-v3", names)
        self.assertEqual(models.DEFAULT_MODEL, "small")

    def test_default_storage_dir_uses_config_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            storage = models.default_storage_dir(config)
            self.assertEqual(storage, os.path.join(tmp, "models"))

    def test_default_storage_dir_honors_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            config.update({"models.storage_dir": "D:/custom/models"})
            self.assertEqual(models.default_storage_dir(config), "D:/custom/models")

    def test_ram_preflight_blocks_when_insufficient(self):
        original = models._available_ram_mb
        models._available_ram_mb = lambda: 256
        try:
            ok, msg = models.ram_preflight("large-v3")
            self.assertFalse(ok)
            self.assertIn("Not enough free memory", msg)
        finally:
            models._available_ram_mb = original

    def test_ram_preflight_allows_when_sufficient(self):
        original = models._available_ram_mb
        models._available_ram_mb = lambda: 64000
        try:
            ok, msg = models.ram_preflight("small")
            self.assertTrue(ok)
            self.assertEqual(msg, "")
        finally:
            models._available_ram_mb = original

    def test_ram_preflight_allows_when_unassessable(self):
        original = models._available_ram_mb
        models._available_ram_mb = lambda: None
        try:
            ok, msg = models.ram_preflight("small")
            self.assertTrue(ok)
        finally:
            models._available_ram_mb = original

    def test_download_model_uses_injected_downloader(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            config.update({"providers.whisper.model": "small"})
            calls = {}

            def fake_downloader(name, cache_dir=None, revision=None):
                calls["name"] = name
                calls["cache_dir"] = cache_dir
                return os.path.join(cache_dir, f"models--{name}")

            path = models.download_model(config, downloader=fake_downloader)
            self.assertEqual(calls["name"], "small")
            self.assertEqual(calls["cache_dir"], os.path.join(tmp, "models"))
            self.assertIn("small", path)

    def test_model_status_reports_downloaded_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            status = models.model_status(config, "small")
            self.assertEqual(status["name"], "small")
            self.assertFalse(status["downloaded"])
            self.assertEqual(status["path"], os.path.join(tmp, "models"))
            # A bare matching directory is NOT downloaded — only a complete model is.
            os.makedirs(os.path.join(tmp, "models", "models--small"))
            self.assertFalse(models.model_status(config, "small")["downloaded"])
            _write_weights(os.path.join(tmp, "models", "models--small"))
            self.assertTrue(models.model_status(config, "small")["downloaded"])

    def test_is_downloaded_requires_complete_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(models.is_downloaded("small", tmp))               # nothing
            model_dir = os.path.join(tmp, "models--Systran--faster-whisper-small")
            os.makedirs(model_dir)
            self.assertFalse(models.is_downloaded("small", tmp))               # bare dir
            # Partial HF download: only an *.incomplete blob, no real weights -> not ready.
            with open(os.path.join(model_dir, "model.bin.incomplete"), "wb") as f:
                f.write(b"\x00" * 4096)
            self.assertFalse(models.is_downloaded("small", tmp))
            # Corrupt/zero-byte weights -> not ready.
            open(os.path.join(model_dir, "model.bin"), "wb").close()
            self.assertFalse(models.is_downloaded("small", tmp))
            # Real (non-trivial) weights -> ready.
            _write_weights(model_dir)
            self.assertTrue(models.is_downloaded("small", tmp))
            self.assertTrue(models.delete_model("small", tmp))
            self.assertFalse(os.path.isdir(model_dir))

    def test_completion_marker_alone_means_ready(self):
        # A model fetched by our download_model leaves the authoritative marker even before we
        # second-guess the weights layout; the marker alone makes it ready.
        with tempfile.TemporaryDirectory() as tmp:
            model_dir = os.path.join(tmp, "models--small")
            os.makedirs(model_dir)
            self.assertFalse(models.is_downloaded("small", tmp))
            with open(os.path.join(model_dir, models.COMPLETE_MARKER), "w") as f:
                f.write("ok")
            self.assertTrue(models.is_downloaded("small", tmp))

    def test_download_model_writes_completion_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            config.update({"providers.whisper.model": "small"})

            def fake_downloader(name, cache_dir=None, revision=None):
                path = os.path.join(cache_dir, f"models--{name}")
                os.makedirs(path, exist_ok=True)   # weights not written, but download "succeeded"
                return path

            self.assertFalse(models.model_status(config, "small")["downloaded"])
            models.download_model(config, downloader=fake_downloader)
            # Marker written -> truthfully ready even though the fake wrote no weights.
            self.assertTrue(models.model_status(config, "small")["downloaded"])


if __name__ == "__main__":
    unittest.main()
