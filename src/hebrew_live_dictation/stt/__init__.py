"""Speech-to-text provider abstraction.

Phase A introduces a provider registry and a shared ``SpeechClientBase`` without
changing existing behaviour: ``google_v2`` (the established Google STT V2 / Chirp 3
stream) remains the default provider. Additional providers (local Whisper,
Deepgram, Groq) and AutoFallback are added in later phases behind config flags.
"""

from .base import ProviderCapabilities, SpeechClientBase, STTErrorKind
from .registry import REGISTRY, ProviderRegistry

__all__ = [
    "ProviderCapabilities",
    "SpeechClientBase",
    "STTErrorKind",
    "ProviderRegistry",
    "REGISTRY",
]
