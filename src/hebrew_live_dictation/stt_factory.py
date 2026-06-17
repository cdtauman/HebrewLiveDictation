import logging


logger = logging.getLogger("STTFactory")

DEFAULT_PROVIDER = "google_v2"


def create_stt_stream(config, on_event_callback):
    """Create the active STT stream for the configured provider.

    Dispatches on ``stt.provider`` (default ``google_v2``) via the provider
    registry. Unknown providers fall back to the default so a bad config can
    never brick dictation. Signature is unchanged from the legacy factory.
    """
    api_version = config.get("google.api_version", "v2")
    if api_version != "v2":
        logger.warning(
            "Ignoring unsupported Google STT api_version=%s. Hebrew Live Dictation v1 uses V2 only.",
            api_version,
        )

    from .stt.registry import REGISTRY

    provider = config.get("stt.provider", DEFAULT_PROVIDER) or DEFAULT_PROVIDER

    # Local Whisper is gated by an explicit enable flag (the rollback lever):
    # if selected but disabled, fall back to the default cloud provider.
    if provider == "whisper_local" and not config.get("providers.whisper.enabled", False):
        logger.warning(
            "stt.provider=whisper_local but providers.whisper.enabled is false; falling back to %r.",
            DEFAULT_PROVIDER,
        )
        provider = DEFAULT_PROVIDER

    if not REGISTRY.is_registered(provider):
        logger.warning(
            "Unknown stt.provider=%r; falling back to %r. Known providers: %s",
            provider,
            DEFAULT_PROVIDER,
            REGISTRY.known(),
        )
        provider = DEFAULT_PROVIDER

    logger.info("Creating STT stream via provider %r.", provider)
    return REGISTRY.create(provider, config, on_event_callback)
