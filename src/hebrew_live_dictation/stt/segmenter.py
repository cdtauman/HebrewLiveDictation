"""Silence-based segmentation for batch/final-only providers.

Batch engines (local Whisper, Groq) need to be fed discrete utterances, but the
controller expects finals to arrive *during* listening. This segmenter splits a
PCM16 stream on silence gaps using the same energy/RMS heuristic as
``vad.VoiceActivityGate`` so those providers can emit one final per spoken
segment, plus a flush of any remaining speech on stop.
"""

import audioop


def is_speech(chunk: bytes, threshold: float) -> bool:
    try:
        rms = audioop.rms(chunk, 2)
    except Exception:
        return False
    return min(1.0, rms / 1200.0) >= max(0.0, min(1.0, float(threshold)))


class SilenceSegmenter:
    def __init__(self, frame_ms=100, silence_threshold=0.5, segment_silence_ms=700, min_speech_ms=300):
        self._frame_ms = max(1, int(frame_ms))
        self._threshold = max(0.0, min(1.0, float(silence_threshold)))
        self._segment_silence_ms = max(1, int(segment_silence_ms))
        self._min_speech_ms = max(0, int(min_speech_ms))
        self._reset()

    def _reset(self):
        self._buffer = bytearray()
        self._silence_ms = 0
        self._speech_ms = 0
        self._have_speech = False

    def add(self, chunk: bytes):
        """Feed one frame. Returns a completed segment (bytes) when a silence
        gap closes one, otherwise None."""
        if is_speech(chunk, self._threshold):
            self._buffer.extend(chunk)
            self._have_speech = True
            self._speech_ms += self._frame_ms
            self._silence_ms = 0
            return None
        if self._have_speech:
            self._buffer.extend(chunk)  # keep trailing silence for context
            self._silence_ms += self._frame_ms
            if self._silence_ms >= self._segment_silence_ms and self._speech_ms >= self._min_speech_ms:
                segment = bytes(self._buffer)
                self._reset()
                return segment
        return None

    def flush(self):
        """Return any remaining buffered speech (e.g. on stop), else None."""
        if self._have_speech and self._buffer:
            segment = bytes(self._buffer)
            self._reset()
            return segment
        return None
