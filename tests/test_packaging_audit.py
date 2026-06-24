import importlib.util
from pathlib import Path
import tempfile
import unittest


def _load_audit_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "packaging_audit.py"
    spec = importlib.util.spec_from_file_location("packaging_audit", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_release_audit_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "release_audit.py"
    spec = importlib.util.spec_from_file_location("release_audit", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PackagingAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = _load_audit_module()
        cls.release_audit = _load_release_audit_module()
        cls.root = Path(__file__).resolve().parents[1]

    def test_current_tree_passes_packaging_audit(self):
        self.assertEqual(self.audit.check_all(self.root), [])

    def test_release_audit_remains_runnable_after_local_build_outputs(self):
        self.assertEqual(self.release_audit.main(), 0)

    def test_engine_spec_requires_google_stack_collection(self):
        text = """
hiddenimports = ["hebrew_live_dictation.bridge.sidecar", "comtypes.client"]
REQUIRED_COLLECT_ALL = ("sounddevice", "docx")
OPTIONAL_COLLECT_ALL = ("av", "onnxruntime")
for _pkg in REQUIRED_COLLECT_ALL:
    pass
for _pkg in OPTIONAL_COLLECT_ALL:
    try:
        pass
    except Exception:
        pass
"""
        failures = self.audit.check_engine_spec_text(text)

        self.assertTrue(any("google.cloud.speech_v2" in failure for failure in failures))
        self.assertTrue(any("grpc" in failure for failure in failures))
        self.assertTrue(any("google.auth" in failure for failure in failures))

    def test_requirements_must_match_pyproject_build_deps(self):
        pyproject = """
[project]
dependencies = ["requests>=2.31"]

[project.optional-dependencies]
build = ["pyinstaller>=6.0"]
"""
        failures = self.audit.check_requirements_text(pyproject, "requests>=2.31\n")

        self.assertIn("requirements.txt: missing pyinstaller>=6.0", failures)

    def test_artifact_hygiene_rejects_private_audio_and_service_account_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "sample.wav").write_bytes(b"RIFF")
            fake_private_key = "-----BEGIN " + "PRIVATE KEY-----"
            (root / "creds.json").write_text(
                '{"type": "service_account", "private_key": "' + fake_private_key + '"}',
                encoding="utf-8",
            )

            failures = self.audit.check_artifact_hygiene(root)

        self.assertTrue(any("sample.wav" in failure for failure in failures))
        self.assertTrue(any("creds.json" in failure for failure in failures))


if __name__ == "__main__":
    unittest.main()
