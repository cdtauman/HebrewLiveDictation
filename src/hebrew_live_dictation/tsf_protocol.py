from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from typing import Any


MAX_FRAME_BYTES = 64 * 1024
FRAME_HEADER_BYTES = 4


@dataclass(frozen=True)
class DecodedFrame:
    ok: bool
    status: str
    payload: dict[str, Any] | None = None
    reason: str = ""


def encode_frame(payload: dict[str, Any]) -> bytes:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8", errors="strict")
    if len(data) > MAX_FRAME_BYTES:
        raise ValueError("TSF IPC frame is too large")
    return struct.pack("<I", len(data)) + data


def decode_frame(frame: bytes) -> DecodedFrame:
    if len(frame) < FRAME_HEADER_BYTES:
        return DecodedFrame(False, "truncated", reason="missing_length")

    size = struct.unpack("<I", frame[:FRAME_HEADER_BYTES])[0]
    if size > MAX_FRAME_BYTES:
        return DecodedFrame(False, "too_large", reason="frame_limit")
    if len(frame) - FRAME_HEADER_BYTES < size:
        return DecodedFrame(False, "truncated", reason="incomplete_payload")
    if len(frame) - FRAME_HEADER_BYTES > size:
        return DecodedFrame(False, "invalid_frame", reason="trailing_bytes")

    payload_bytes = frame[FRAME_HEADER_BYTES:]
    try:
        text = payload_bytes.decode("utf-8", errors="strict")
        payload = json.loads(text)
    except UnicodeDecodeError:
        return DecodedFrame(False, "invalid_utf8", reason="decode_failed")
    except json.JSONDecodeError:
        return DecodedFrame(False, "invalid_json", reason="parse_failed")

    if not isinstance(payload, dict):
        return DecodedFrame(False, "invalid_json", reason="payload_not_object")
    return DecodedFrame(True, "ok", payload=payload)


class SequenceGate:
    def __init__(self):
        self._generation = -1
        self._seq = -1

    def accept(self, generation: int, seq: int) -> bool:
        generation = int(generation)
        seq = int(seq)
        if generation < self._generation:
            return False
        if generation > self._generation:
            self._generation = generation
            self._seq = seq
            return True
        if seq <= self._seq:
            return False
        self._seq = seq
        return True


class MessageBuilder:
    def __init__(self, session_id: str, generation: int = 1):
        self.session_id = session_id
        self.generation = int(generation)
        self._seq = 0

    def next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def update_composition(self, text: str, selection_start_utf16: int | None = None, selection_end_utf16: int | None = None) -> dict[str, Any]:
        return self._text_message("update_composition", text, selection_start_utf16, selection_end_utf16)

    def commit_text(self, text: str) -> dict[str, Any]:
        return self._text_message("commit_text", text, utf16_length(text), utf16_length(text))

    def cancel_composition(self, reason: str = "") -> dict[str, Any]:
        return self._base("cancel_composition") | {"reason": reason}

    def replace_in_scope(self, old: str, new: str) -> dict[str, Any]:
        return self._base("replace_in_scope") | {"old_text": old, "new_text": new}

    def select_last(self, unit: str) -> dict[str, Any]:
        return self._base("select_last") | {"unit": unit}

    def _text_message(
        self,
        message_type: str,
        text: str,
        selection_start_utf16: int | None,
        selection_end_utf16: int | None,
    ) -> dict[str, Any]:
        length = utf16_length(text)
        start = length if selection_start_utf16 is None else int(selection_start_utf16)
        end = start if selection_end_utf16 is None else int(selection_end_utf16)
        return self._base(message_type) | {
            "text": text,
            "selection_start_utf16": max(0, min(length, start)),
            "selection_end_utf16": max(0, min(length, end)),
        }

    def _base(self, message_type: str) -> dict[str, Any]:
        return {
            "type": message_type,
            "session_id": self.session_id,
            "generation": self.generation,
            "seq": self.next_seq(),
        }


def utf16_length(text: str) -> int:
    return len((text or "").encode("utf-16-le", errors="surrogatepass")) // 2
