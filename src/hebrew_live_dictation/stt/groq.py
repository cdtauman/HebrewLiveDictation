"""Groq Whisper batch speech-to-text ("Cheapest cloud").

Groq exposes an OpenAI-compatible audio-transcription REST endpoint (no
streaming), so this provider segments the PCM16 stream on silence (shared
SilenceSegmenter) and POSTs each spoken segment as a WAV, emitting one final per
segment plus a flush on stop. The API key comes from the OS keyring via
secrets_store. Network/auth failures emit a terminal error (-> AutoFallback).

HTTP and key resolution are behind seams so segmentation, WAV building, response
parsing, and the no-key path are unit-testable without network access.
"""

import io
import logging
import threading
import wave

from .base import ProviderCapabilities, SpeechClientBase
from .segmenter import SilenceSegmenter


logger = logging.getLogger("GroqStream")

_ENDPOINT = "https://api.groq.com/openai/v1/audio/transcriptions"


class GroqStream(SpeechClientBase):
    capabilities = ProviderCapabilities(
        name="groq",
        streaming=False,
        batch=True,
        interim=False,
        offline=False,
        fallback_target=False,
        needs_credentials=True,
    )

    def __init__(self, config, on_event_callback=None):
        super().__init__(config, on_event_callback)
        self.audio_queue = None
        self.thread = None
        self._sample_rate = int(config.get("audio.sample_rate", 16000) or 16000)
        self._frame_ms = int(config.get("speech.frame_ms", 100) or 100)
        self._silence_threshold = max(0.0, min(1.0, float(config.get("speech.vad_threshold", 0.5) or 0.5)))
        self._segment_silence_ms = int(config.get("providers.whisper.segment_silence_ms", 700) or 700)

    # ---- seams (tests patch these) ----
    def _resolve_key(self):
        from .. import secrets_store

        return secrets_store.provider_api_key(self.config, "groq")

    def _post(self, wav_bytes, key):
        import requests

        model = self.config.get("providers.groq.model", "whisper-large-v3") or "whisper-large-v3"
        resp = requests.post(
            _ENDPOINT,
            headers={"Authorization": f"Bearer {key}"},
            files={"file": ("audio.wav", wav_bytes, "audio/wav")},
            data={"model": model, "language": self._language(), "response_format": "json"},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json().get("text", "")

    # ---- helpers ----
    def _language(self):
        primary = (self.config.get("languages.primary", "iw-IL") or "iw-IL")
        code = primary.split("-")[0].lower()
        return "he" if code == "iw" else code

    def _to_wav(self, pcm16: bytes) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(self._sample_rate)
            wav.writeframes(pcm16)
        return buf.getvalue()

    def _transcribe_segment(self, pcm16: bytes, key: str) -> str:
        if not pcm16:
            return ""
        return (self._post(self._to_wav(pcm16), key) or "").strip()

    def _emit_segment(self, pcm16: bytes, key: str):
        text = self._transcribe_segment(pcm16, key)
        if text:
            self._emit_event({"type": "final", "text": text, "confidence": 0.0})

    # ---- SpeechClient contract ----
    def start(self, audio_queue):
        self.audio_queue = audio_queue
        self.active = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        key = self._resolve_key()
        if not key:
            self._emit_event(
                {"type": "error", "message": "Groq API key is not configured.", "code": "terminal"}
            )
            self.active = False
            return
        try:
            segmenter = SilenceSegmenter(
                frame_ms=self._frame_ms,
                silence_threshold=self._silence_threshold,
                segment_silence_ms=self._segment_silence_ms,
            )
            while self.active:
                chunk = self.audio_queue.get()
                if chunk is None:
                    break
                if chunk == b"":
                    continue
                segment = segmenter.add(chunk)
                if segment is not None:
                    self._emit_segment(segment, key)
            segment = segmenter.flush()
            if segment is not None:
                self._emit_segment(segment, key)
        except Exception as e:
            logger.error("Groq transcription error: %s", e)
            self._emit_event({"type": "error", "message": f"Groq transcription error: {e}", "code": "terminal"})
        finally:
            self.active = False

    def stop(self):
        self.active = False
        if self.audio_queue is not None:
            try:
                self.audio_queue.put(None)
            except Exception:
                pass
        if self.thread is not None:
            self.thread.join(timeout=5.0)
            self.thread = None
