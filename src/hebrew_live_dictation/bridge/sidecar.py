r"""
Engine-side sidecar: wraps the existing engine and exposes it over the named-pipe
JSON-RPC server. This is the *thin adapter* between the WinUI shell and the engine.

It does not modify any engine module. Because `DictationController` is a QObject that
relies on `QueuedConnection` signals and `QTimer`, the sidecar runs a windowless
`QApplication` to pump queued STT events and timers. The named-pipe server runs on a
background thread and marshals controller calls onto the Qt main thread.

Run as:  python -m hebrew_live_dictation.bridge [--pipe \\.\pipe\<name>]
The WinUI shell passes a per-launch unique pipe name so a client can only ever attach
to the sidecar it spawned (never a stale/orphan one).
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import time
import traceback

from .server import DEFAULT_PIPE_NAME, NamedPipeJsonRpcServer

logger = logging.getLogger("voicetype.bridge")

HEARTBEAT_MS = 10000


def make_callbacks(hotkeys, server_ref, on_session_end=None):
    """Build the controller event callbacks.

    Extracted so the listening-state sync (toggle-hotkey parity with the legacy Qt
    app) and the session-history accumulation are unit-testable without a Qt event
    loop. `server_ref` returns the live server (or None before it is constructed).
    `on_session_end(transcript)` is invoked once per completed session (parity with
    the legacy app, which appended finalized transcripts to history in the UI layer).
    """

    finals = []

    def send(event):
        server = server_ref()
        if server is not None:
            server.send_event(event)

    def on_status(state, message, output_mode):
        # Keep the toggle hotkey in sync with the real dictation state, exactly as
        # the legacy Qt app did (qt_app.py: set_listening_state on every status).
        # Without this, F8 toggle starts but never stops.
        hotkeys.set_listening_state(state == "listening")
        # Session ended: append the accumulated finals to history. The legacy app
        # did this in qt_app (_flush_session_history); the sidecar must replicate it
        # or completed WinUI sessions never reach history / Home recent activity.
        if state == "idle" and finals:
            transcript = " ".join(finals).strip()
            finals.clear()
            if transcript and on_session_end:
                try:
                    on_session_end(transcript)
                except Exception:
                    logger.error("session history append failed:\n%s", traceback.format_exc())
        send({"kind": "status", "state": state, "message": message, "outputMode": output_mode})

    def on_text(text, final, output_mode):
        if final and text and text.strip():
            finals.append(text.strip())
        send({"kind": "text", "text": text, "final": bool(final), "outputMode": output_mode})

    def on_error(message):
        send({"kind": "error", "message": message})

    def on_command(action, result):
        send({"kind": "command", "action": action})

    return on_status, on_text, on_error, on_command


_MODEL_PRETTY = {
    "chirp_3": "Chirp 3", "chirp_2": "Chirp 2", "chirp": "Chirp",
    "latest_long": "Latest Long", "latest_short": "Latest Short",
}


def engine_label(config) -> str:
    """User-facing engine name derived from config (no engine internals exposed)."""
    provider = config.get("stt.provider", "google_v2")
    mode = config.get("stt.mode", "api")
    if mode == "local" or provider == "whisper_local":
        return "לא־מקוון · Whisper"
    if provider == "google_v2":
        model = str(config.get("google.model", "chirp_3"))
        return "Google · " + _MODEL_PRETTY.get(model, model)
    if provider == "deepgram":
        return "Deepgram"
    if provider == "groq":
        return "Groq"
    return str(provider)


def compute_health(config) -> dict:
    """Home health strip: engine label, microphone availability, offline readiness."""
    try:
        from ..audio_stream import AudioStream
        mic_ok = bool(AudioStream.list_devices())
    except Exception:
        mic_ok = False
    mode = config.get("stt.mode", "api")
    offline_ready = bool(config.get("providers.whisper.enabled", False)) or mode in ("local", "auto_fallback")
    return {
        "engine": {"label": engine_label(config)},
        "microphone": {"ok": mic_ok},
        "offline": {"ready": offline_ready},
    }


HISTORY_PREVIEW_MAX = 80
HISTORY_COUNT_MAX = 50


def recent_history(config, count) -> list:
    """Bounded, sanitized Home preview: newest first, only {ts, text} with text
    truncated to a short preview. `target` and full text are never exposed, and
    `count` is clamped (the underlying file is already capped at history.max_entries).
    """
    try:
        n = int(count)
    except (TypeError, ValueError):
        n = 5
    n = max(1, min(n, HISTORY_COUNT_MAX))
    try:
        from ..history import load
        items = load(config, limit=n)
    except Exception:
        return []
    out = []
    for it in reversed(items):
        if not isinstance(it, dict):
            continue
        text = str(it.get("text", "")).strip()
        if not text:
            continue
        if len(text) > HISTORY_PREVIEW_MAX:
            text = text[:HISTORY_PREVIEW_MAX].rstrip() + "…"
        ts = it.get("ts", 0)
        out.append({"ts": ts if isinstance(ts, (int, float)) else 0, "text": text})
    return out


def _append_history(config, transcript):
    try:
        from ..history import append
        append(config, transcript)
    except Exception:
        pass


def _parse_pipe_arg(argv) -> str:
    for i, a in enumerate(argv):
        if a == "--pipe" and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith("--pipe="):
            return a.split("=", 1)[1]
    return DEFAULT_PIPE_NAME


def run(pipe_name: str | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if pipe_name is None:
        pipe_name = _parse_pipe_arg(sys.argv)

    # COM STA + per-monitor-v2 DPI, mirroring the engine's own entry point so the
    # Word-COM injector and DPI behavior match the legacy app exactly.
    if sys.platform == "win32":
        sys.coinit_flags = 2  # COINIT_APARTMENTTHREADED
        try:
            ctypes.windll.ole32.CoInitialize(None)
        except Exception:
            pass
        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except Exception:
            pass

    from PySide6.QtCore import QObject, Qt, QTimer, Signal
    from PySide6.QtWidgets import QApplication

    from ..config import Config
    from ..dictation_controller import DictationController
    from ..hotkeys import HotkeyListener

    appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
    config_dir = os.path.join(appdata, "VoiceType")
    config = Config(config_dir)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    class Invoker(QObject):
        """Marshal a callable onto the Qt main thread (for controller calls)."""
        invoke = Signal(object)

        def __init__(self):
            super().__init__()
            self.invoke.connect(self._run, Qt.ConnectionType.QueuedConnection)

        def _run(self, fn):
            try:
                fn()
            except Exception:
                logger.error("main-thread invoke failed:\n%s", traceback.format_exc())

    invoker = Invoker()
    server_holder = {"server": None}

    # Controller first (no callbacks yet), then hotkeys, then wire callbacks so the
    # callbacks can reference the hotkey listener for listening-state sync.
    controller = DictationController(config)

    def hotkey_start():
        s = server_holder["server"]
        if s:
            s.send_event({"kind": "hotkey", "edge": "start"})
        invoker.invoke.emit(lambda: controller.start_listening("external"))

    def hotkey_stop():
        s = server_holder["server"]
        if s:
            s.send_event({"kind": "hotkey", "edge": "stop"})
        invoker.invoke.emit(controller.stop_listening)

    hotkeys = HotkeyListener(config, hotkey_start, hotkey_stop)

    on_status, on_text, on_error, on_command = make_callbacks(
        hotkeys, lambda: server_holder["server"],
        on_session_end=lambda transcript: _append_history(config, transcript))
    controller.on_status = on_status
    controller.on_text = on_text
    controller.on_error = on_error
    controller.on_command = on_command

    try:
        hotkeys.start()
        hotkeys_ok = True
    except Exception as e:
        logger.error("HotkeyListener failed to start: %s", e)
        hotkeys_ok = False

    def do_shutdown():
        # Clean teardown: stop any active dictation BEFORE quitting the loop, then
        # quit. Mirrors the legacy app (controller.shutdown() on exit).
        try:
            controller.shutdown()
        except Exception:
            logger.error("controller.shutdown failed:\n%s", traceback.format_exc())
        app.quit()

    def handle_request(method, params):
        if method == "ping":
            return {"ok": True, "pid": os.getpid()}
        if method == "getStatus":
            return {"state": controller.state, "hotkeysActive": hotkeys_ok,
                    "configDir": config_dir, "pipe": pipe_name}
        if method == "getConfig":
            return {"key": params.get("key"),
                    "value": config.get(params.get("key"), params.get("default"))}
        if method == "getAllConfig":
            return config.as_dict()
        if method == "getHealth":
            return compute_health(config)
        if method == "getHistory":
            return {"items": recent_history(config, params.get("count", 5))}
        if method == "setConfig":
            config.set(params["key"], params["value"])  # engine is the single writer
            return {"key": params["key"], "value": config.get(params["key"]), "saved": True}
        if method == "startDictation":
            invoker.invoke.emit(lambda: controller.start_listening(params.get("mode", "external")))
            return {"accepted": True}
        if method == "stopDictation":
            invoker.invoke.emit(controller.stop_listening)
            return {"accepted": True}
        if method == "toggleDictation":
            invoker.invoke.emit(lambda: controller.toggle_listening(params.get("mode", "external")))
            return {"accepted": True}
        if method == "shutdown":
            invoker.invoke.emit(do_shutdown)
            return {"accepted": True}
        raise ValueError(f"unknown method: {method}")

    server = NamedPipeJsonRpcServer(handle_request, name=pipe_name)
    server_holder["server"] = server
    server.start()
    logger.info("VoiceType engine sidecar ready on %s (pid=%s, hotkeys=%s)",
                pipe_name, os.getpid(), hotkeys_ok)

    hb = QTimer()
    hb.setInterval(HEARTBEAT_MS)
    hb.timeout.connect(lambda: server.send_event({"kind": "heartbeat", "state": controller.state}))
    hb.start()

    exit_code = app.exec()

    # Final clean teardown (idempotent if already shut down via RPC), then give any
    # async stream teardown a brief moment before the process exits.
    try:
        controller.shutdown()
    except Exception:
        pass
    time.sleep(0.25)
    try:
        hotkeys.stop()
    except Exception:
        pass
    server.stop()
    return exit_code
