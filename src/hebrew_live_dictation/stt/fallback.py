"""AutoFallback speech client: primary (cloud) -> local on terminal failure.

Wraps a primary provider and, on a terminal error from it, transparently
switches the live audio to the local Whisper provider, replaying the buffered
utterance so nothing spoken so far is lost. Selected by ``stt.mode=auto_fallback``.

The audio source queue is owned by this client: a single pump thread reads the
source, appends to a bounded ring buffer (drop-oldest policy) and forwards each
chunk to the active provider's private queue. The switch is performed inline on
the pump thread (never on the failing provider's own callback thread) to avoid
self-join deadlocks and queue races.
"""

import collections
import logging
import queue
import threading

from .base import ProviderCapabilities, SpeechClientBase


logger = logging.getLogger("FallbackSpeechClient")


class FallbackSpeechClient(SpeechClientBase):
    capabilities = ProviderCapabilities(
        name="auto_fallback",
        streaming=True,
        batch=True,
        interim=True,
        offline=True,
        fallback_target=False,
        needs_credentials=False,
    )

    def __init__(
        self,
        config,
        on_event_callback=None,
        primary_name="google_v2",
        local_name="whisper_local",
        max_buffer_chunks=3000,
    ):
        super().__init__(config, on_event_callback)
        self._primary_name = primary_name
        self._local_name = local_name
        self._source_queue = None
        self._active = None
        self._active_queue = None
        self._buffer = collections.deque(maxlen=max_buffer_chunks)
        self._pump_thread = None
        self._switched = False
        self._fallback_requested = False
        # Whether the PRIMARY produced any committed final text before a terminal error.
        # If it did, replaying the buffered (already-transcribed) audio into local would
        # re-emit duplicate content, so the switch must NOT replay the buffer.
        self._primary_emitted_final = False
        self._lock = threading.Lock()

    # Overridable seam for tests.
    def _create(self, name):
        from .registry import REGISTRY

        return REGISTRY.create(name, self.config, self._on_provider_event)

    def _on_provider_event(self, event):
        # Swallow the primary's terminal error and request a switch instead of
        # surfacing it to the controller. After switching, all events pass through
        # (so a local-provider failure still surfaces — no false success).
        if event.get("type") == "error" and not self._switched and self._local_name:
            logger.warning("Primary provider error; requesting fallback to local: %s", event.get("message"))
            with self._lock:
                self._fallback_requested = True
            return
        # Remember if the primary committed any final text before failing. Used to
        # decide whether the fallback may replay the buffered audio (see _do_switch).
        if (not self._switched
                and event.get("type") == "final"
                and str(event.get("text", "")).strip()):
            with self._lock:
                self._primary_emitted_final = True
        self._emit_event(event)

    def start(self, source_queue):
        self._source_queue = source_queue
        self.active = True
        self._switched = False
        self._fallback_requested = False
        self._primary_emitted_final = False
        self._active_queue = queue.Queue()
        self._active = self._create(self._primary_name)
        self._active.start(self._active_queue)
        self._pump_thread = threading.Thread(target=self._pump, name="FallbackPump", daemon=True)
        self._pump_thread.start()

    def _pump(self):
        while self.active:
            if self._fallback_requested and not self._switched:
                self._do_switch_to_local()
            try:
                chunk = self._source_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if chunk is None:
                # If a fallback was requested but not yet applied, switch now so
                # the buffered audio is replayed to local before we close.
                if self._fallback_requested and not self._switched:
                    self._do_switch_to_local()
                with self._lock:
                    if self._active_queue:
                        self._active_queue.put(None)
                break
            if not self._switched:
                self._buffer.append(chunk)
            with self._lock:
                if self._active_queue:
                    self._active_queue.put(chunk)

    def _do_switch_to_local(self):
        self._switched = True
        self._emit_event(
            {"type": "status", "message": "Cloud transcription unavailable; switching to offline local mode."}
        )
        old = self._active
        if old:
            try:
                old.stop()  # safe: runs on the pump thread, not the provider's own thread
            except Exception as e:  # pragma: no cover
                logger.warning("Error stopping primary during fallback: %s", e)
        new_queue = queue.Queue()
        with self._lock:
            replay = not self._primary_emitted_final
        if replay:
            # Rescue path: the primary produced no committed final, so the buffered
            # utterance is unsaved -> replay it to local so nothing spoken is lost.
            for chunk in list(self._buffer):
                new_queue.put(chunk)
        else:
            # The primary already committed final text for the buffered audio. Replaying
            # it would re-transcribe and emit duplicate content (even with slightly
            # different punctuation/spacing that exact dedupe can't catch). Switch local
            # onto only subsequent audio. Safety over completeness (MF2).
            logger.info(
                "Primary already emitted a committed final; not replaying buffer to local "
                "to avoid duplicate content."
            )
        local = self._create(self._local_name)
        with self._lock:
            self._active_queue = new_queue
            self._active = local
        local.start(new_queue)

    def restart_stream(self):
        with self._lock:
            active = self._active
        if active is not None and hasattr(active, "restart_stream"):
            active.restart_stream()

    def stop(self):
        self.active = False
        if self._source_queue is not None:
            try:
                self._source_queue.put(None)
            except Exception:
                pass
        if self._pump_thread is not None:
            self._pump_thread.join(timeout=2.0)
            self._pump_thread = None
        with self._lock:
            active = self._active
        if active is not None:
            try:
                active.stop()
            except Exception:
                pass
