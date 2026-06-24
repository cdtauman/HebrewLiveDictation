import logging
import threading
import time
import uuid

from PySide6.QtCore import QObject, Signal, QTimer, Qt, Slot

from .audio_stream import AudioStream
from .app_logging import log_transcript
from .i18n import tr
from .stt_factory import create_stt_stream
from .language_packs import parse_voice_command, format_text
from .text_injector import TextInjector


logger = logging.getLogger("DictationController")


class DictationController(QObject):
    stt_event_received = Signal(dict)
    stop_completed = Signal()

    def __init__(self, config, on_status=None, on_text=None, on_error=None, on_command=None):
        super().__init__()
        self.config = config
        self.on_status = on_status
        self.on_text = on_text
        self.on_error = on_error
        self.on_command = on_command

        # Connect signals cross-thread safely using QueuedConnection
        self.stt_event_received.connect(self._on_stt_event_queued, Qt.ConnectionType.QueuedConnection)
        self.stop_completed.connect(self._on_stop_listening_completed, Qt.ConnectionType.QueuedConnection)


        self.state = "idle"
        self.output_mode = "external"
        self.latest_interim_text = ""
        self.has_pasted_final = False
        self.accumulated_final_text = ""
        self.accumulated_timer = None
        self.ignore_next_final = False
        self.session_id = ""
        self.generation = 0

        self.injector = TextInjector(config)
        self.audio_stream = None
        self.stt_stream = None

    def start_listening(self, output_mode="external"):
        if self.state != "idle":
            logger.debug("start_listening ignored. Current state: %s", self.state)
            return

        self.output_mode = "preview" if output_mode == "preview" else "external"
        self.session_id = uuid.uuid4().hex
        self.generation += 1
        logger.info("Starting dictation session. output_mode=%s", self.output_mode)
        self.state = "listening"
        self.latest_interim_text = ""
        self.has_pasted_final = False
        self.accumulated_final_text = ""
        self._stop_accumulation_timer()
        if self.output_mode == "external":
            self.injector.reset_session()
        self._emit_status("listening", tr(self.config, "recording"))

        self._start_capture()

    def _provider_event_callback(self, session_id, generation):
        def emit(event):
            if isinstance(event, dict):
                event = dict(event)
                event.setdefault("session_id", session_id)
                event.setdefault("generation", generation)
            self.stt_event_received.emit(event)
        return emit

    def _start_capture(self):
        sample_rate = int(self.config.get("audio.sample_rate", 16000))
        frame_ms = int(self.config.get("speech.frame_ms", 100))
        block_size = max(1, int(sample_rate * frame_ms / 1000))

        self.audio_stream = AudioStream(
            device_id=self.config.get("microphone_device"),
            sample_rate=sample_rate,
            block_size=block_size,
            vad_enabled=self.config.get("speech.vad_enabled", False),
            vad_threshold=self.config.get("speech.vad_threshold", 0.5),
            vad_padding_ms=self.config.get("speech.vad_padding_ms", 240),
            vad_min_silence_ms=self.config.get("speech.vad_min_silence_ms", 500),
        )

        if not self.audio_stream.start():
            self.handle_error("Microphone audio stream failed to start.")
            return

        self.stt_stream = create_stt_stream(
            self.config,
            self._provider_event_callback(self.session_id, self.generation),
        )

        try:
            self.stt_stream.start(self.audio_stream.get_queue())
        except Exception as e:
            logger.error("Failed to start STT stream: %s", e)
            self.audio_stream.stop()
            self.handle_error(f"Google Speech: {e}")
            return

    def stop_listening(self):
        if self.state not in ("listening", "paused"):
            logger.debug("stop_listening ignored. Current state: %s", self.state)
            return

        logger.info("Stopping dictation session.")
        self.state = "stopping"
        self._stop_accumulation_timer()

        if self.output_mode == "external":
            is_live = self._live_target_typing_enabled()
            if not is_live and self.accumulated_final_text:
                logger.info(
                    "Flushing accumulated final text on stop: text_len=%s.",
                    len(self.accumulated_final_text),
                )
                result = self.injector.inject_final(self.accumulated_final_text)
                self._handle_injector_result(result)
                if result.get("status") in ("inserted", "duplicate", "command"):
                    self.has_pasted_final = True
                self.accumulated_final_text = ""

            if not self.has_pasted_final and self.latest_interim_text:
                logger.info(
                    "Forcing final insert from latest interim on stop: text_len=%s.",
                    len(self.latest_interim_text),
                )
                result = self.injector.inject_final(self.latest_interim_text)
                self._handle_injector_result(result)

        self._emit_status("stopping", tr(self.config, "processing"))

        if self.audio_stream or self.stt_stream:
            def teardown():
                time.sleep(0.15)
                if self.audio_stream:
                    try:
                        self.audio_stream.stop()
                    except Exception:
                        pass
                if self.stt_stream:
                    try:
                        self.stt_stream.stop()
                    except Exception:
                        pass
                self.stop_completed.emit()

            threading.Thread(target=teardown, name="STTTeardownThread", daemon=True).start()
        else:
            self._on_stop_listening_completed()

    def pause_listening(self):
        if self.state != "listening":
            logger.debug("pause_listening ignored. Current state: %s", self.state)
            return

        logger.info("Pausing dictation session.")
        self.state = "paused"
        self.generation += 1   # late events from the suspended provider are stale now
        self._stop_accumulation_timer()
        self._emit_status("paused", tr(self.config, "paused"))
        self._suspend_capture()

    def resume_listening(self):
        if self.state != "paused":
            logger.debug("resume_listening ignored. Current state: %s", self.state)
            return

        logger.info("Resuming dictation session.")
        self.state = "listening"
        self._emit_status("listening", tr(self.config, "recording"))
        self._start_capture()

    def toggle_pause(self, output_mode="external"):
        if self.state == "listening":
            self.pause_listening()
        elif self.state == "paused":
            self.resume_listening()
        elif self.state == "idle":
            self.start_listening(output_mode)

    def _suspend_capture(self):
        audio_stream = self.audio_stream
        stt_stream = self.stt_stream
        self.audio_stream = None
        self.stt_stream = None

        if not audio_stream and not stt_stream:
            return

        def teardown():
            if audio_stream:
                try:
                    audio_stream.stop()
                except Exception:
                    pass
            if stt_stream:
                try:
                    if hasattr(stt_stream, "cancel"):
                        stt_stream.cancel()
                    else:
                        stt_stream.stop()
                except Exception:
                    pass

        threading.Thread(target=teardown, name="STTPauseThread", daemon=True).start()

    def toggle_listening(self, output_mode="external"):
        if self.state == "listening":
            self.stop_listening()
        elif self.state == "paused":
            self.resume_listening()
        elif self.state == "idle":
            self.start_listening(output_mode)

    def handle_stt_event(self, event):
        if self._is_stale_event(event):
            logger.info(
                "Ignoring stale STT event. event_session=%s current_session=%s event_generation=%s current_generation=%s",
                event.get("session_id"),
                self.session_id,
                event.get("generation"),
                self.generation,
            )
            return

        self._stop_accumulation_timer()
        event_type = event.get("type")
        if event_type in ("interim", "final"):
            text = event.get("text", "")
            log_transcript(
                logger,
                logging.DEBUG,
                f"STT {event_type} event",
                text,
                self.config.get("debug_log_transcripts", False),
            )
            self._emit_text(text, final=(event_type == "final"))

            if event_type == "interim":
                self.latest_interim_text = text
                self.has_pasted_final = False
                if self.output_mode == "external":
                    if self._live_target_typing_enabled():
                        result = self.injector.inject_interim(text)
                        logger.debug("Interim live injection result: %s", result)
                        self._start_accumulation_timer()
                    else:
                        logger.debug("External mode interim received; target injection waits for final/stop.")
                        self._start_accumulation_timer()

                if len(text.split()) >= 12:
                    if self.stt_stream and hasattr(self.stt_stream, "restart_stream"):
                        logger.info("Interim segment reached 12 words. Forcing STT restart to preserve quality.")
                        self.stt_stream.restart_stream()
            else:
                logger.info("Received real final STT event: text_len=%s.", len(text))
                if getattr(self, "_ignore_finals_until", 0) > time.time():
                    logger.info("Ignoring leftover final event after stream restart to prevent duplication.")
                    return
                if getattr(self, "ignore_next_final", False):
                    self.ignore_next_final = False
                    self._start_accumulation_timer()
                    return
                if self.output_mode == "external":
                    command = parse_voice_command(text, self.injector._language_code(), self.injector._command_pack())
                    # Post-stop final: offline whisper_local emits its single final AFTER stop, when the
                    # stop-flush has already run with an empty accumulator. In final_only mode that final
                    # would otherwise be accumulated and only flushed on trailing punctuation -> the words
                    # reach history but never get typed. If a (non-command, non-live) final arrives while the
                    # session is no longer listening and nothing was injected this session, inject it once,
                    # verbatim. has_pasted_final guards against double-insertion; this never fires for a
                    # streaming provider's finals-while-listening (state == "listening") or after it already
                    # injected, so cloud/streaming behavior is unchanged.
                    if (not command
                            and not self._live_target_typing_enabled()
                            and self.state not in ("listening", "paused")
                            and not self.has_pasted_final
                            and text.strip()):
                        logger.info("Injecting post-stop final immediately (no later flush will run): text_len=%s.", len(text))
                        result = self.injector.inject_final(text)
                        self._handle_injector_result(result)
                        if result.get("status") in ("inserted", "duplicate", "command"):
                            self.has_pasted_final = True
                        return
                    if command or self._live_target_typing_enabled():
                        if self.accumulated_final_text:
                            flush_result = self.injector.inject_final(self.accumulated_final_text)
                            logger.debug("Flushing accumulated final text before command/live final: %s", flush_result)
                            self._handle_injector_result(flush_result)
                            if flush_result.get("status") in ("inserted", "duplicate", "command"):
                                self.has_pasted_final = True
                            self.accumulated_final_text = ""

                        result = self.injector.inject_final(text)
                        logger.debug("Final injection result: %s", result)
                        self._handle_injector_result(result)
                        if result.get("status") in ("inserted", "duplicate", "command"):
                            self.has_pasted_final = True
                    else:
                        from .language_packs import format_text
                        lang_code = self.config.get("language_code", "he-IL")
                        cmd_pack = self.config.get("languages.command_pack", "he")
                        formatted_segment = format_text(text, lang_code, cmd_pack)
                        if formatted_segment:
                            if self.accumulated_final_text:
                                if not self.accumulated_final_text.endswith(" ") and not formatted_segment.startswith(" ") and not formatted_segment[0] in ".,;:!?":
                                    self.accumulated_final_text += " "
                                self.accumulated_final_text += formatted_segment
                            else:
                                self.accumulated_final_text = formatted_segment

                            trimmed_accumulated = self.accumulated_final_text.strip()
                            if trimmed_accumulated and trimmed_accumulated[-1] in ('.', '?', '!', '\n'):
                                result = self.injector.inject_final(self.accumulated_final_text)
                                logger.debug("Accumulated sentence final injection result: %s", result)
                                self._handle_injector_result(result)
                                if result.get("status") in ("inserted", "duplicate", "command"):
                                    self.has_pasted_final = True
                                self.accumulated_final_text = ""
                            else:
                                self._start_accumulation_timer()
                else:
                    self.has_pasted_final = True
        elif event_type == "error":
            self.handle_error(event.get("message", "Unknown STT error"))
        elif event_type == "status":
            self._emit_status(self.state, event.get("message", ""))
        elif event_type == "speech_start":
            self._emit_status(self.state, tr(self.config, "recording"))
        elif event_type == "speech_end":
            self._emit_status(self.state, tr(self.config, "processing"))
            self._start_accumulation_timer()

    @Slot(dict)
    def _on_stt_event_queued(self, event):
        self.handle_stt_event(event)

    @Slot()
    def _on_stop_listening_completed(self):
        self.audio_stream = None
        self.stt_stream = None
        self.state = "idle"
        self.output_mode = "external"
        self.accumulated_final_text = ""
        self.ignore_next_final = False
        self._emit_status("idle", tr(self.config, "ready"))

    def handle_error(self, message):
        logger.error("Dictation error: %s", message)
        self.state = "error"
        self._emit_status("error", message)
        if self.on_error:
            self.on_error(message)

        if self.audio_stream or self.stt_stream:
            def teardown():
                if self.audio_stream:
                    try:
                        self.audio_stream.stop()
                    except Exception:
                        pass
                if self.stt_stream:
                    try:
                        self.stt_stream.stop()
                    except Exception:
                        pass
                self.stop_completed.emit()
            threading.Thread(target=teardown, name="STTErrorTeardownThread", daemon=True).start()
        else:
            self._on_stop_listening_completed()

    def shutdown(self):
        if self.state in ("listening", "paused"):
            self.stop_listening()

    def _handle_injector_result(self, result):
        if isinstance(result, dict) and result.get("status") == "detached_preview":
            self.latest_interim_text = result.get("text", self.latest_interim_text)
            self._emit_status(self.state, tr(self.config, "target_detached_preview"))
            return

        if not isinstance(result, dict) or result.get("status") != "command":
            return

        action = result.get("action")
        self.latest_interim_text = ""
        self.has_pasted_final = True
        if self.on_command:
            self.on_command(action, result)

        if action == "stop" and self.state == "listening":
            self.stop_listening()

    def _emit_status(self, state, message):
        if self.on_status:
            self.on_status(state, message, self.output_mode)

    def _emit_text(self, text, final=False):
        if self.on_text:
            self.on_text(text, final, self.output_mode)

    def _live_target_typing_enabled(self) -> bool:
        return (
            self.config.get("dictation.live_typing_mode") == "live"
            and bool(self.config.get("labs.live_target_typing_enabled", False))
        )

    def _is_stale_event(self, event) -> bool:
        event_session_id = event.get("session_id")
        if event_session_id and event_session_id != self.session_id:
            return True
        if "generation" not in event:
            return False
        try:
            return int(event.get("generation")) != int(self.generation)
        except (TypeError, ValueError):
            return True

    def _start_accumulation_timer(self):
        self._stop_accumulation_timer()
        timeout_ms = int(float(self.config.get("dictation.pause_commit_timeout_seconds", 1.5)) * 1000)
        self.accumulated_timer = QTimer(self)
        self.accumulated_timer.setSingleShot(True)
        self.accumulated_timer.timeout.connect(self._flush_accumulated_on_timeout)
        self.accumulated_timer.start(timeout_ms)

    def _stop_accumulation_timer(self):
        if self.accumulated_timer:
            self.accumulated_timer.stop()
            self.accumulated_timer.deleteLater()
            self.accumulated_timer = None


    def _flush_accumulated_on_timeout(self):
        flushed_manually = False
        if self.output_mode == "external":
            if self.accumulated_final_text:
                logger.info(
                    "Flushing accumulated final text due to speech pause timeout: text_len=%s.",
                    len(self.accumulated_final_text),
                )
                result = self.injector.inject_final(self.accumulated_final_text)
                self._handle_injector_result(result)
                if result.get("status") in ("inserted", "duplicate", "command"):
                    self.has_pasted_final = True
                self.accumulated_final_text = ""
                flushed_manually = True
            if not self._live_target_typing_enabled() and self.latest_interim_text:
                logger.info(
                    "Flushing latest interim text due to speech pause timeout: text_len=%s.",
                    len(self.latest_interim_text),
                )
                from .language_packs import format_text
                lang_code = self.config.get("language_code", "he-IL")
                cmd_pack = self.config.get("languages.command_pack", "he")
                formatted_segment = format_text(self.latest_interim_text, lang_code, cmd_pack)
                if formatted_segment:
                    result = self.injector.inject_final(formatted_segment)
                    self._handle_injector_result(result)
                    if result.get("status") in ("inserted", "duplicate", "command"):
                        self.has_pasted_final = True
                self.latest_interim_text = ""
                flushed_manually = True

        if self.stt_stream and hasattr(self.stt_stream, "restart_stream"):
            logger.info("Restarting STT stream to reset context and prevent degradation/accumulation.")
            self.stt_stream.restart_stream()
            if flushed_manually:
                # Ignore leftover finals from the dying stream to prevent duplicates
                self._ignore_finals_until = time.time() + 1.5
