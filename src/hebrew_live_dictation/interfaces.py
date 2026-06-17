from __future__ import annotations

from typing import Any, Literal, Protocol, TypedDict


STTEventType = Literal["interim", "final", "speech_start", "speech_end", "error", "status"]


class STTEvent(TypedDict, total=False):
    type: STTEventType
    text: str
    confidence: float
    message: str
    code: int | str
    session_id: str
    generation: int


class TargetIdentity(TypedDict, total=False):
    hwnd: int
    process_id: int
    process_name: str
    title: str
    generation: int


class TSFHandshake(TypedDict, total=False):
    available: bool
    status: str
    reason: str
    pipe_name: str
    session_id: str
    nonce: str


class AudioSource(Protocol):
    def start(self) -> bool: ...
    def stop(self) -> None: ...
    def get_queue(self) -> Any: ...


class SpeechClient(Protocol):
    def start(self, audio_queue: Any) -> None: ...
    def stop(self) -> None: ...
    def restart_stream(self) -> None: ...


class TextCommitter(Protocol):
    def reset_session(self) -> None: ...
    def inject_interim(self, text: str) -> dict[str, Any]: ...
    def inject_final(self, text: str) -> dict[str, Any]: ...


class CompositionCommitter(Protocol):
    def begin_composition(self, session_id: str, target: TargetIdentity) -> TSFHandshake: ...
    def update_composition(self, text: str, generation: int) -> dict[str, Any]: ...
    def commit_composition(self, text: str, generation: int) -> dict[str, Any]: ...
    def cancel_composition(self, reason: str) -> dict[str, Any]: ...


class CommandParser(Protocol):
    def parse(self, text: str, language_code: str, command_pack: str | None = None) -> Any: ...
