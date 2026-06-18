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

    mode = config.get("stt.mode", "api") or "api"
    provider = config.get("stt.provider", DEFAULT_PROVIDER) or DEFAULT_PROVIDER

    # stt.mode selects the strategy:
    #   api           -> use stt.provider as configured
    #   local         -> force the offline local provider
    #   auto_fallback -> primary = stt.provider, fall back to local on failure
    if mode == "local":
        provider = "whisper_local"

    whisper_enabled = bool(config.get("providers.whisper.enabled", False))

    # Local Whisper is gated by an explicit enable flag (the rollback lever):
    # if selected but disabled, fall back to the default cloud provider.
    if provider == "whisper_local" and not whisper_enabled:
        logger.warning(
            "Local Whisper selected (mode=%r) but providers.whisper.enabled is false; falling back to %r.",
            mode,
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

    if mode == "auto_fallback" and provider != "whisper_local" and whisper_enabled:
        from .stt.fallback import FallbackSpeechClient

        logger.info("Creating AutoFallback STT stream: primary=%r -> local=whisper_local.", provider)
        return FallbackSpeechClient(
            config, on_event_callback, primary_name=provider, local_name="whisper_local"
        )

    logger.info("Creating STT stream via provider %r (mode=%r).", provider, mode)
    return REGISTRY.create(provider, config, on_event_callback)
