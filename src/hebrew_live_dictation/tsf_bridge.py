from __future__ import annotations

import logging
import os
import secrets
import json
from dataclasses import dataclass

from .tsf_ipc import NamedPipeCommandSession
from .tsf_protocol import MessageBuilder

logger = logging.getLogger("TSFBridge")


@dataclass(frozen=True)
class TSFHandshakeResult:
    available: bool
    status: str
    reason: str = ""
    pipe_name: str = ""
    session_id: str = ""
    nonce: str = ""


class TSFBridge:
    """Python-side guardrail for the future native TSF component.

    The native component is not part of v1. This bridge deliberately fails
    closed unless an external TSF transport is explicitly configured and a
    short handshake succeeds. That lets the app keep the stable v1 path while
    v2 compatibility work happens behind a hard fallback boundary.
    """

    def __init__(self, config):
        self.config = config
        self._session: NamedPipeCommandSession | None = None
        self._builder: MessageBuilder | None = None
        self._advertised_session_id = ""

    def handshake(self, target, session_id: str) -> TSFHandshakeResult:
        self.close()
        if self.config.get("dictation.input_backend", "v1") != "tsf":
            return TSFHandshakeResult(False, "disabled", "input_backend_not_tsf", session_id=session_id)

        if not target or not target.is_usable_external():
            return TSFHandshakeResult(False, "target_unavailable", "no_usable_external_target", session_id=session_id)

        pipe_name = self._pipe_name(session_id)
        nonce = secrets.token_hex(16)
        timeout_ms = int(self.config.get("tsf.handshake_timeout_ms", 100))
        self._write_advertisement(pipe_name, session_id, nonce, timeout_ms)

        # There is no production native TSF peer yet. A future implementation
        # must replace this probe with overlapped pipe I/O and preserve the same
        # fail-closed contract.
        if not self.config.get("tsf.experimental_transport_enabled", False):
            logger.info(
                "TSF requested but experimental transport is disabled; falling back. target=%s timeout_ms=%s",
                target.describe(),
                timeout_ms,
            )
            return TSFHandshakeResult(
                False,
                "fallback",
                "experimental_transport_disabled",
                pipe_name=pipe_name,
                session_id=session_id,
                nonce=nonce,
            )

        server = NamedPipeCommandSession(
            pipe_name,
            session_id,
            nonce,
            timeout_ms=timeout_ms,
            allow_low_integrity_label=self.config.get("tsf.allow_low_integrity_label", False),
        )
        result = server.start()
        if result.ok:
            self._session = server
            self._builder = MessageBuilder(session_id=session_id, generation=1)
            logger.info("TSF handshake succeeded. target=%s pipe=%s", target.describe(), pipe_name)
            return TSFHandshakeResult(
                True,
                "connected",
                pipe_name=pipe_name,
                session_id=session_id,
                nonce=nonce,
            )

        logger.info(
            "TSF handshake failed; falling back to v1. status=%s reason=%s target=%s pipe=%s",
            result.status,
            result.reason,
            target.describe(),
            pipe_name,
        )
        return TSFHandshakeResult(
            False,
            result.status,
            result.reason,
            pipe_name=pipe_name,
            session_id=session_id,
            nonce=nonce,
        )

    def send_update(self, text: str) -> bool:
        if not self._session or not self._builder:
            return False
        return self._session.send(self._builder.update_composition(text))

    def send_commit(self, text: str) -> bool:
        if not self._session or not self._builder:
            return False
        return self._session.send(self._builder.commit_text(text))

    def send_replace_in_scope(self, old: str, new: str) -> bool:
        if not self._session or not self._builder:
            return False
        return self._session.send(self._builder.replace_in_scope(old, new))

    def send_select_last(self, unit: str) -> bool:
        if not self._session or not self._builder:
            return False
        return self._session.send(self._builder.select_last(unit))

    def close(self):
        if self._session:
            self._session.close()
        self._session = None
        self._builder = None
        self._remove_advertisement()

    def _pipe_name(self, session_id: str) -> str:
        user_part = str(os.getuid()) if hasattr(os, "getuid") else os.environ.get("USERNAME", "user")
        return rf"\\.\pipe\VoiceType-{user_part}-{session_id}"

    def _advertisement_path(self) -> str:
        config_dir = getattr(self.config, "config_dir", "") or os.path.join(os.environ.get("APPDATA", ""), "VoiceType")
        return os.path.join(config_dir, "tsf_session.json")

    def _write_advertisement(self, pipe_name: str, session_id: str, nonce: str, timeout_ms: int):
        path = self._advertisement_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            payload = {
                "pipe_name": pipe_name,
                "session_id": session_id,
                "nonce": nonce,
                "timeout_ms": timeout_ms,
            }
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            self._advertised_session_id = session_id
        except Exception as e:
            logger.info("Could not write TSF session advertisement: %s", e)

    def _remove_advertisement(self):
        if not self._advertised_session_id:
            return
        path = self._advertisement_path()
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
                if payload.get("session_id") == self._advertised_session_id:
                    os.remove(path)
        except Exception as e:
            logger.info("Could not remove TSF session advertisement: %s", e)
        finally:
            self._advertised_session_id = ""
