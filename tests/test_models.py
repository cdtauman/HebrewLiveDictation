import os
import tempfile
import unittest

from hebrew_live_dictation import models
from hebrew_live_dictation.config import Config


def _write_weights(model_dir, size=2048):
    """Write a non-trivial model.bin (weights only — NOT a complete model on its own)."""
    with open(os.path.join(model_dir, "model.bin"), "wb") as f:
        f.write(b"\x00" * size)


def _write_complete_model(model_dir, size=2048):
    """Write a complete, loadable layout: real weights + a config file + the completion
    marker — the three signals readiness now requires."""
    os.makedirs(model_dir, exist_ok=True)
    _write_weights(model_dir, size)
    with open(os.path.join(model_dir, "config.json"), "w") as f:
        f.write("{}")
    with open(os.path.join(model_dir, models.COMPLETE_MARKER), "w") as f:
        f.write("ok")


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
            self.assertEqual(status["state"], "missing")
            self.assertEqual(status["reason"], "not_found")
            self.assertEqual(status["missing"], [])
            self.assertEqual(status["path"], os.path.join(tmp, "models"))
            # A bare matching directory is NOT downloaded — only a complete model is.
            model_dir = os.path.join(tmp, "models", "models--small")
            os.makedirs(model_dir)
            partial = models.model_status(config, "small")
            self.assertFalse(partial["downloaded"])
            self.assertEqual(partial["state"], "incomplete")
            self.assertEqual(partial["reason"], "incomplete")
            self.assertEqual(
                partial["missing"],
                ["completion_marker", "model_weights", "model_config"],
            )
            self.assertEqual(partial["modelPath"], model_dir)
            _write_complete_model(model_dir)
            ready = models.model_status(config, "small")
            self.assertTrue(ready["downloaded"])
            self.assertEqual(ready["state"], "ready")
            self.assertEqual(ready["reason"], "complete")
            self.assertEqual(ready["missing"], [])

    def test_is_downloaded_requires_marker_weights_and_aux(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(models.is_downloaded("small", tmp))               # nothing
            model_dir = os.path.join(tmp, "models--Systran--faster-whisper-small")
            os.makedirs(model_dir)
            self.assertFalse(models.is_downloaded("small", tmp))               # bare dir
            # Partial HF download: only an *.incomplete blob -> not ready.
            with open(os.path.join(model_dir, "model.bin.incomplete"), "wb") as f:
                f.write(b"\x00" * 4096)
            self.assertFalse(models.is_downloaded("small", tmp))
            # Weights + aux but NO completion marker -> not ready (interrupted before commit).
            _write_weights(model_dir)
            with open(os.path.join(model_dir, "config.json"), "w") as f:
                f.write("{}")
            self.assertFalse(models.is_downloaded("small", tmp))
            # Add the marker -> now complete and usable -> ready.
            with open(os.path.join(model_dir, models.COMPLETE_MARKER), "w") as f:
                f.write("ok")
            self.assertTrue(models.is_downloaded("small", tmp))
            self.assertTrue(models.delete_model("small", tmp))
            self.assertFalse(os.path.isdir(model_dir))

    def test_marker_alone_is_not_ready(self):
        # The authoritative marker is necessary but NOT sufficient: without real weights and
        # config, a marker-only cache must report not-ready.
        with tempfile.TemporaryDirectory() as tmp:
            model_dir = os.path.join(tmp, "models--small")
            os.makedirs(model_dir)
            with open(os.path.join(model_dir, models.COMPLETE_MARKER), "w") as f:
                f.write("ok")
            self.assertFalse(models.is_downloaded("small", tmp))
            # Even with the marker, zero-byte weights is corrupt -> still not ready.
            open(os.path.join(model_dir, "model.bin"), "wb").close()
            with open(os.path.join(model_dir, "config.json"), "w") as f:
                f.write("{}")
            self.assertFalse(models.is_downloaded("small", tmp))

    def test_download_model_writes_marker_but_files_still_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            config.update({"providers.whisper.model": "small"})

            def empty_downloader(name, cache_dir=None, revision=None):
                path = os.path.join(cache_dir, f"models--{name}")
                os.makedirs(path, exist_ok=True)   # "succeeds" but writes no real model files
                return path

            models.download_model(config, downloader=empty_downloader)
            # Marker was written, but with no weights/config the model is NOT usable.
            self.assertTrue(os.path.exists(
                os.path.join(tmp, "models", "models--small", models.COMPLETE_MARKER)))
            self.assertFalse(models.model_status(config, "small")["downloaded"])

            def real_downloader(name, cache_dir=None, revision=None):
                path = os.path.join(cache_dir, f"models--{name}")
                os.makedirs(path, exist_ok=True)
                _write_weights(path)                       # real weights
                with open(os.path.join(path, "config.json"), "w") as f:
                    f.write("{}")                          # + config
                return path                                # download_model adds the marker

            models.download_model(config, downloader=real_downloader)
            self.assertTrue(models.model_status(config, "small")["downloaded"])

    def test_inspect_model_prefers_ready_cache_over_partial_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            partial_dir = os.path.join(tmp, "models--small-partial")
            ready_dir = os.path.join(tmp, "models--small-ready")
            os.makedirs(partial_dir)
            _write_weights(partial_dir)
            _write_complete_model(ready_dir)

            status = models.inspect_model("small", tmp)
            self.assertTrue(status["downloaded"])
            self.assertEqual(status["state"], "ready")
            self.assertEqual(status["modelPath"], ready_dir)


if __name__ == "__main__":
    unittest.main()
