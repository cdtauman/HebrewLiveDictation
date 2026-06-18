"""Start/stop dictation feedback tones.

Generates short, click-free sine tones as WAV files (cached under the config
dir) so playback (QSoundEffect) needs no bundled assets. Tone generation is
pure-stdlib and unit-tested; playback is wired in the UI layer.
"""

import logging
import math
import os
import struct
import wave


logger = logging.getLogger("AudioFeedback")

# Higher pitch for start, lower for stop.
TONES = {"start": 880, "stop": 440}
_DURATION_MS = 90
_RATE = 16000


def tone_path(config_dir, kind, volume_percent=50):
    freq = TONES.get(kind, 660)
    volume = max(0.0, min(1.0, float(volume_percent) / 100.0))
    path = os.path.join(config_dir, f"tone_{kind}_{int(volume * 100)}.wav")
    if os.path.exists(path):
        return path
    try:
        _write_tone(path, freq, _DURATION_MS, volume=volume)
    except Exception as e:  # pragma: no cover - generation must never crash the app
        logger.warning("Could not generate feedback tone: %s", e)
        return None
    return path


def _write_tone(path, freq, ms, rate=_RATE, volume=0.5):
    n = int(rate * ms / 1000)
    fade = max(1, int(rate * 0.005))  # 5 ms fade in/out to avoid clicks
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(n):
            env = min(1.0, i / fade, (n - i) / fade)
            sample = int(volume * env * 32767 * math.sin(2 * math.pi * freq * i / rate))
            frames += struct.pack("<h", max(-32768, min(32767, sample)))
        w.writeframes(bytes(frames))
    return path
