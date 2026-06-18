r"""
Engine-side sidecar: wraps the existing engine and exposes it over the named-pipe
JSON-RPC server. This is the *thin adapter* between the WinUI shell and the engine.

It does not modify any engine module. Because `DictationController` is a QObject that
relies on `QueuedConnection` signals and `QTimer`, the sidecar runs a windowless
`QApplication` to pump queued STT events and timers. The named-pipe server runs on a
background thread and marshals controller calls onto the Qt main thread.

Run as:  python -m hebrew_live_dictation.bridge
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import traceback

from .server import DEFAULT_PIPE_NAME, NamedPipeJsonRpcServer

logger = logging.getLogger("voicetype.bridge")

HEARTBEAT_MS = 10000


def run(pipe_name: str = DEFAULT_PIPE_NAME) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

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
    server: NamedPipeJsonRpcServer | None = None

    def on_status(state, message, output_mode):
        if server:
            server.send_event({"kind": "status", "state": state,
                               "message": message, "outputMode": output_mode})

    def on_text(text, final, output_mode):
        if server:
            server.send_event({"kind": "text", "text": text,
                               "final": bool(final), "outputMode": output_mode})

    def on_error(message):
        if server:
            server.send_event({"kind": "error", "message": message})

    def on_command(action, result):
        if server:
            server.send_event({"kind": "command", "action": action})

    controller = DictationController(
        config, on_status=on_status, on_text=on_text,
        on_error=on_error, on_command=on_command,
    )

    def hotkey_start():
        if server:
            server.send_event({"kind": "hotkey", "edge": "start"})
        invoker.invoke.emit(lambda: controller.start_listening("external"))

    def hotkey_stop():
        if server:
            server.send_event({"kind": "hotkey", "edge": "stop"})
        invoker.invoke.emit(controller.stop_listening)

    hotkeys = HotkeyListener(config, hotkey_start, hotkey_stop)
    try:
        hotkeys.start()
        hotkeys_ok = True
    except Exception as e:
        logger.error("HotkeyListener failed to start: %s", e)
        hotkeys_ok = False

    def handle_request(method, params):
        if method == "ping":
            return {"ok": True, "pid": os.getpid()}
        if method == "getStatus":
            return {"state": controller.state, "hotkeysActive": hotkeys_ok,
                    "configDir": config_dir}
        if method == "getConfig":
            return {"key": params.get("key"),
                    "value": config.get(params.get("key"), params.get("default"))}
        if method == "getAllConfig":
            return config.as_dict()
        if method == "setConfig":
            # Settings boundary: the ENGINE is the single writer (persists to disk).
            config.set(params["key"], params["value"])
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
            invoker.invoke.emit(app.quit)
            return {"accepted": True}
        raise ValueError(f"unknown method: {method}")

    server = NamedPipeJsonRpcServer(handle_request, name=pipe_name)
    server.start()
    logger.info("VoiceType engine sidecar ready on %s (pid=%s, hotkeys=%s)",
                pipe_name, os.getpid(), hotkeys_ok)

    hb = QTimer()
    hb.setInterval(HEARTBEAT_MS)
    hb.timeout.connect(lambda: server and server.send_event(
        {"kind": "heartbeat", "state": controller.state}))
    hb.start()

    exit_code = app.exec()
    try:
        hotkeys.stop()
    except Exception:
        pass
    server.stop()
    return exit_code
