import logging


logger = logging.getLogger("STTFactory")


def create_stt_stream(config, on_event_callback):
    api_version = config.get("google.api_version", "v2")
    if api_version != "v2":
        logger.warning("Ignoring unsupported Google STT api_version=%s. Hebrew Live Dictation v1 uses V2 only.", api_version)

    from .google_stt_v2_stream import GoogleSTTV2Stream

    logger.info("Using Google STT V2 stream.")
    return GoogleSTTV2Stream(config, on_event_callback=on_event_callback)
