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
import json
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
        target = foreground_app_name() if state == "listening" else ""
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
        event = {"kind": "status", "state": state, "message": message, "outputMode": output_mode}
        if target:
            event["target"] = target   # where text will land — the HUD's "→ {app}" reassurance
        send(event)

    def on_text(text, final, output_mode):
        if final and text and text.strip():
            finals.append(text.strip())
        send({"kind": "text", "text": text, "final": bool(final), "outputMode": output_mode})

    def on_error(message):
        send({"kind": "error", "message": message})

    def on_command(action, result):
        send({"kind": "command", "action": action})

    return on_status, on_text, on_error, on_command


# Friendly labels for the HUD's "→ {app}" target reassurance. The map covers the apps
# Hebrew professionals dictate into most; anything else falls back to the executable's
# base name. Our own shell is suppressed so a console-triggered start doesn't read
# "→ VoiceType".
_APP_NAMES = {
    "winword.exe": "Word", "excel.exe": "Excel", "powerpnt.exe": "PowerPoint",
    "outlook.exe": "Outlook", "onenote.exe": "OneNote", "notepad.exe": "Notepad",
    "wordpad.exe": "WordPad", "chrome.exe": "Chrome", "msedge.exe": "Edge",
    "firefox.exe": "Firefox", "whatsapp.exe": "WhatsApp", "telegram.exe": "Telegram",
    "slack.exe": "Slack", "teams.exe": "Teams", "code.exe": "VS Code",
    "explorer.exe": "Explorer", "acrobat.exe": "Acrobat",
}
_SELF_APPS = {"voicetype.exe"}


def friendly_app_name(proc: str) -> str:
    """Map a foreground process executable name to a friendly app label for the HUD.
    Returns "" for our own shell (suppressed) or an unusable name; otherwise falls back
    to the base name without its .exe extension."""
    if not proc:
        return ""
    key = proc.strip().lower()
    if not key or key in _SELF_APPS:
        return ""
    if key in _APP_NAMES:
        return _APP_NAMES[key]
    base = key[:-4] if key.endswith(".exe") else key
    return base[:1].upper() + base[1:] if base else ""


def _foreground_process_name() -> str:
    """Executable name of the current foreground window's process (Windows only). Our
    overlays are no-activate, so at listening-start the foreground window is the user's
    actual target app."""
    if sys.platform != "win32":
        return ""
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ""
        pid = ctypes.c_ulong(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return ""
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not handle:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(260)
            size = ctypes.c_ulong(260)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return os.path.basename(buf.value)
            return ""
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return ""


def foreground_app_name() -> str:
    """Friendly label for the current foreground app, or "" when unknown/suppressed."""
    try:
        return friendly_app_name(_foreground_process_name())
    except Exception:
        return ""


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
    """Home health strip: engine label, microphone availability, offline readiness.

    Offline backup is "ready" only when it is BOTH configured (stt.mode is local or
    auto_fallback) AND the local Whisper engine is actually enabled. Being configured
    for fallback without enabling Whisper does not make offline backup work, so we
    never claim it does — `configured` is reported separately from `ready`.
    """
    try:
        from ..audio_stream import AudioStream
        mic_ok = bool(AudioStream.list_devices())
    except Exception:
        mic_ok = False
    mode = config.get("stt.mode", "api")
    whisper_enabled = bool(config.get("providers.whisper.enabled", False))
    offline_configured = mode in ("local", "auto_fallback")
    offline_ready = offline_configured and whisper_enabled
    return {
        "engine": {"label": engine_label(config)},
        "microphone": {"ok": mic_ok},
        "offline": {"ready": offline_ready, "configured": offline_configured},
    }


def list_microphones(config=None) -> dict:
    """Input devices for the Controls mic picker — a thin wrapper over the engine's own
    enumeration (AudioStream.list_devices, also used by the health check). Returns just the
    real devices keyed by their device index; the UI prepends a "Windows default" option
    (the engine treats a null microphone_device as the system default).

    When `config` is given and at least one device is enumerated, a saved selection whose
    index is no longer present is cleared to null (Windows default), so the engine never
    opens a stale device on the next dictation — keeping persisted truth and the UI in sync.
    """
    try:
        from ..audio_stream import AudioStream
        devices = AudioStream.list_devices()
    except Exception:
        logger.error("list_microphones failed:\n%s", traceback.format_exc())
        devices = []
    items = []
    for d in devices:
        try:
            name = str(d.get("display_name") or d.get("name") or "").strip()
            if name:
                items.append({"index": int(d["index"]), "name": name})
        except Exception:
            continue
    if config is not None and items:
        _normalize_microphone(config, {it["index"] for it in items})
    return {"items": items}


def _normalize_microphone(config, available_indices) -> bool:
    """Clear audio.microphone_device to null when it points at a device that is gone.
    Returns True if it cleared the stale selection. Only call with a non-empty device set."""
    saved = config.get("audio.microphone_device")
    if isinstance(saved, int) and not isinstance(saved, bool) and saved not in available_indices:
        config.set("audio.microphone_device", None)
        logger.info("Cleared stale microphone device %s (no longer present).", saved)
        return True
    return False


HISTORY_PREVIEW_MAX = 80
HISTORY_COUNT_MAX = 50
HISTORY_TAIL_MAX_BYTES = 8_000_000  # never read more than this from the tail (corrupt/huge files)


def _tail_entries(path, limit) -> list:
    """Return up to the last `limit` JSON entries (oldest->newest) WITHOUT loading the
    whole file: seek from the end and read bounded blocks until we have enough lines or
    hit a byte ceiling. Corrupt lines are skipped. This keeps a pathological history
    file from blocking the single IPC request loop (unlike history.load, which reads the
    entire file before slicing).
    """
    if limit <= 0 or not os.path.exists(path):
        return []
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            pos = f.tell()
            data = b""
            block = 65536
            # +1 so the (possibly partial) first line is safely discarded by the slice
            while pos > 0 and data.count(b"\n") <= limit and len(data) < HISTORY_TAIL_MAX_BYTES:
                read = min(block, pos)
                pos -= read
                f.seek(pos)
                data = f.read(read) + data
        text = data.decode("utf-8", errors="replace")
        out = []
        for line in text.splitlines()[-limit:]:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out
    except Exception:
        return []


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
        from ..history import _path
        items = _tail_entries(_path(config), n)
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


HISTORY_FULL_MAX = 5000  # absolute safety ceiling regardless of config


def full_history(config, count) -> list:
    """Full transcripts for the History room: newest-first, untruncated, with the
    target app. Unlike the sanitized Home preview, this is the user's own complete
    record on their machine. The ceiling is the configured store cap
    (history.max_entries) so an "export all" returns everything the store keeps,
    bounded by an absolute safety ceiling.
    """
    try:
        max_entries = int(config.get("history.max_entries", 500) or 500)
    except (TypeError, ValueError):
        max_entries = 500
    ceiling = max(1, min(max_entries, HISTORY_FULL_MAX))
    try:
        n = int(count)
    except (TypeError, ValueError):
        n = min(200, ceiling)
    n = max(1, min(n, ceiling))
    try:
        from ..history import _path
        items = _tail_entries(_path(config), n)
    except Exception:
        return []
    out = []
    for it in reversed(items):
        if not isinstance(it, dict):
            continue
        text = str(it.get("text", "")).strip()
        if not text:
            continue
        ts = it.get("ts", 0)
        out.append({
            "ts": ts if isinstance(ts, (int, float)) else 0,
            "text": text,
            "target": str(it.get("target", "")),
        })
    return out


def _append_history(config, transcript):
    try:
        from ..history import append
        append(config, transcript)
    except Exception:
        pass


def _clear_history(config) -> bool:
    try:
        from ..history import clear
        return bool(clear(config))
    except Exception:
        return False


_SYMBOL_LABELS = {"\n": "↵ שורה חדשה", "\n\n": "¶ פסקה"}
_ACTION_LABELS = {
    "stop": "עצירת הכתבה",
    "delete_last_word": "מחיקת המילה האחרונה",
    "delete_last_sentence": "מחיקת המשפט האחרון",
    "clear_all": "מחיקת הכל",
    "undo": "ביטול",
    "send": "שליחה",
    "next_field": "מעבר לשדה הבא",
    "select_last_word": "בחירת המילה האחרונה",
    "select_last_sentence": "בחירת המשפט האחרון",
    "replace_phrase": "החלפת ביטוי",
    "delete_phrase": "מחיקת ביטוי",
}


def _visible_symbol(symbol) -> str:
    if symbol in _SYMBOL_LABELS:
        return _SYMBOL_LABELS[symbol]
    stripped = symbol.strip()
    return stripped if stripped else symbol


def command_reference(config) -> dict:
    """Human-readable voice-command reference for the active command pack — for the
    Dictation room. Returns punctuation (say -> inserted symbol) and actions
    (say -> friendly label), keeping only the first phrase per result so the many
    alternates in a pack collapse into one clean teaching list.
    """
    try:
        from ..language_packs import get_pack
        pack = get_pack(config.get("languages.primary", "iw-IL"),
                        config.get("languages.command_pack", None))
    except Exception:
        return {"punctuation": [], "actions": []}

    punctuation, seen = [], set()
    for phrase, symbol in pack.get("punctuation", ()):
        if symbol in seen:
            continue
        seen.add(symbol)
        punctuation.append({"say": phrase, "inserts": _visible_symbol(symbol)})

    actions, seen_actions = [], set()
    for phrase, action in pack.get("commands", {}).items():
        if action in seen_actions:
            continue
        seen_actions.add(action)
        actions.append({"say": phrase, "does": _ACTION_LABELS.get(action, action)})

    return {"punctuation": punctuation, "actions": actions}


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

    # Clear a stale saved microphone before any dictation can start, so the engine falls
    # back to the Windows default rather than trying a device that no longer exists —
    # even if the user never opens the Controls room this session.
    try:
        list_microphones(config)
    except Exception:
        logger.error("startup microphone normalization failed:\n%s", traceback.format_exc())

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
        if method == "getCommands":
            return command_reference(config)
        if method == "listMicrophones":
            return list_microphones(config)
        if method == "getHistory":
            return {"items": recent_history(config, params.get("count", 5))}
        if method == "getTranscripts":
            return {"items": full_history(config, params.get("count", 200))}
        if method == "clearHistory":
            # Destructive: require an explicit confirmation flag at the RPC boundary so
            # a stray/automated call can never wipe the store without intent.
            if not params.get("confirm"):
                return {"cleared": False, "error": "confirmation required"}
            return {"cleared": _clear_history(config)}
        if method == "setConfig":
            saved = config.set(params["key"], params["value"])  # engine is the single writer
            return {"key": params["key"], "value": config.get(params["key"]), "saved": bool(saved)}
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
