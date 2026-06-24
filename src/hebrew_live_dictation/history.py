"""Transcription history store (append-only JSONL under the config dir).

Each finalized session is one JSON line: {ts, target, text}. Privacy: history is
opt-out via ``history.enabled`` and capped at ``history.max_entries``. Stored
under %APPDATA%\\VoiceType, not in the repo.
"""

import hashlib
import json
import logging
import os
import time
import uuid


logger = logging.getLogger("History")


def _path(config):
    base = getattr(config, "config_dir", None) or os.path.join(
        os.environ.get("APPDATA", os.path.expanduser("~")), "VoiceType"
    )
    return os.path.join(base, "history.jsonl")


def entry_id(entry):
    """Return a stable, non-secret identifier for a history entry.

    New entries are written with a UUID. Older JSONL rows do not have one, so we
    derive a deterministic hash from the local row contents for delete/search UI.
    """
    if not isinstance(entry, dict):
        return ""
    existing = str(entry.get("id", "") or "").strip()
    if existing:
        return existing
    text = str(entry.get("text", "") or "")
    target = str(entry.get("target", "") or "")
    ts = entry.get("ts", "")
    raw = f"{ts}\n{target}\n{text}".encode("utf-8", errors="replace")
    return hashlib.sha256(raw).hexdigest()[:24]


def normalize_entry(entry):
    if not isinstance(entry, dict):
        return None
    text = str(entry.get("text", "") or "").strip()
    if not text:
        return None
    ts = entry.get("ts", 0)
    return {
        "id": entry_id(entry),
        "ts": ts if isinstance(ts, (int, float)) else 0,
        "target": str(entry.get("target", "") or ""),
        "text": text,
        "chars": len(text),
    }


def append(config, text, target=None, when=None):
    if not text or not text.strip():
        return False
    if not config.get("history.enabled", True):
        return False
    entry = {
        "id": uuid.uuid4().hex,
        "ts": when if when is not None else time.time(),
        "target": target or "",
        "text": text.strip(),
    }
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


def delete(config, delete_id):
    delete_id = str(delete_id or "").strip()
    if not delete_id:
        return False
    path = _path(config)
    if not os.path.exists(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        kept = []
        deleted = False
        for line in lines:
            stripped = line.strip()
            if not stripped:
                kept.append(line)
                continue
            try:
                entry = json.loads(stripped)
            except ValueError:
                kept.append(line)
                continue
            if not deleted and entry_id(entry) == delete_id:
                deleted = True
                continue
            kept.append(line)
        if not deleted:
            return False
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.writelines(kept)
        os.replace(tmp_path, path)
        return True
    except Exception as e:
        logger.warning("Failed to delete history entry: %s", e)
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
