from __future__ import annotations

import audioop
from collections import deque


class VoiceActivityGate:
    """Small local VAD gate with pre-roll padding.

    The threshold is intentionally normalized to a speech-like score instead of
    raw RMS so the public setting can later map to a neural VAD without changing
    the configuration shape.
    """

    def __init__(
        self,
        frame_ms: int = 100,
        threshold: float = 0.5,
        padding_ms: int = 240,
        min_silence_ms: int = 500,
    ):
        self.frame_ms = max(1, int(frame_ms))
        self.threshold = max(0.0, min(1.0, float(threshold)))
        self.padding_frames = max(1, int(round(max(0, padding_ms) / self.frame_ms)))
        self.min_silence_frames = max(1, int(round(max(100, min_silence_ms) / self.frame_ms)))
        self._pre_roll: deque[bytes] = deque(maxlen=self.padding_frames)
        self._in_speech = False
        self._silence_frames = 0

    def process(self, chunk: bytes) -> list[bytes]:
        if not chunk:
            return []

        if self._is_speech(chunk):
            if not self._in_speech:
                self._in_speech = True
                self._silence_frames = 0
                buffered = list(self._pre_roll)
                self._pre_roll.clear()
                return buffered + [chunk]

            self._silence_frames = 0
            return [chunk]

        if self._in_speech:
            self._silence_frames += 1
            if self._silence_frames < self.min_silence_frames:
                return [chunk]
            self._in_speech = False
            self._silence_frames = 0

        self._pre_roll.append(chunk)
        return []

    def reset(self) -> None:
        self._pre_roll.clear()
        self._in_speech = False
        self._silence_frames = 0

    def _is_speech(self, chunk: bytes) -> bool:
        try:
            rms = audioop.rms(chunk, 2)
        except audioop.error:
            return False
        speech_score = min(1.0, rms / 1200.0)
        return speech_score >= self.threshold
