import os
import tempfile
import unittest

from hebrew_live_dictation import models
from hebrew_live_dictation.config import Config


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

    def test_is_downloaded_and_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(models.is_downloaded("small", tmp))
            model_dir = os.path.join(tmp, "models--Systran--faster-whisper-small")
            os.makedirs(model_dir)
            with open(os.path.join(model_dir, "model.bin"), "w") as f:
                f.write("x")
            # Heuristic matches on the bare name token too.
            self.assertTrue(models.is_downloaded("small", tmp))
            self.assertTrue(models.delete_model("small", tmp))
            self.assertFalse(os.path.isdir(model_dir))


if __name__ == "__main__":
    unittest.main()
