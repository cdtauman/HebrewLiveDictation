import importlib.util
from pathlib import Path
import sys
import unittest


def _load_probe_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "google_stt_probe.py"
    spec = importlib.util.spec_from_file_location("google_stt_probe", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class GoogleSTTProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.probe = _load_probe_module()

    def test_chunks_stay_under_google_request_limit(self):
        chunks = list(self.probe._chunks(b"x" * 50000))

        self.assertEqual([len(chunk) for chunk in chunks], [12000, 12000, 12000, 12000, 2000])

    def test_matrix_contains_required_r3_cases(self):
        cases = self.probe._matrix_cases("_")
        tuples = {(case.model, case.location, case.language, case.recognizer) for case in cases}

        self.assertIn(("chirp_3", "eu", "iw-IL", "_"), tuples)
        self.assertIn(("chirp_3", "us", "iw-IL", "_"), tuples)
        self.assertIn(("latest_long", "eu", "iw-IL", "_"), tuples)
        self.assertIn(("latest_long", "us", "iw-IL", "_"), tuples)
        self.assertIn(("latest_long", "eu", "he-IL", "_"), tuples)
        self.assertIn(("latest_long", "us", "he-IL", "_"), tuples)

    def test_latest_long_probe_omits_automatic_punctuation(self):
        chirp = self.probe._recognition_config(self.probe.ProbeCase("eu", "chirp_3", "iw-IL", "_"), 16000)
        latest = self.probe._recognition_config(self.probe.ProbeCase("eu", "latest_long", "iw-IL", "_"), 16000)

        self.assertTrue(chirp.features.enable_automatic_punctuation)
        self.assertFalse(latest.features.enable_automatic_punctuation)


if __name__ == "__main__":
    unittest.main()
