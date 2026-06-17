from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

BLOCKED_ROOT_FILES = {
    "settings.json": "local user settings must live under %APPDATA%\\VoiceType",
    "hebrew_live_dictation.log": "logs must live under %APPDATA%\\VoiceType",
    "google_stt_stream.py": "Google STT V1 is not supported in v1 beta",
    "overlay.py": "legacy overlay was replaced by the Qt overlay",
    "tray_app.py": "legacy tray app was replaced by qt_app.py",
    "test_inject.py": "manual development harness is not part of the release",
}

BLOCKED_TREE_NAMES = {
    "__pycache__": "Python bytecode cache",
    ".pytest_cache": "test cache",
}

SKIP_DIRS = {
    ".git",
    ".venv",
    ".runenv",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "build",
    "dist",
    "__pycache__",
}

SKIP_ARTIFACT_PARENTS = {".git", ".venv", ".runenv", "build", "dist"}

TEXT_EXTENSIONS = {
    ".md",
    ".py",
    ".ps1",
    ".spec",
    ".toml",
    ".txt",
    ".json",
    ".yml",
    ".yaml",
}

SECRET_PATTERNS = (
    re.compile(r"C:[\\/]+Users[\\/]+cdtauman", re.IGNORECASE),
    re.compile(r"GOOGLE_APPLICATION_CREDENTIALS\s*=\s*['\"]?[A-Za-z]:", re.IGNORECASE),
    re.compile(r'"private_key"\s*:\s*"-----BEGIN PRIVATE KEY-----'),
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
    re.compile("מפתחות" + r"\s+" + "גוגל"),
)


def iter_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        relative_parts = set(path.relative_to(ROOT).parts)
        if relative_parts & SKIP_DIRS:
            continue
        if path.is_file():
            files.append(path)
    return files


def is_under_skipped_artifact_parent(path: Path) -> bool:
    parts = path.relative_to(ROOT).parts
    return any(part in SKIP_ARTIFACT_PARENTS for part in parts[:-1])


def main() -> int:
    failures: list[str] = []

    for name, reason in BLOCKED_ROOT_FILES.items():
        if (ROOT / name).exists():
            failures.append(f"{name}: {reason}")

    for name, reason in BLOCKED_TREE_NAMES.items():
        if any(path.name == name and not is_under_skipped_artifact_parent(path) for path in ROOT.rglob(name)):
            failures.append(f"{name}: {reason}")

    for path in iter_files():
        if path.suffix.lower() == ".log":
            failures.append(f"{path.relative_to(ROOT)}: log files are local runtime artifacts")
            continue
        if path.suffix.lower() == ".pyc":
            failures.append(f"{path.relative_to(ROOT)}: bytecode cache is not releasable")
            continue
        if path.suffix.lower() not in TEXT_EXTENSIONS:
            continue

        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                failures.append(f"{path.relative_to(ROOT)}: possible secret or developer-specific path")
                break

    if failures:
        print("Release audit failed:")
        for failure in sorted(set(failures)):
            print(f" - {failure}")
        return 1

    print("Release audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
