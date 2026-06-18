"""Lightweight provider credential/key verification for the UI "Test" buttons.

Returns (ok: bool, message: str). Cloud checks do a minimal authenticated GET;
the HTTP call is injectable (``http_get``) so the logic is unit-testable without
network access.
"""

import logging


logger = logging.getLogger("STTVerify")


def verify(config, provider, *, http_get=None):
    if provider == "deepgram":
        return _verify_http_key(
            config, "deepgram", "https://api.deepgram.com/v1/projects",
            lambda k: {"Authorization": f"Token {k}"}, http_get,
        )
    if provider == "groq":
        return _verify_http_key(
            config, "groq", "https://api.groq.com/openai/v1/models",
            lambda k: {"Authorization": f"Bearer {k}"}, http_get,
        )
    if provider == "google_v2":
        return _verify_google(config)
    if provider == "whisper_local":
        return _verify_whisper(config)
    return False, f"Unknown provider: {provider}"


def _verify_http_key(config, name, url, headers_fn, http_get):
    from .. import secrets_store

    key = secrets_store.provider_api_key(config, name)
    if not key:
        return False, f"No {name} API key configured."
    if http_get is None:
        import requests

        http_get = requests.get
    try:
        resp = http_get(url, headers=headers_fn(key), timeout=15)
        code = int(getattr(resp, "status_code", 0) or 0)
    except Exception as e:
        return False, f"{name} connection failed: {e}"
    if 200 <= code < 300:
        return True, "OK"
    if code in (401, 403):
        return False, f"{name} key rejected (HTTP {code})."
    return False, f"{name} returned HTTP {code}."


def _verify_google(config):
    try:
        from ..google_stt_v2_stream import infer_project_id_from_credentials

        project = infer_project_id_from_credentials(config)
    except Exception as e:
        return False, f"Google credential check failed: {e}"
    if project:
        return True, f"Google project: {project}"
    return False, "Could not resolve Google project ID / credentials."


def _verify_whisper(config):
    from .. import models

    name = config.get("providers.whisper.model", "small")
    ok, message = models.ram_preflight(name)
    if not ok:
        return False, message
    try:
        import faster_whisper  # noqa: F401
    except Exception:
        return False, "faster-whisper is not installed."
    return True, f"Local model '{name}' is ready to load."
