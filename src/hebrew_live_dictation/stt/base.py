import logging
from dataclasses import dataclass
from enum import Enum


logger = logging.getLogger("STTProvider")


class STTErrorKind(str, Enum):
    """Classifies provider failures so orchestration can react uniformly.

    TERMINAL  -> do not retry this provider for the current utterance; the
                 utterance is eligible for fallback to another provider
                 (auth/quota/unsupported configuration).
    RETRYABLE -> transient; the provider may restart its own stream
                 (network blip, timeout, empty response).

    Reserved for Phase D (AutoFallback). Providers may attach this to ``error``
    events via the ``code`` field; nothing consumes it yet.
    """

    TERMINAL = "terminal"
    RETRYABLE = "retryable"


@dataclass(frozen=True)
class ProviderCapabilities:
    """Static description of what a speech provider can do.

    Lets the controller/registry branch on capability instead of provider name
    and lets AutoFallback decide which providers are eligible local targets.
    """

    name: str
    streaming: bool = False
    batch: bool = False
    interim: bool = False
    offline: bool = False
    fallback_target: bool = False
    needs_credentials: bool = True


class SpeechClientBase:
    """Shared base for speech providers.

    Conforms to ``interfaces.SpeechClient`` (start/stop/restart_stream) and adds
    a uniform ``cancel`` plus an ``on_event_callback`` emit helper.

    NOTE (Phase A): ``GoogleSTTV2Stream`` is intentionally NOT migrated onto this
    base yet (zero-behaviour-change guarantee). It is registered as-is and its
    capabilities are declared in the registry. Future providers subclass this.
    """

    capabilities: ProviderCapabilities = ProviderCapabilities(name="base")

    def __init__(self, config, on_event_callback=None):
        self.config = config
        self.on_event_callback = on_event_callback
        self.active = False

    def start(self, audio_queue):
        raise NotImplementedError

    def stop(self):
        raise NotImplementedError

    def restart_stream(self):
        # Optional; no-op for providers that cannot rotate a stream.
        return None

    def cancel(self):
        # Uniform cancellation; defaults to stop() for providers without a
        # distinct cancel path.
        self.stop()

    def _emit_event(self, event):
        if self.on_event_callback:
            try:
                self.on_event_callback(event)
            except Exception as e:  # pragma: no cover - callback owns its errors
                logger.error("Error in STT event callback: %s", e)
