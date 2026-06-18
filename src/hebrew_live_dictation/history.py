"""Transcription history store (append-only JSONL under the config dir).

Each finalized session is one JSON line: {ts, target, text}. Privacy: history is
opt-out via ``history.enabled`` and capped at ``history.max_entries``. Stored
under %APPDATA%\\VoiceType, not in the repo.
"""

import json
import logging
import os
import time


logger = logging.getLogger("History")


def _path(config):
    base = getattr(config, "config_dir", None) or os.path.join(
        os.environ.get("APPDATA", os.path.expanduser("~")), "VoiceType"
    )
    return os.path.join(base, "history.jsonl")


def append(config, text, target=None, when=None):
    if not text or not text.strip():
        return False
    if not config.get("history.enabled", True):
        return False
    entry = {"ts": when if when is not None else time.time(), "target": target or "", "text": text.strip()}
    path = _path(config)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        _trim(config, path)
        return True
    except Exception as e:
        logger.warning("Failed to append history: %s", e)
        return False


def load(config, limit=None):
    path = _path(config)
    if not os.path.exists(path):
        return []
    entries = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except ValueError:
                    continue
    except Exception as e:
        logger.warning("Failed to read history: %s", e)
        return []
    return entries[-limit:] if limit else entries


def clear(config):
    path = _path(config)
    try:
        if os.path.exists(path):
            os.remove(path)
        return True
    except Exception as e:
        logger.warning("Failed to clear history: %s", e)
        return False


def _trim(config, path):
    try:
        max_entries = int(config.get("history.max_entries", 500) or 500)
    except (TypeError, ValueError):
        max_entries = 500
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) > max_entries:
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(lines[-max_entries:])
    except Exception:
        pass
