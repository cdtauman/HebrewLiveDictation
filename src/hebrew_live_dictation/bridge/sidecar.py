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
import threading
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
    # HUD target reassurance is captured ONCE when a session enters "listening" and is
    # reused for every later listening-status refresh, so the displayed target can never
    # change mid-session. `fallback` latches when the engine reports the cloud provider
    # dropped to local mid-session (auto_fallback). Both reset the moment listening ends.
    session = {"listening": False, "target": "", "fallback": False, "target_changed": False}

    def send(event):
        server = server_ref()
        if server is not None:
            server.send_event(event)

    def on_status(state, message, output_mode):
        # Keep the toggle hotkey in sync with the real dictation state, exactly as
        # the legacy Qt app did (qt_app.py: set_listening_state on every status).
        # Without this, F8 toggle starts but never stops.
        hotkeys.set_listening_state(state == "listening")

        # Capture the injection target exactly once, on the transition into listening.
        # Latch the offline-fallback notice if the engine reports it mid-session. The
        # target-changed notice is transient: set on the detached-preview status and
        # cleared by the next normal status.
        if state == "listening":
            if not session["listening"]:
                session["listening"] = True
                session["target"] = injection_target_label()
                session["fallback"] = False
            if is_fallback_status(message):
                session["fallback"] = True
            session["target_changed"] = is_target_changed_status(message)
        else:
            session["listening"] = False
            session["target"] = ""
            session["fallback"] = False
            session["target_changed"] = False
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
        if state == "listening":
            # Always carry the captured-once target while listening; "" tells the HUD to
            # show its safe state rather than a confident — possibly wrong — target claim.
            event["target"] = session["target"]
            if session["fallback"]:
                event["fallback"] = True
            if session["target_changed"]:
                event["targetChanged"] = True
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


# Markers for the engine's auto_fallback notice. The FallbackSpeechClient emits a
# status event ("Cloud transcription unavailable; switching to offline local mode.")
# the moment it switches the live audio from the cloud provider to local Whisper. We
# match on stable substrings of that one engine-owned message rather than the whole
# literal, so wording tweaks upstream don't silently drop the §10 "offline backup
# active" treatment.
_FALLBACK_STATUS_MARKERS = ("offline local mode", "switching to offline")


def is_fallback_status(message) -> bool:
    """True when a listening status message is the engine's offline-fallback notice."""
    if not message:
        return False
    text = str(message).lower()
    return any(marker in text for marker in _FALLBACK_STATUS_MARKERS)


# Markers for the engine's "target changed" notice. The controller emits a status with
# tr(..., "target_detached_preview") when the injector finds the captured window gone and
# keeps the text in preview instead of writing it. The message is localized (he/en), so we
# match a stable substring of each known translation (i18n.py).
_TARGET_CHANGED_MARKERS = ("target changed", "יעד הכתיבה השתנה")


def is_target_changed_status(message) -> bool:
    """True when a listening status message is the engine's target-detached notice."""
    if not message:
        return False
    text = str(message).lower()
    return any(marker.lower() in text for marker in _TARGET_CHANGED_MARKERS)


def injection_target_label() -> str:
    """Friendly label of the window the text injector will actually type into.

    Critically, this uses the SAME selection the injector uses
    (WindowTarget.capture_best_target) and the SAME safety gate (is_usable_external),
    so the HUD's "יעד: X" can never name a window the injector would not actually write
    to. Returns "" when the target is unknown, detached, our own shell, or an
    unsafe/blocked window — the HUD then shows a safe state rather than a confident
    (possibly wrong) claim. Windows-only; safe-empty on any failure."""
    if sys.platform != "win32":
        return ""
    try:
        from ..editing_backend import WindowTarget
        target = WindowTarget.capture_best_target()
        if target is None or not target.is_usable_external():
            return ""
        return friendly_app_name(target.process_name)
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


def model_downloaded(config) -> bool:
    """Whether the configured local Whisper model is actually present on disk. The single
    source of truth for offline readiness — a flag/config alone never proves offline works."""
    try:
        from .. import models
        return bool(models.model_status(config).get("downloaded"))
    except Exception:
        return False


# Shown (and routed on) when offline is the live engine but no model is installed. Hebrew
# first, with a short English tail so a mixed-locale user still understands. The shell reads
# the `needsModel` flag to route the user to the explicit download flow (Engine room).
OFFLINE_MODEL_REQUIRED_MSG = (
    "המודל הלא־מקוון אינו מותקן. התקינו אותו בחדר המנוע כדי להכתיב במצב לא־מקוון. "
    "(Offline model not installed — install it in the Engine room first.)"
)


def offline_is_primary_engine(config) -> bool:
    """True when starting dictation now runs local Whisper as the LIVE (primary) transcriber —
    i.e. the path that, without an installed model, would otherwise trigger faster-whisper's
    silent first-use auto-download.

    Mirrors stt_factory's selection: stt.mode 'local' forces whisper_local, and an explicit
    whisper_local provider is the live engine — but BOTH require providers.whisper.enabled to
    actually run (else the factory falls back to the cloud default, so no local download would
    happen). auto_fallback / smart_auto are deliberately NOT counted: their live path is the
    cloud provider, and the local backup is reached (if at all) only mid-session — which the
    sidecar cannot gate at the start boundary without touching protected STT modules.
    """
    mode = config.get("stt.mode", "api") or "api"
    provider = config.get("stt.provider", "google_v2") or "google_v2"
    whisper_enabled = bool(config.get("providers.whisper.enabled", False))
    selects_local = (mode == "local") or (provider == "whisper_local")
    return selects_local and whisper_enabled


def offline_model_required(config) -> bool:
    """True when starting dictation would run local Whisper as primary but no usable model is
    installed. Option A: all offline model acquisition goes through the explicit download flow,
    so the caller must REFUSE to start (never let faster-whisper silently auto-download) and
    route the user to download the model first. Readiness is the authoritative on-disk check."""
    try:
        return offline_is_primary_engine(config) and not model_downloaded(config)
    except Exception:
        logger.error("offline model gate check failed:\n%s", traceback.format_exc())
        return False


def model_status(config) -> dict:
    """Local-model state for the UI (Onboarding/Engine): {name, downloaded, path}. Read-only;
    no heavy import (presence is an on-disk check), so safe to call on any status query."""
    try:
        from .. import models
        return models.model_status(config)
    except Exception:
        logger.error("model_status failed:\n%s", traceback.format_exc())
        return {"name": "", "downloaded": False, "path": ""}


class ModelDownloadManager:
    """Runs a single local-model download OFF the pipe thread and streams progress events.

    faster-whisper / Hugging Face downloads do not expose granular byte progress, so progress
    is honest and indeterminate: a "running" event, then "done" (the model is now complete) or
    "error". Only one download runs at a time; a second request while busy is refused, not
    queued. `send_event` is the server's thread-safe push; `downloader(config, name)` is
    injectable for tests (defaults to models.download_model, which writes the completion
    marker on success).
    """

    def __init__(self, send_event, downloader=None):
        self._send = send_event
        self._downloader = downloader
        self._lock = threading.Lock()
        self._running = None  # model name currently downloading, else None

    @property
    def active(self):
        with self._lock:
            return self._running

    def start(self, config, name=None) -> dict:
        from .. import models
        name = name or config.get("providers.whisper.model", models.DEFAULT_MODEL)
        with self._lock:
            if self._running is not None:
                return {"started": False, "busy": True, "name": self._running}
            self._running = name
        self._emit("running", name)
        threading.Thread(target=self._run, args=(config, name),
                         name="ModelDownload", daemon=True).start()
        return {"started": True, "name": name}

    def _run(self, config, name):
        from .. import models
        try:
            download = self._downloader or (lambda cfg, nm: models.download_model(cfg, nm))
            download(config, name)
            # Do NOT trust the downloader returning. Re-validate with the strong readiness
            # check: only report done if the model is now actually complete and usable.
            if models.model_status(config, name).get("downloaded"):
                self._emit("done", name, downloaded=True)
            else:
                self._emit("error", name,
                           message="Download finished but the model is incomplete or unusable.")
        except Exception as e:
            logger.error("model download failed:\n%s", traceback.format_exc())
            self._emit("error", name, message=str(e))
        finally:
            with self._lock:
                self._running = None

    def _emit(self, state, name, **extra):
        try:
            event = {"kind": "modelDownload", "state": state, "name": name}
            event.update(extra)
            self._send(event)
        except Exception:
            logger.error("model download event emit failed:\n%s", traceback.format_exc())


def delete_model(config, name=None) -> dict:
    """Remove a local model from disk (Engine-room model management). Returns
    {deleted, name}. Safe-empty on failure; the caller guards with a confirm flag."""
    try:
        from .. import models
        name = name or config.get("providers.whisper.model", models.DEFAULT_MODEL)
        removed = models.delete_model(name, models.default_storage_dir(config))
        return {"deleted": bool(removed), "name": name}
    except Exception:
        logger.error("delete_model failed:\n%s", traceback.format_exc())
        return {"deleted": False, "name": name or ""}


def compute_health(config) -> dict:
    """Home health strip: engine label, microphone availability, offline readiness.

    Offline is "ready" only when it is configured (stt.mode is local or auto_fallback), the
    local Whisper engine is enabled, AND the model is actually downloaded. Enabling Whisper
    without the model on disk does NOT make offline work, so we never claim it does —
    `configured` and `model_ready` are reported separately from `ready`.
    """
    try:
        from ..audio_stream import AudioStream
        mic_ok = bool(AudioStream.list_devices())
    except Exception:
        mic_ok = False
    mode = config.get("stt.mode", "api")
    whisper_enabled = bool(config.get("providers.whisper.enabled", False))
    offline_configured = mode in ("local", "auto_fallback")
    has_model = model_downloaded(config)
    offline_ready = offline_configured and whisper_enabled and has_model
    return {
        "engine": {"label": engine_label(config)},
        "microphone": {"ok": mic_ok},
        "offline": {"ready": offline_ready, "configured": offline_configured, "model_ready": has_model},
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
        if config.set("audio.microphone_device", None):
            logger.info("Cleared stale microphone device %s (no longer present).", saved)
            return True
        # Persisting null failed (e.g. disk error). Do NOT claim the device was cleared;
        # the saved value is still stale and config.set already rolled memory back.
        logger.warning("Stale microphone device %s could not be cleared (save failed).", saved)
        return False
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

    def emit_event(event):
        s = server_holder["server"]
        if s:
            s.send_event(event)

    model_downloads = ModelDownloadManager(emit_event)

    # Controller first (no callbacks yet), then hotkeys, then wire callbacks so the
    # callbacks can reference the hotkey listener for listening-state sync.
    controller = DictationController(config)

    def offline_start_refused() -> bool:
        """Option A gate: if offline is the live engine but no model is installed, refuse to
        start dictation and surface a clear, recoverable status that routes the user to the
        explicit download flow — never let faster-whisper silently auto-download. Returns True
        when the start was refused (caller must NOT start)."""
        if not offline_model_required(config):
            return False
        emit_event({"kind": "status", "state": "error",
                    "message": OFFLINE_MODEL_REQUIRED_MSG, "needsModel": True})
        return True

    def hotkey_start():
        if offline_start_refused():
            return
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
        if method == "getModelStatus":
            return model_status(config)
        if method == "downloadModel":
            # Runs off this thread; progress arrives as {"kind":"modelDownload",...} events.
            return model_downloads.start(config, params.get("name"))
        if method == "deleteModel":
            # Destructive: require an explicit confirmation flag at the RPC boundary.
            if not params.get("confirm"):
                return {"deleted": False, "error": "confirmation required"}
            # Don't delete out from under an in-flight download (it would race the writer and
            # could leave a half-written cache). Refuse while a download is active.
            if model_downloads.active is not None:
                return {"deleted": False, "error": "download in progress"}
            return delete_model(config, params.get("name"))
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
            if offline_start_refused():
                return {"accepted": False, "needsModel": True, "message": OFFLINE_MODEL_REQUIRED_MSG}
            invoker.invoke.emit(lambda: controller.start_listening(params.get("mode", "external")))
            return {"accepted": True}
        if method == "stopDictation":
            invoker.invoke.emit(controller.stop_listening)
            return {"accepted": True}
        if method == "toggleDictation":
            # Only a start (idle -> listening) can trigger an offline model download; a toggle
            # that stops an active session needs no model, so gate only when currently idle.
            if controller.state == "idle" and offline_start_refused():
                return {"accepted": False, "needsModel": True, "message": OFFLINE_MODEL_REQUIRED_MSG}
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
