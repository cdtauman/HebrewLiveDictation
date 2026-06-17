"""Local Whisper model management: registry, storage, RAM preflight.

faster-whisper downloads models from the Hugging Face hub on first use and
verifies download integrity itself (etag/revision). We therefore do NOT
re-implement per-file SHA-256 here (that would require brittle hardcoded hashes
per model revision); instead integrity can be pinned via a model ``revision``
(a HF commit SHA) in the registry below. This module focuses on what the app
adds on top: a known-model registry, a download location under %APPDATA%, a RAM
preflight, and availability/delete helpers for a future model-management UI.
"""

import logging
import os


logger = logging.getLogger("Models")

# Approximate peak RAM (MB) for int8 CPU inference and a human-readable download
# size. ``revision`` pins a Hugging Face commit SHA for reproducible/verified
# downloads (None = latest; pin before advertising a model as stable).
MODEL_REGISTRY = {
    "tiny":            {"approx_ram_mb": 700,  "size_label": "~75 MB",  "revision": None},
    "base":            {"approx_ram_mb": 900,  "size_label": "~145 MB", "revision": None},
    "small":           {"approx_ram_mb": 1600, "size_label": "~480 MB", "revision": None},
    "medium":          {"approx_ram_mb": 3000, "size_label": "~1.5 GB", "revision": None},
    "large-v3":        {"approx_ram_mb": 5000, "size_label": "~3.1 GB", "revision": None},
    "distil-large-v3": {"approx_ram_mb": 3000, "size_label": "~1.5 GB", "revision": None},
}

DEFAULT_MODEL = "small"


def known_models():
    return sorted(MODEL_REGISTRY)


def model_info(name):
    return MODEL_REGISTRY.get(name)


def model_revision(name):
    info = MODEL_REGISTRY.get(name) or {}
    return info.get("revision")


def default_storage_dir(config):
    """Resolve where local models are stored.

    Honors ``models.storage_dir`` if set, else ``%APPDATA%\\VoiceType\\models``
    (derived from the Config's directory when available).
    """
    configured = ""
    try:
        configured = (config.get("models.storage_dir", "") or "").strip()
    except Exception:
        configured = ""
    if configured:
        return configured
    base = getattr(config, "config_dir", None) or os.path.join(
        os.environ.get("APPDATA", os.path.expanduser("~")), "VoiceType"
    )
    return os.path.join(base, "models")


def _available_ram_mb():
    try:
        import psutil

        return int(psutil.virtual_memory().available / (1024 * 1024))
    except Exception as e:  # pragma: no cover - psutil availability guard
        logger.warning("psutil unavailable for RAM preflight: %s", e)
        return None


def ram_preflight(name):
    """Return (ok, message). If RAM cannot be assessed, allow (ok=True)."""
    info = MODEL_REGISTRY.get(name)
    required = info.get("approx_ram_mb") if info else None
    available = _available_ram_mb()
    if required is None or available is None:
        return True, ""
    if available < required:
        return False, (
            f"Not enough free memory for the '{name}' local model: "
            f"~{required} MB needed, {available} MB available. "
            f"Choose a smaller model or close other applications."
        )
    return True, ""


def _matches(entry: str, name: str) -> bool:
    flat = name.replace("/", "--")
    return flat in entry or name in entry


def is_downloaded(name, storage_dir) -> bool:
    if not storage_dir or not os.path.isdir(storage_dir):
        return False
    return any(_matches(entry, name) for entry in os.listdir(storage_dir))


def delete_model(name, storage_dir) -> bool:
    import shutil

    if not storage_dir or not os.path.isdir(storage_dir):
        return False
    removed = False
    for entry in list(os.listdir(storage_dir)):
        if _matches(entry, name):
            try:
                shutil.rmtree(os.path.join(storage_dir, entry))
                removed = True
            except Exception as e:
                logger.warning("Could not delete model dir %s: %s", entry, e)
    return removed
