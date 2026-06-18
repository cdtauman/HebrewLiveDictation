"""Offline local speech-to-text via faster-whisper (CTranslate2).

faster-whisper is batch/final-only, but the dictation controller expects finals
to arrive *during* listening (sentence accumulation + pause-commit). So this
provider segments the incoming PCM16 stream on silence (energy/RMS based, the
same approach as ``vad.VoiceActivityGate``) and emits one ``final`` event per
spoken segment, plus a final for any remaining speech on stop.

Heavy imports (faster_whisper, numpy) are deferred to the worker thread so the
module/provider can be constructed without the dependency installed. The
``_ram_preflight``/``_load_model`` seams are overridable for tests.

Known v1 limitation: stopping mid-utterance with no trailing pause may drop the
last partial segment (the controller resets pending text on stop-completion).
faster-whisper's trailing punctuation usually avoids this.
"""

import logging
import threading

from .base import ProviderCapabilities, SpeechClientBase
from .segmenter import SilenceSegmenter, is_speech


logger = logging.getLogger("WhisperLocalStream")


class WhisperLocalStream(SpeechClientBase):
    capabilities = ProviderCapabilities(
        name="whisper_local",
        streaming=False,
        batch=True,
        interim=False,
        offline=True,
        fallback_target=True,
        needs_credentials=False,
    )

    def __init__(self, config, on_event_callback=None):
        super().__init__(config, on_event_callback)
        self.audio_queue = None
        self.thread = None
        self._model = None
        self._frame_ms = int(config.get("speech.frame_ms", 100) or 100)
        self._silence_threshold = max(0.0, min(1.0, float(config.get("speech.vad_threshold", 0.5) or 0.5)))
        self._segment_silence_ms = int(config.get("providers.whisper.segment_silence_ms", 700) or 700)
        self._min_speech_ms = 300

    # ---- overridable seams (tests patch these) ----
    def _ram_preflight(self):
        from .. import models

        return models.ram_preflight(self.config.get("providers.whisper.model", "small"))

    def _load_model(self):
        from faster_whisper import WhisperModel

        from .. import models

        name = self.config.get("providers.whisper.model", "small")
        device = self.config.get("providers.whisper.device", "cpu")
        compute_type = self.config.get("providers.whisper.compute_type", "int8")
        kwargs = {
            "device": device,
            "compute_type": compute_type,
            "download_root": models.default_storage_dir(self.config),
        }
        revision = models.model_revision(name)
        if revision:
            kwargs["revision"] = revision
        logger.info("Loading local Whisper model %r (%s/%s).", name, device, compute_type)
        return WhisperModel(name, **kwargs)

    # ---- helpers ----
    def _language(self):
        primary = (self.config.get("languages.primary", "iw-IL") or "iw-IL")
        code = primary.split("-")[0].lower()
        return "he" if code == "iw" else code

    def _is_speech(self, chunk: bytes) -> bool:
        return is_speech(chunk, self._silence_threshold)

    def _transcribe(self, pcm16: bytes) -> str:
        import numpy as np

        if not pcm16:
            return ""
        audio = np.frombuffer(bytes(pcm16), dtype=np.int16).astype(np.float32) / 32768.0
        segments, _info = self._model.transcribe(audio, language=self._language())
        return "".join(getattr(seg, "text", "") for seg in segments).strip()

    def _emit_final(self, pcm16: bytes):
        text = self._transcribe(pcm16)
        if text:
            self._emit_event({"type": "final", "text": text, "confidence": 0.0})

    # ---- SpeechClient contract ----
    def start(self, audio_queue):
        self.audio_queue = audio_queue
        self.active = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        try:
            ok, msg = self._ram_preflight()
            if not ok:
                self._emit_event({"type": "error", "message": msg})
                self.active = False
                return

            self._emit_event({"type": "status", "message": "Loading local model..."})
            self._model = self._load_model()
            self._emit_event({"type": "status", "message": "Local model ready."})

            segmenter = SilenceSegmenter(
                frame_ms=self._frame_ms,
                silence_threshold=self._silence_threshold,
                segment_silence_ms=self._segment_silence_ms,
                min_speech_ms=self._min_speech_ms,
            )
            while self.active:
                chunk = self.audio_queue.get()
                if chunk is None:
                    break
                if chunk == b"":
                    continue
                segment = segmenter.add(chunk)
                if segment is not None:
                    self._emit_final(segment)

            segment = segmenter.flush()
            if segment is not None:
                self._emit_final(segment)
        except Exception as e:
            logger.error("Local transcription error: %s", e)
            self._emit_event({"type": "error", "message": f"Local transcription error: {e}"})
        finally:
            self.active = False

    def stop(self):
        self.active = False
        if self.audio_queue:
            try:
                self.audio_queue.put(None)
            except Exception:
                pass
        if self.thread:
            self.thread.join(timeout=8.0)
            self.thread = None
