import struct
import unittest

from hebrew_live_dictation.tsf_protocol import MAX_FRAME_BYTES, SequenceGate, decode_frame, encode_frame


class TSFProtocolTests(unittest.TestCase):
    def test_frame_round_trips_hebrew_utf8(self):
        payload = {"type": "composition_update", "generation": 1, "seq": 7, "text": "שלום עולם"}

        frame = encode_frame(payload)
        decoded = decode_frame(frame)

        self.assertTrue(decoded.ok, decoded)
        self.assertEqual(decoded.payload, payload)

    def test_truncated_frame_is_rejected(self):
        frame = encode_frame({"type": "hello", "text": "שלום"})

        decoded = decode_frame(frame[:-2])

        self.assertFalse(decoded.ok)
        self.assertEqual(decoded.status, "truncated")

    def test_invalid_utf8_is_rejected_before_json_parse(self):
        payload = b'{"type":"composition_update","text":"\xff"}'
        frame = struct.pack("<I", len(payload)) + payload

        decoded = decode_frame(frame)

        self.assertFalse(decoded.ok)
        self.assertEqual(decoded.status, "invalid_utf8")

    def test_oversized_frame_is_rejected(self):
        frame = struct.pack("<I", MAX_FRAME_BYTES + 1)

        decoded = decode_frame(frame)

        self.assertFalse(decoded.ok)
        self.assertEqual(decoded.status, "too_large")

    def test_sequence_gate_drops_stale_generation_and_sequence(self):
        gate = SequenceGate()

        self.assertTrue(gate.accept(1, 1))
        self.assertTrue(gate.accept(1, 2))
        self.assertFalse(gate.accept(1, 2))
        self.assertFalse(gate.accept(1, 1))
        self.assertTrue(gate.accept(2, 1))
        self.assertFalse(gate.accept(1, 999))
