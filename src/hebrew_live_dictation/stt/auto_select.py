"""Smart Auto provider selection.

Picks the best *available* provider given configured credentials/enablement,
preferring quality-for-Hebrew then cost then offline:

    deepgram (best Hebrew realtime)  ->  google_v2 (strong Hebrew streaming)
    ->  groq (cheapest cloud)  ->  whisper_local (offline)  ->  google_v2 (default)

This is the heuristic baseline; it can later be refined by the benchmark/WER
suite (the "benchmark-driven" half of the product direction).
"""

import logging
import os


logger = logging.getLogger("STTAutoSelect")


def _has_key(config, provider):
    from .. import secrets_store

    return bool(secrets_store.provider_api_key(config, provider))


def _google_available(config):
    mode = config.get("google.credential_mode", "service_account_json")
    if mode == "adc":
        return True
    path = config.get("google.credentials_path", "") or config.get("google_credentials_path", "")
    if path:
        return True
    return "GOOGLE_APPLICATION_CREDENTIALS" in os.environ


def select_provider(config):
    if _has_key(config, "deepgram"):
        return "deepgram"
    if _google_available(config):
        return "google_v2"
    if _has_key(config, "groq"):
        return "groq"
    if config.get("providers.whisper.enabled", False):
        return "whisper_local"
    return "google_v2"
