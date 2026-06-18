import logging

from .base import ProviderCapabilities


logger = logging.getLogger("STTRegistry")


class ProviderRegistry:
    """Maps provider name -> (factory, capabilities).

    Factories are lazy callables ``(config, on_event_callback) -> SpeechClient``
    that import any heavy dependency only when invoked, mirroring the original
    ``stt_factory`` behaviour (keeps google-cloud-speech off module-import time).
    """

    def __init__(self):
        self._factories = {}
        self._capabilities = {}

    def register(self, name, factory, capabilities):
        self._factories[name] = factory
        self._capabilities[name] = capabilities

    def is_registered(self, name):
        return name in self._factories

    def known(self):
        return sorted(self._factories)

    def capabilities(self, name):
        if name not in self._capabilities:
            raise ValueError(
                f"Unknown STT provider: {name!r}. Known providers: {self.known()}"
            )
        return self._capabilities[name]

    def create(self, name, config, on_event_callback=None):
        if name not in self._factories:
            raise ValueError(
                f"Unknown STT provider: {name!r}. Known providers: {self.known()}"
            )
        return self._factories[name](config, on_event_callback)


def _google_v2_factory(config, on_event_callback):
    # Lazy import keeps the google client out of module-import time.
    from ..google_stt_v2_stream import GoogleSTTV2Stream

    return GoogleSTTV2Stream(config, on_event_callback=on_event_callback)


def _whisper_local_factory(config, on_event_callback):
    # Lazy import keeps faster-whisper/numpy out of module-import time.
    from .whisper_local import WhisperLocalStream

    return WhisperLocalStream(config, on_event_callback=on_event_callback)


def _deepgram_factory(config, on_event_callback):
    from .deepgram import DeepgramStream

    return DeepgramStream(config, on_event_callback=on_event_callback)


def _groq_factory(config, on_event_callback):
    from .groq import GroqStream

    return GroqStream(config, on_event_callback=on_event_callback)


# App-wide registry. Providers register here as they are added in later phases.
REGISTRY = ProviderRegistry()
REGISTRY.register(
    "google_v2",
    _google_v2_factory,
    ProviderCapabilities(
        name="google_v2",
        streaming=True,
        batch=False,
        interim=True,
        offline=False,
        fallback_target=False,
        needs_credentials=True,
    ),
)
REGISTRY.register(
    "whisper_local",
    _whisper_local_factory,
    ProviderCapabilities(
        name="whisper_local",
        streaming=False,
        batch=True,
        interim=False,
        offline=True,
        fallback_target=True,
        needs_credentials=False,
    ),
)
REGISTRY.register(
    "deepgram",
    _deepgram_factory,
    ProviderCapabilities(
        name="deepgram",
        streaming=True,
        batch=False,
        interim=True,
        offline=False,
        fallback_target=False,
        needs_credentials=True,
    ),
)
REGISTRY.register(
    "groq",
    _groq_factory,
    ProviderCapabilities(
        name="groq",
        streaming=False,
        batch=True,
        interim=False,
        offline=False,
        fallback_target=False,
        needs_credentials=True,
    ),
)
