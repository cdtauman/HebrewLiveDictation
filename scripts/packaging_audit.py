from __future__ import annotations

import ast
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_ENGINE_COLLECT_ALL = {
    "faster_whisper",
    "ctranslate2",
    "tokenizers",
    "huggingface_hub",
    "sounddevice",
    "docx",
    "google.cloud.speech_v2",
    "google.api_core",
    "google.auth",
    "google.protobuf",
    "grpc",
    "proto",
    "keyring",
    "websockets",
}

REQUIRED_ENGINE_HIDDEN_IMPORTS = {
    "hebrew_live_dictation.bridge.sidecar",
    "hebrew_live_dictation.stt.registry",
    "hebrew_live_dictation.stt.whisper_local",
    "hebrew_live_dictation.stt.deepgram",
    "hebrew_live_dictation.stt.groq",
    "hebrew_live_dictation.stt.fallback",
    "hebrew_live_dictation.stt.auto_select",
    "hebrew_live_dictation.google_stt_v2_stream",
    "google.cloud.speech_v2",
    "google.cloud.speech_v2.types.cloud_speech",
    "google.protobuf.duration_pb2",
    "comtypes.client",
    "uiautomation",
    "keyring.backends.Windows",
    "cryptography.hazmat.primitives.asymmetric.ed25519",
    "websockets.sync.client",
}

REQUIRED_OPTIONAL_COLLECT_ALL = {"av", "onnxruntime"}

SKIP_DIRS = {
    ".git",
    ".claude",
    ".venv",
    ".runenv",
    ".pytest_cache",
    "bin",
    "build",
    "dist",
    "obj",
    "__pycache__",
}
PRIVATE_AUDIO_SUFFIXES = {".wav", ".flac", ".mp3", ".m4a", ".ogg"}


def _read(root: Path, relative: str) -> str:
    return (root / relative).read_text(encoding="utf-8")


def _string_sequence_assignment(text: str, name: str) -> set[str]:
    tree = ast.parse(text)
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            continue
        if not isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):
            return set()
        values: set[str] = set()
        for item in node.value.elts:
            if isinstance(item, ast.Constant) and isinstance(item.value, str):
                values.add(item.value)
        return values
    return set()


def _missing(label: str, actual: set[str], required: set[str]) -> list[str]:
    missing = sorted(required - actual)
    return [f"{label}: missing {item}" for item in missing]


def check_engine_spec_text(text: str) -> list[str]:
    failures: list[str] = []
    required = _string_sequence_assignment(text, "REQUIRED_COLLECT_ALL")
    optional = _string_sequence_assignment(text, "OPTIONAL_COLLECT_ALL")
    hidden = _string_sequence_assignment(text, "hiddenimports")

    failures.extend(_missing("packaging/engine.spec REQUIRED_COLLECT_ALL", required, REQUIRED_ENGINE_COLLECT_ALL))
    failures.extend(_missing("packaging/engine.spec OPTIONAL_COLLECT_ALL", optional, REQUIRED_OPTIONAL_COLLECT_ALL))
    failures.extend(_missing("packaging/engine.spec hiddenimports", hidden, REQUIRED_ENGINE_HIDDEN_IMPORTS))

    if "for _pkg in REQUIRED_COLLECT_ALL:" not in text:
        failures.append("packaging/engine.spec: required collect_all loop must be fail-fast and explicit")
    if "for _pkg in OPTIONAL_COLLECT_ALL:" not in text or "except Exception:" not in text:
        failures.append("packaging/engine.spec: optional collect_all loop must be visibly best-effort")
    return failures


def check_requirements_text(pyproject_text: str, requirements_text: str) -> list[str]:
    pyproject = tomllib.loads(pyproject_text)
    project = pyproject.get("project", {})
    expected = set(project.get("dependencies", []))
    optional = project.get("optional-dependencies", {})
    expected.update(optional.get("build", []))
    actual = {
        line.strip()
        for line in requirements_text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    failures: list[str] = []
    failures.extend(_missing("requirements.txt", actual, expected))
    extras = sorted(actual - expected)
    failures.extend(f"requirements.txt: extra dependency not declared in pyproject.toml: {item}" for item in extras)
    return failures


def check_packaging_script_text(relative: str, text: str) -> list[str]:
    required_by_file = {
        "packaging/build_engine.ps1": (
            "VoiceType.exe",
            "Refusing to delete",
            "not a recognized engine staging dir",
            "PyInstaller failed",
        ),
        "packaging/build_beta.ps1": (
            "READ-ME-BETA.txt",
            "Refusing to delete",
            "not a prior beta layout",
            "VoiceType.pri",
            "UNSIGNED LOCAL BETA",
            "Windows protected your PC",
        ),
        "packaging/verify_beta.ps1": (
            "vt-beta-verify",
            "--expect-packaged-engine",
            "engine.exe.off",
            "winui_runtime_report.positive.txt",
            "winui_runtime_report.negative.txt",
            "ADVISORY",
        ),
    }
    failures: list[str] = []
    for needle in required_by_file.get(relative, ()):
        if needle not in text:
            failures.append(f"{relative}: missing guard or proof marker {needle!r}")
    return failures


def check_workflow_text(text: str) -> list[str]:
    required = (
        "permissions:\n  contents: read",
        "Packaging/security audit",
        "python scripts/packaging_audit.py",
        "PYTHONPATH: src",
        "python -m unittest discover -s tests",
        "./packaging/build_beta.ps1",
        "./packaging/verify_beta.ps1",
        "VoiceType-winui-beta-unsigned",
        "retention-days: 14",
        "if: startsWith(github.ref, 'refs/tags/beta-v')",
        "UNSIGNED",
    )
    return [f".github/workflows/winui-beta.yml: missing {needle!r}" for needle in required if needle not in text]


def check_artifact_hygiene(root: Path) -> list[str]:
    failures: list[str] = []
    for path in root.rglob("*"):
        if set(path.relative_to(root).parts) & SKIP_DIRS:
            continue
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if path.suffix.lower() in PRIVATE_AUDIO_SUFFIXES:
            failures.append(f"{rel}: private audio samples must not be committed")
            continue
        if path.suffix.lower() == ".json":
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if '"type"' in text and "service_account" in text and '"private_key"' in text:
                failures.append(f"{rel}: service-account credential JSON must not be committed")
    return failures


def check_all(root: Path = ROOT) -> list[str]:
    failures: list[str] = []
    failures.extend(check_engine_spec_text(_read(root, "packaging/engine.spec")))
    failures.extend(check_requirements_text(_read(root, "pyproject.toml"), _read(root, "requirements.txt")))
    for relative in ("packaging/build_engine.ps1", "packaging/build_beta.ps1", "packaging/verify_beta.ps1"):
        failures.extend(check_packaging_script_text(relative, _read(root, relative)))
    failures.extend(check_workflow_text(_read(root, ".github/workflows/winui-beta.yml")))
    failures.extend(check_artifact_hygiene(root))
    return failures


def main(argv: list[str] | None = None) -> int:
    root = Path(argv[0]).resolve() if argv else ROOT
    failures = check_all(root)
    if failures:
        print("Packaging audit failed:")
        for failure in sorted(set(failures)):
            print(f" - {failure}")
        return 1
    print("Packaging audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
