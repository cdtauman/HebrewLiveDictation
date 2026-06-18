"""Deepgram Nova streaming speech-to-text ("Best Hebrew realtime").

Streaming over a synchronous WebSocket (websockets.sync) on a worker thread:
one sender thread pushes PCM16 frames, the main thread receives JSON results and
emits interim/final events. The API key is read from the OS keyring via
secrets_store (never plaintext config). Network/auth failures emit a terminal
``error`` event, which AutoFallback turns into a switch to local.

Heavy imports (websockets, json) and the connection are behind seams so the URL
building, message parsing, key resolution, and no-key path are unit-testable
without network access.
"""

import json
import logging
import threading

from .base import ProviderCapabilities, SpeechClientBase


logger = logging.getLogger("DeepgramStream")

_ENDPOINT = "wss://api.deepgram.com/v1/listen"


class DeepgramStream(SpeechClientBase):
    capabilities = ProviderCapabilities(
        name="deepgram",
        streaming=True,
        batch=False,
        interim=True,
        offline=False,
        fallback_target=False,
        needs_credentials=True,
    )

    def __init__(self, config, on_event_callback=None):
        super().__init__(config, on_event_callback)
        self.audio_queue = None
        self.thread = None
        self._sender = None
        self._conn = None

    # ---- seams (tests patch these) ----
    def _resolve_key(self):
        from .. import secrets_store

        return secrets_store.provider_api_key(self.config, "deepgram")

    def _connect(self, url, key):
        from websockets.sync.client import connect

        return connect(url, additional_headers={"Authorization": f"Token {key}"})

    # ---- helpers ----
    def _language(self):
        primary = (self.config.get("languages.primary", "iw-IL") or "iw-IL")
        code = primary.split("-")[0].lower()
        return "he" if code == "iw" else code

    def _build_url(self):
        sample_rate = int(self.config.get("audio.sample_rate", 16000) or 16000)
        model = self.config.get("providers.deepgram.model", "nova-2") or "nova-2"
        params = {
            "model": model,
            "language": self._language(),
            "encoding": "linear16",
            "sample_rate": str(sample_rate),
            "channels": "1",
            "interim_results": "true" if self.config.get("google.interim_results", True) else "false",
            "punctuate": "true" if self.config.get("google.automatic_punctuation", True) else "false",
        }
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{_ENDPOINT}?{query}"

    def _handle_message(self, raw):
        try:
            msg = json.loads(raw)
        except (ValueError, TypeError):
            return
        channel = msg.get("channel") if isinstance(msg, dict) else None
        if not channel:
            return
        alternatives = channel.get("alternatives") or []
        if not alternatives:
            return
        transcript = (alternatives[0] or {}).get("transcript", "")
        if not transcript:
            return
        confidence = float((alternatives[0] or {}).get("confidence", 0.0) or 0.0)
        is_final = bool(msg.get("is_final") or msg.get("speech_final"))
        self._emit_event(
            {"type": "final" if is_final else "interim", "text": transcript, "confidence": confidence}
        )

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
                {"type": "error", "message": "Deepgram API key is not configured.", "code": "terminal"}
            )
            self.active = False
            return
        try:
            self._conn = self._connect(self._build_url(), key)
        except Exception as e:
            logger.error("Deepgram connection failed: %s", e)
            self._emit_event({"type": "error", "message": f"Deepgram connection failed: {e}", "code": "terminal"})
            self.active = False
            return

        self._sender = threading.Thread(target=self._send_loop, name="DeepgramSender", daemon=True)
        self._sender.start()

        try:
            while self.active:
                try:
                    message = self._conn.recv(timeout=0.5)
                except TimeoutError:
                    continue
                if message is None:
                    break
                if isinstance(message, (bytes, bytearray)):
                    message = message.decode("utf-8", "ignore")
                self._handle_message(message)
        except Exception as e:
            if self.active:
                logger.error("Deepgram stream error: %s", e)
                self._emit_event({"type": "error", "message": f"Deepgram stream error: {e}", "code": "terminal"})
        finally:
            self.active = False
            self._close_conn()

    def _send_loop(self):
        try:
            while self.active:
                chunk = self.audio_queue.get()
                if chunk is None:
                    break
                if chunk == b"":
                    continue
                try:
                    self._conn.send(chunk)
                except Exception:
                    break
        finally:
            # Politely tell Deepgram to flush/close the stream.
            try:
                self._conn.send(json.dumps({"type": "CloseStream"}))
            except Exception:
                pass

    def _close_conn(self):
        try:
            if self._conn is not None:
                self._conn.close()
        except Exception:
            pass
        self._conn = None

    def stop(self):
        self.active = False
        if self.audio_queue is not None:
            try:
                self.audio_queue.put(None)
            except Exception:
                pass
        self._close_conn()
        if self.thread is not None:
            self.thread.join(timeout=3.0)
            self.thread = None
