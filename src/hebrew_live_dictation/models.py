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


# Authoritative completion marker. A model is "ready" only when this sentinel is present
# inside its cache dir; download_model writes it as the LAST step, after the downloader has
# returned successfully. Its presence means a download WE performed (the explicit download
# flow) finished completely — an interrupted/partial download never leaves it behind. Models
# fetched by faster-whisper's own first-use auto-download have NO marker and are deliberately
# NOT treated as ready (Option A): offline acquisition must go through download_model, so the
# UI state, progress/error/retry handling, and readiness all stay consistent.
COMPLETE_MARKER = ".vt_complete"

# A complete, *usable* faster-whisper (CTranslate2) model needs the weights AND the
# accompanying config/vocabulary so the runtime can actually load it. We require all three
# signals — the completion marker is necessary but NOT sufficient on its own.
_WEIGHTS_FILE = "model.bin"          # the CT2 weights; partial HF downloads leave *.incomplete
_MIN_WEIGHTS_BYTES = 1024            # guard against zero/placeholder files
_AUX_FILES = {"config.json", "tokenizer.json", "vocabulary.txt", "vocabulary.json"}


def download_model(config, name=None, downloader=None):
    """Download a model into the storage dir without loading it into RAM.

    Uses faster-whisper's downloader (Hugging Face); ``downloader`` is injectable
    for tests. On success, writes the COMPLETE_MARKER inside the model dir so readiness
    can be reported truthfully. Returns the local model path.
    """
    name = name or config.get("providers.whisper.model", DEFAULT_MODEL)
    storage_dir = default_storage_dir(config)
    try:
        os.makedirs(storage_dir, exist_ok=True)
    except Exception:
        pass
    if downloader is None:
        from faster_whisper import download_model as downloader  # type: ignore
    path = downloader(name, cache_dir=storage_dir, revision=model_revision(name))
    _mark_complete(path)
    return path


def _mark_complete(model_path) -> None:
    """Stamp a completed download. Best-effort: failure to write the marker only means a
    later readiness check falls back to validating the weights file."""
    try:
        if model_path and os.path.isdir(model_path):
            with open(os.path.join(model_path, COMPLETE_MARKER), "w", encoding="utf-8") as f:
                f.write("ok")
    except Exception as e:  # pragma: no cover - marker is best-effort
        logger.warning("Could not write model completion marker in %s: %s", model_path, e)


def model_status(config, name=None):
    """Return {name, downloaded, path} for the UI. ``downloaded`` is the TRUTHFUL completion
    signal (see is_downloaded), never merely "a matching directory exists"."""
    name = name or config.get("providers.whisper.model", DEFAULT_MODEL)
    storage_dir = default_storage_dir(config)
    return {"name": name, "downloaded": is_downloaded(name, storage_dir), "path": storage_dir}


def is_downloaded(name, storage_dir) -> bool:
    """Whether a COMPLETE, USABLE model is present — not just a matching cache entry or a
    stray marker.

    A model is ready only if a matching cache dir contains ALL of:
      * our authoritative COMPLETE_MARKER (a download we finished), AND
      * a non-trivially-sized ``model.bin`` (real weights, not a zero/placeholder), AND
      * at least one config/vocabulary file the runtime needs to load it.

    A bare directory, a marker with no weights, an interrupted download (only
    ``*.incomplete`` blobs), or a zero-byte weights file all report False.
    """
    if not storage_dir or not os.path.isdir(storage_dir):
        return False
    for entry in os.listdir(storage_dir):
        if not _matches(entry, name):
            continue
        if _entry_is_complete(os.path.join(storage_dir, entry)):
            return True
    return False


def _entry_is_complete(root) -> bool:
    """True only if a matched cache entry holds a finished AND loadable model: our completion
    marker, real weights, and the supporting config/vocabulary. The marker alone is never
    enough."""
    try:
        if not os.path.isdir(root):
            return False
        has_marker = has_weights = has_aux = False
        for dirpath, _dirs, files in os.walk(root):
            fileset = set(files)
            if COMPLETE_MARKER in fileset:
                has_marker = True
            if _WEIGHTS_FILE in fileset:
                try:
                    if os.path.getsize(os.path.join(dirpath, _WEIGHTS_FILE)) >= _MIN_WEIGHTS_BYTES:
                        has_weights = True
                except OSError:
                    pass
            if fileset & _AUX_FILES:
                has_aux = True
        return has_marker and has_weights and has_aux
    except Exception:
        return False


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
