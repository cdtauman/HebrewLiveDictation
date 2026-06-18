import unittest

import numpy as np

from hebrew_live_dictation.stt.segmenter import SilenceSegmenter, is_speech


def _speech():
    return np.full(1600, 5000, dtype=np.int16).tobytes()


def _silence():
    return np.zeros(1600, dtype=np.int16).tobytes()


class SegmenterTests(unittest.TestCase):
    def test_is_speech(self):
        self.assertTrue(is_speech(_speech(), 0.5))
        self.assertFalse(is_speech(_silence(), 0.5))

    def test_segment_returned_after_silence_gap(self):
        seg = SilenceSegmenter(frame_ms=100, silence_threshold=0.5, segment_silence_ms=200, min_speech_ms=300)
        out = None
        for _ in range(5):
            self.assertIsNone(seg.add(_speech()))
        # first silence frame: not yet enough silence
        self.assertIsNone(seg.add(_silence()))
        # second silence frame: 200ms reached -> emit segment
        out = seg.add(_silence())
        self.assertIsNotNone(out)
        self.assertEqual(len(out), 1600 * 2 * 7)  # 5 speech + 2 silence frames

    def test_flush_returns_remaining_speech(self):
        seg = SilenceSegmenter(segment_silence_ms=5000)
        for _ in range(3):
            seg.add(_speech())
        out = seg.flush()
        self.assertIsNotNone(out)
        self.assertEqual(len(out), 1600 * 2 * 3)
        self.assertIsNone(seg.flush())  # nothing left

    def test_short_speech_below_min_not_emitted(self):
        seg = SilenceSegmenter(frame_ms=100, segment_silence_ms=100, min_speech_ms=500)
        seg.add(_speech())  # 100ms speech only
        out = seg.add(_silence())  # silence >= 100ms but speech < 500ms
        self.assertIsNone(out)


if __name__ == "__main__":
    unittest.main()
