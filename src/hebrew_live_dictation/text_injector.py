import ctypes
import logging
import uuid
import time
import threading

import pyperclip
from pynput.keyboard import Controller, Key, KeyCode

from .app_logging import log_transcript
from .editing_backend import WindowTarget, WordCOMEditor, UIAutomationEditor
from .language_packs import (
    delete_last_sentence_text,
    delete_last_word_text,
    parse_voice_command,
    prepare_text_for_insert,
)
from .text_diff import compute_end_rewrite
from .tsf_bridge import TSFBridge


keyboard = Controller()
vk_v = KeyCode.from_vk(0x56)

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
VK_BACK = 0x08

logger = logging.getLogger("TextInjector")


class KEYBDINPUT(ctypes.Structure):
    _fields_ = (
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.c_void_p),
    )

class MOUSEINPUT(ctypes.Structure):
    _fields_ = (
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.c_void_p),
    )


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = (
        ("uMsg", ctypes.c_ulong),
        ("wParamL", ctypes.c_ushort),
        ("wParamH", ctypes.c_ushort),
    )


class INPUTUNION(ctypes.Union):
    _fields_ = (("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT))


class INPUT(ctypes.Structure):
    _fields_ = (("type", ctypes.c_ulong), ("union", INPUTUNION))


try:
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    CF_UNICODETEXT = 13
    RegisterClipboardFormatW = user32.RegisterClipboardFormatW
    RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    RegisterClipboardFormatW.restype = wintypes.UINT
    cf_exclude = RegisterClipboardFormatW("ExcludeClipboardContentFromMonitor")
except Exception:
    user32 = None
    kernel32 = None
    cf_exclude = 0

try:
    from ctypes import wintypes
    class KBDLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("vkCode", wintypes.DWORD),
            ("scanCode", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_void_p)
        ]
    HOOKPROC = ctypes.WINFUNCTYPE(
        ctypes.c_longlong,
        ctypes.c_int,
        wintypes.WPARAM,
        ctypes.POINTER(KBDLLHOOKSTRUCT)
    )
except Exception:
    KBDLLHOOKSTRUCT = None
    HOOKPROC = None

WH_KEYBOARD_LL = 13
LLKHF_INJECTED = 0x00000010
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104


def _utf16_units(text: str):
    data = text.encode("utf-16-le", errors="surrogatepass")
    for index in range(0, len(data), 2):
        yield data[index] | (data[index + 1] << 8)


def copy_without_history(text: str) -> bool:
    if not user32 or not kernel32:
        return False
    try:
        if not user32.OpenClipboard(0):
            return False
        user32.EmptyClipboard()
        text_len = len(text) + 1
        handle = kernel32.GlobalAlloc(0x0042, text_len * ctypes.sizeof(ctypes.c_wchar))
        if not handle:
            user32.CloseClipboard()
            return False
        data = kernel32.GlobalLock(handle)
        ctypes.memmove(data, text, text_len * ctypes.sizeof(ctypes.c_wchar))
        kernel32.GlobalUnlock(handle)
        user32.SetClipboardData(CF_UNICODETEXT, handle)
        if cf_exclude:
            marker = kernel32.GlobalAlloc(0x0042, 1)
            user32.SetClipboardData(cf_exclude, marker)
        user32.CloseClipboard()
        return True
    except Exception as e:
        logger.error("copy_without_history failed: %s", e)
        try:
            user32.CloseClipboard()
        except Exception:
            pass
        return False


class TextInjector:
    """Commit-only text injection.

    Interim transcripts are intentionally preview-only. The external target is
    touched only when a final transcript or voice command must be committed.
    That keeps Word and other apps away from fragile live rewrites.
    """

    def __init__(self, config):
        self.config = config
        self.word_editor = WordCOMEditor()
        self.uia_editor = UIAutomationEditor()
        self.last_insert_backend = ""
        self.session_interim_text = ""
        self.is_injecting = False
        self.abort_requested = False
        self.last_raw_text = ""
        self.window_switch_ignore_word_count = 0
        self.session_id = ""
        self.target_generation = 0
        self.target_detached = False
        self.detached_pending_text = ""
        self.input_backend = "v1"
        self.tsf_bridge = TSFBridge(config)
        self.tsf_status = None
        self._hook_h = None
        self._hook_proc = None
        
        self._start_keyboard_hook()
        
        WindowTarget.start_tracker()
        self.reset_session()

    def reset_session(self):
        self.session_id = uuid.uuid4().hex
        self.target_generation = 1
        self.target_detached = False
        self.detached_pending_text = ""
        self.session_pasted_text = ""
        self.session_interim_text = ""
        self.pending_preview_text = ""
        self.history = []
        self.journal = []
        self.last_insert_backend = ""
        self.last_raw_text = ""
        self.window_switch_ignore_word_count = 0
        self.target = WindowTarget.capture_best_target()
        self.input_backend = "v1"
        self.tsf_status = self.tsf_bridge.handshake(self.target, self.session_id)
        if self.tsf_status.available:
            self.input_backend = "tsf"
            logger.info("TSF backend enabled for session. target=%s", self.target.describe())
        elif self.config.get("dictation.input_backend", "v1") == "tsf":
            logger.info(
                "TSF backend unavailable; using v1 fallback. status=%s reason=%s target=%s",
                self.tsf_status.status,
                self.tsf_status.reason,
                self.target.describe() if self.target else "none",
            )
        if self.target and self.target.is_usable_external():
            logger.info("Text injector session reset. target=%s", self.target.describe())
        else:
            logger.info(
                "Text injector session reset without usable external target. target=%s",
                self.target.describe() if self.target else "none",
            )

    def _check_target_change(self) -> bool:
        current_target = WindowTarget.capture_foreground()
        if current_target:
            if not self.target or current_target.hwnd != self.target.hwnd:
                logger.info("Foreground target changed. Old: %s, New: %s. Detaching session scope.",
                            self.target.describe() if self.target else "None",
                            current_target.describe())
                self._detach_target("focus_lost")
                return False
        return not self.target_detached

    def _detach_target(self, reason: str):
        self.target_generation += 1
        self.target_detached = True
        self.tsf_bridge.close()
        self.input_backend = "v1"
        self.session_interim_text = ""
        self.pending_preview_text = ""
        self.last_raw_text = ""
        self.window_switch_ignore_word_count = 0
        self._close_editable_scope(reason)

    def _close_editable_scope(self, reason: str):
        if self.session_pasted_text or self.history:
            logger.info("Closing editable scope: reason=%s session_text_len=%s", reason, len(self.session_pasted_text))
        self.session_pasted_text = ""
        self.history = []

    def _detached_result(self, text: str, reason: str):
        self.detached_pending_text = text or self.detached_pending_text
        self._record("detached_preview", reason=reason, text=self.detached_pending_text, backend="preview_only")
        return {
            "status": "detached_preview",
            "reason": reason,
            "text": self.detached_pending_text,
            "backend": "preview_only",
        }

    def inject_interim(self, text: str):
        if not text:
            if self.config.get("dictation.live_typing_mode") == "live" and self.session_interim_text:
                self._replace_text(self.session_interim_text, "")
                self.session_interim_text = ""
            return {"status": "empty"}
        if parse_voice_command(text, self._language_code(), self._command_pack()):
            if self.config.get("dictation.live_typing_mode") == "live" and self.session_interim_text:
                self._replace_text(self.session_interim_text, "")
                self.session_interim_text = ""
            return {"status": "command_preview"}

        raw_input = text
        if self.config.get("dictation.live_typing_mode") == "live":
            if not self._check_target_change():
                return self._detached_result(raw_input, "target_changed")
            self.last_raw_text = raw_input

        target_text = prepare_text_for_insert(
            text,
            self.session_pasted_text,
            self._language_code(),
            self._command_pack(),
        )
        self.pending_preview_text = target_text
        
        if self.config.get("dictation.live_typing_mode") == "live":
            success = self._replace_text(self.session_interim_text, target_text)
            if success:
                self.session_interim_text = target_text
                self._record(
                    "interim_live",
                    raw_text=raw_input,
                    text=target_text,
                    inserted=target_text,
                    backend=self._insertion_backend(),
                )
                return {"status": "inserted", "text": target_text, "backend": self._insertion_backend()}
            else:
                return {"status": "target_unavailable", "text": target_text, "backend": "none"}
        else:
            if self.input_backend == "tsf" and self.tsf_bridge.send_update(target_text):
                self.session_interim_text = target_text
                self._record("interim_tsf", raw_text=raw_input, text=target_text, backend="tsf")
                return {"status": "inserted", "text": target_text, "backend": "tsf"}
            log_transcript(
                logger,
                logging.DEBUG,
                "Interim preview text",
                target_text,
                self.config.get("debug_log_transcripts", False),
            )
            self._record("interim_preview", raw_text=raw_input, text=target_text, backend="preview_only")
            return {"status": "preview_only", "text": target_text, "backend": "preview_only"}

    def inject_final(self, text: str):
        if not text:
            if self.config.get("dictation.live_typing_mode") == "live" and self.session_interim_text:
                self._replace_text(self.session_interim_text, "")
                self.session_interim_text = ""
            self.pending_preview_text = ""
            self.last_raw_text = ""
            self.window_switch_ignore_word_count = 0
            return {"status": "empty"}

        command = parse_voice_command(text, self._language_code(), self._command_pack())
        if command:
            if command.action != "stop" and not self._check_target_change():
                return self._detached_result(text, "target_changed")
            if self.config.get("dictation.live_typing_mode") == "live" and self.session_interim_text:
                self._replace_text(self.session_interim_text, "")
                self.session_interim_text = ""
            self.pending_preview_text = ""
            self.last_raw_text = ""
            self.window_switch_ignore_word_count = 0
            return self._execute_command(command.action, command.args)

        raw_input = text
        if not self._check_target_change():
            return self._detached_result(raw_input, "target_changed")
        if self.config.get("dictation.live_typing_mode") == "live":
            if self.window_switch_ignore_word_count > 0:
                words = text.split()
                if len(words) >= self.window_switch_ignore_word_count:
                    text = " ".join(words[self.window_switch_ignore_word_count:])
                else:
                    text = ""

        target_text = prepare_text_for_insert(
            text,
            self.session_pasted_text,
            self._language_code(),
            self._command_pack(),
        )
        self.pending_preview_text = ""
        if not target_text:
            if self.config.get("dictation.live_typing_mode") == "live":
                self.last_raw_text = ""
                self.window_switch_ignore_word_count = 0
            return {"status": "duplicate"}

        self._snapshot()

        if self.input_backend == "tsf" and self.tsf_bridge.send_commit(target_text):
            self.session_pasted_text += target_text
            self.session_interim_text = ""
            self.last_raw_text = ""
            self.window_switch_ignore_word_count = 0
            self._record(
                "final_tsf",
                raw_text=raw_input,
                text=target_text,
                inserted=target_text,
                committed=self.session_pasted_text,
                backend="tsf",
            )
            return {"status": "inserted", "text": target_text, "backend": "tsf"}
        
        if self.config.get("dictation.live_typing_mode") == "live":
            success = self._replace_text(self.session_interim_text, target_text)
            if success:
                self.session_pasted_text += target_text
                self.session_interim_text = ""
                self.last_raw_text = ""
                self.window_switch_ignore_word_count = 0
                self._record(
                    "final",
                    raw_text=raw_input,
                    text=target_text,
                    inserted=target_text,
                    committed=self.session_pasted_text,
                    backend=self._insertion_backend(),
                )
                return {"status": "inserted", "text": target_text, "backend": self._insertion_backend()}
            else:
                return {"status": "target_unavailable", "text": target_text, "backend": "none"}
        else:
            # final_only path: a complete utterance. Prefer clipboard paste for exact Hebrew fidelity
            # (per-char unicode SendInput races under load and corrupts the text in apps like Notepad).
            if not self._insert_text(target_text, prefer_clipboard=True):
                return {"status": "target_unavailable", "text": target_text, "backend": "none"}

            self.session_pasted_text += target_text
            self._record(
                "final",
                raw_text=raw_input,
                text=target_text,
                inserted=target_text,
                committed=self.session_pasted_text,
                backend=self._insertion_backend(),
                )
            return {"status": "inserted", "text": target_text, "backend": self._insertion_backend()}

    def _language_code(self):
        return self.config.get("language_code", "he-IL")

    def _command_pack(self):
        return self.config.get("languages.command_pack", "he")

    def _insertion_backend(self):
        if self.last_insert_backend:
            return self.last_insert_backend
        method = self.config.get("dictation.paste_method", None) or self.config.get("paste_method", None)
        return "clipboard" if method == "clipboard" else "unicode_keyboard"

    def _external_injection_allowed(self) -> bool:
        if self.target_detached:
            logger.info("External injection blocked: target is detached for this session.")
            return False
        if self.target and self.target.is_usable_external():
            return True
        self.target = WindowTarget.capture_best_target()
        return bool(self.target and self.target.is_usable_external())

    def _ensure_target_foreground(self) -> bool:
        if not self._external_injection_allowed():
            logger.info(
                "External injection blocked: no usable external target. target=%s",
                self.target.describe() if self.target else "none",
            )
            return False
        if self.target.ensure_foreground():
            return True
        logger.info("External injection blocked: could not activate target. target=%s", self.target.describe())
        return False

    def _insert_text(self, text: str, prefer_clipboard: bool = False) -> bool:
        if not (self.target and self.target.is_usable_external()):
            self.target = WindowTarget.capture_best_target()
        profile = self.target.profile() if self.target and hasattr(self.target, "profile") else None
        backend_pref = profile.preferred_backend if profile else "unicode_keyboard"
        # Instrumentation: what the backend is about to attempt (the transcript content is logged
        # separately, redaction-aware, by inject_final's caller). Helps diagnose insertion fidelity.
        logger.info("Insert attempt: len=%s prefer_clipboard=%s profile_backend=%s target=%s",
                    len(text), prefer_clipboard, backend_pref,
                    self.target.describe() if self.target else "none")

        # Beta-safe FINAL insertion: clipboard paste is atomic and reproduces Hebrew/Unicode exactly.
        # Per-character unicode SendInput (see _type_unicode_text) races under the load right after
        # offline processing, so Notepad drops/repeats characters (the "זזזזזז" corruption). For a
        # complete final utterance prefer clipboard, except for Word (its COM editor is more precise).
        # Falls through to the existing keyboard/COM backends if the paste fails.
        if prefer_clipboard and backend_pref != "word_com":
            if self._paste_text(text):
                self.last_insert_backend = "clipboard"
                logger.info("Inserted via clipboard paste (backend=clipboard, len=%s).", len(text))
                return True
            logger.warning("Clipboard paste failed for final insertion; falling back to keyboard/COM backends.")

        if profile and profile.preferred_backend == "word_com" and self.word_editor.insert_text(text, self.target):
            self.last_insert_backend = "word_com"
            return True
        if profile and profile.preferred_backend == "unicode_keyboard":
            success = self._type_unicode_text(text)
            if success:
                self.last_insert_backend = "unicode_keyboard"
                return True
        if self.word_editor.insert_text(text, self.target):
            self.last_insert_backend = "word_com"
            return True
        method = self.config.get("dictation.paste_method", None) or self.config.get("paste_method", None)
        if method == "clipboard":
            success = self._paste_text(text)
            if success:
                self.last_insert_backend = "clipboard"
            return success
        success = self._type_unicode_text(text)
        if success:
            self.last_insert_backend = "unicode_keyboard"
        return success

    def _type_unicode_text(self, text: str) -> bool:
        log_transcript(
            logger,
            logging.DEBUG,
            "Typing final text with Unicode keyboard events",
            text,
            self.config.get("debug_log_transcripts", False),
        )
        if not text or not self._ensure_target_foreground() or not user32:
            return False

        try:
            for char in text:
                if self.abort_requested:
                    logger.warning("Typing aborted due to user keyboard intervention.")
                    return False
                if char == "\n":
                    VK_RETURN = 0x0D
                    down = INPUT(
                        type=INPUT_KEYBOARD,
                        union=INPUTUNION(ki=KEYBDINPUT(wVk=VK_RETURN, wScan=0, dwFlags=0, time=0, dwExtraInfo=None)),
                    )
                    up = INPUT(
                        type=INPUT_KEYBOARD,
                        union=INPUTUNION(ki=KEYBDINPUT(wVk=VK_RETURN, wScan=0, dwFlags=KEYEVENTF_KEYUP, time=0, dwExtraInfo=None)),
                    )
                    events = (INPUT * 2)(down, up)
                    user32.SendInput(2, ctypes.byref(events), ctypes.sizeof(INPUT))
                    time.sleep(0.01)
                elif char == "\r":
                    continue
                else:
                    for unit in _utf16_units(char):
                        down = INPUT(
                            type=INPUT_KEYBOARD,
                            union=INPUTUNION(ki=KEYBDINPUT(0, unit, KEYEVENTF_UNICODE, 0, None)),
                        )
                        up = INPUT(
                            type=INPUT_KEYBOARD,
                            union=INPUTUNION(ki=KEYBDINPUT(0, unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, None)),
                        )
                        events = (INPUT * 2)(down, up)
                        sent = user32.SendInput(2, ctypes.byref(events), ctypes.sizeof(INPUT))
                        if sent != 2:
                            logger.warning("Unicode SendInput inserted only %s/2 events.", sent)
                            return False
                        time.sleep(0.001)
            return True
        except Exception as e:
            logger.error("Unicode typing failed: %s", e)
            return False

    def _replace_text(self, old_text: str, new_text: str) -> bool:
        if not self.target:
            self.target = WindowTarget.capture_best_target()

        # Update target in editors
        self.word_editor.set_target(self.target)
        self.uia_editor.set_target(self.target)

        # 1. Try Word COM
        if self.word_editor.replace_session_suffix(old_text, new_text):
            self.last_insert_backend = "word_com"
            return True

        # 2. Try UI Automation
        if self.uia_editor.replace_session_suffix(old_text, new_text):
            self.last_insert_backend = "uia"
            return True

        # 3. Fallback to Keyboard Emulation (SendInput / backspaces)
        rewrite = compute_end_rewrite(old_text, new_text)
        
        self.is_injecting = True
        self.abort_requested = False
        success = True
        
        try:
            if self.abort_requested:
                success = False
            if success and rewrite.chars_to_delete:
                success = success and self._send_backspaces(rewrite.chars_to_delete)
            if success and rewrite.text_to_insert:
                success = success and self._insert_text(rewrite.text_to_insert)
        finally:
            self.is_injecting = False
            self.abort_requested = False

        if success:
            self.last_insert_backend = "unicode_keyboard"
        return success

    def _start_keyboard_hook(self):
        if not user32 or not HOOKPROC:
            return
        t = threading.Thread(target=self._run_hook_loop, name="LowLevelKeyboardHook", daemon=True)
        t.start()

    def _run_hook_loop(self):
        try:
            user32_dll = ctypes.WinDLL("user32", use_last_error=True)
        except Exception:
            logger.error("Failed to load user32 DLL privately.")
            return
        
        def hook_callback(nCode, wParam, lParam):
            if nCode >= 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                if self.is_injecting:
                    flags = lParam.contents.flags
                    is_injected = bool(flags & LLKHF_INJECTED)
                    if not is_injected:
                        logger.warning("Hardware interrupt detected! User pressed a physical key during injection. Aborting sequence.")
                        self.abort_requested = True
            return user32_dll.CallNextHookEx(self._hook_h, nCode, wParam, lParam)

        self._hook_proc = HOOKPROC(hook_callback)
        self._hook_h = user32_dll.SetWindowsHookExW(
            WH_KEYBOARD_LL,
            self._hook_proc,
            None,
            0
        )
        if not self._hook_h:
            logger.error("Failed to install low-level keyboard hook.")
            return
        
        # MSG pump
        msg = wintypes.MSG()
        while user32_dll.GetMessageW(ctypes.byref(msg), 0, 0, 0) != 0:
            user32_dll.TranslateMessage(ctypes.byref(msg))
            user32_dll.DispatchMessageW(ctypes.byref(msg))

    def shutdown(self):
        if self._hook_h:
            try:
                user32_dll = ctypes.WinDLL("user32", use_last_error=True)
                user32_dll.UnhookWindowsHookEx(self._hook_h)
                self._hook_h = None
            except Exception as e:
                logger.error("Failed to unhook low-level keyboard hook: %s", e)

    def _paste_text(self, text: str) -> bool:
        log_transcript(
            logger,
            logging.DEBUG,
            "Pasting final text",
            text,
            self.config.get("debug_log_transcripts", False),
        )
        if not text or not self._ensure_target_foreground():
            return False

        prev_clipboard = None
        restore = self.config.get("restore_clipboard", True)
        if restore:
            try:
                prev_clipboard = pyperclip.paste()
            except Exception as e:
                logger.warning("Failed to read clipboard before paste: %s", e)

        if not copy_without_history(text):
            logger.error("Failed to safely copy text to clipboard. Aborting paste.")
            return False

        try:
            if not self._ensure_target_foreground():
                return False
            with keyboard.pressed(Key.ctrl):
                keyboard.press(vk_v)
                keyboard.release(vk_v)
            time.sleep(0.15)
            return True
        except Exception as e:
            logger.error("Failed to paste text: %s", e)
            return False
        finally:
            if restore and prev_clipboard is not None:
                self._restore_clipboard_later(prev_clipboard, text)

    def _restore_clipboard_later(self, prev_clipboard: str, inserted_text: str):
        try:
            max_restore_len = int(self.config.get("dictation.max_clipboard_restore_chars", 5000))
            if len(prev_clipboard or "") > max_restore_len:
                logger.warning(
                    "Clipboard restore skipped because previous clipboard is too large: previous_len=%s max_restore_len=%s.",
                    len(prev_clipboard or ""),
                    max_restore_len,
                )
                return
            restore_delay = float(self.config.get("dictation.clipboard_restore_delay_seconds", 1.0))
            time.sleep(max(0.0, restore_delay))
            if pyperclip.paste() == inserted_text:
                copy_without_history(prev_clipboard)
        except Exception as e:
            logger.warning("Failed to restore clipboard after paste: %s", e)

    def _send_backspaces(self, count: int) -> bool:
        if count <= 0:
            return True
        if self.abort_requested:
            return False
        if not self._ensure_target_foreground() or not user32:
            return False
        try:
            events_list = []
            for _ in range(count):
                if self.abort_requested:
                    return False
                down = INPUT(
                    type=INPUT_KEYBOARD,
                    union=INPUTUNION(ki=KEYBDINPUT(wVk=VK_BACK, wScan=0, dwFlags=0, time=0, dwExtraInfo=None)),
                )
                up = INPUT(
                    type=INPUT_KEYBOARD,
                    union=INPUTUNION(ki=KEYBDINPUT(wVk=VK_BACK, wScan=0, dwFlags=KEYEVENTF_KEYUP, time=0, dwExtraInfo=None)),
                )
                events_list.append(down)
                events_list.append(up)
            
            n_events = len(events_list)
            events_array = (INPUT * n_events)(*events_list)
            sent = user32.SendInput(n_events, ctypes.byref(events_array), ctypes.sizeof(INPUT))
            if sent != n_events:
                logger.warning("Backspaces SendInput sent only %s/%s events.", sent, n_events)
                return False
            return True
        except Exception as e:
            logger.error("Failed to send backspaces: %s", e)
            return False

    def _press_key(self, key) -> bool:
        if not self._ensure_target_foreground():
            return False
        try:
            keyboard.press(key)
            keyboard.release(key)
            time.sleep(0.05)
            return True
        except Exception as e:
            logger.error("Failed to press key %s: %s", key, e)
            return False

    def _execute_command(self, action: str, args: dict | None = None):
        args = args or {}
        logger.info("Executing voice command: %s", action)

        if action == "stop":
            return {"status": "command", "action": action}
        if action == "send":
            success = self._press_key(Key.enter)
            self._close_editable_scope("send")
            return {"status": "command", "action": action, "success": success}
        if action == "next_field":
            success = self._press_key(Key.tab)
            self._close_editable_scope("next_field")
            return {"status": "command", "action": action, "success": success}
        if action == "undo":
            return self._undo()
        if action == "delete_last_word":
            return self._replace_session_text(delete_last_word_text(self.session_pasted_text), action)
        if action == "delete_last_sentence":
            return self._replace_session_text(delete_last_sentence_text(self.session_pasted_text), action)
        if action == "clear_all":
            return self._replace_session_text("", action)
        if action == "replace_phrase":
            return self._replace_phrase(args.get("old", ""), args.get("new", ""))
        if action == "delete_phrase":
            return self._delete_phrase(args.get("target", ""))
        if action == "select_last_word":
            return self._select_last("word")
        if action == "select_last_sentence":
            return self._select_last("sentence")
        return {"status": "unknown_command", "action": action}

    def _undo(self):
        if not self.history:
            return {"status": "command", "action": "undo", "success": False}
        return self._set_session_text(self.history.pop(), "undo")

    def _replace_phrase(self, old: str, new: str):
        old = (old or "").strip()
        new = (new or "").strip()
        if not old or self.session_pasted_text.count(old) != 1:
            return {"status": "command", "action": "replace_phrase", "success": False}
        self._snapshot()
        if self.input_backend == "tsf" and self.tsf_bridge.send_replace_in_scope(old, new):
            self.session_pasted_text = self.session_pasted_text.replace(old, new, 1)
            return {"status": "command", "action": "replace_phrase", "success": True, "backend": "tsf"}
        return self._set_session_text(self.session_pasted_text.replace(old, new, 1), "replace_phrase")

    def _delete_phrase(self, target: str):
        target = (target or "").strip()
        if not target or self.session_pasted_text.count(target) != 1:
            return {"status": "command", "action": "delete_phrase", "success": False}
        self._snapshot()
        new_text = self.session_pasted_text.replace(target, "", 1)
        new_text = " ".join(new_text.split())
        return self._set_session_text(new_text, "delete_phrase")

    def _select_last(self, unit: str):
        action = f"select_last_{unit}"
        if self.input_backend == "tsf" and self.tsf_bridge.send_select_last(unit):
            return {"status": "command", "action": action, "success": True, "backend": "tsf"}
        return {"status": "command", "action": action, "success": False, "backend": self._insertion_backend()}

    def _replace_session_text(self, new_text: str, action: str):
        if new_text == self.session_pasted_text:
            return {"status": "command", "action": action, "success": False}
        self._snapshot()
        return self._set_session_text(new_text, action)

    def _set_session_text(self, new_text: str, action: str):
        old_text = self.session_pasted_text
        rewrite = compute_end_rewrite(old_text, new_text)
        if rewrite.chars_to_delete and not self._send_backspaces(rewrite.chars_to_delete):
            return {"status": "paste_failed", "action": action}
        if rewrite.text_to_insert and not self._insert_text(rewrite.text_to_insert):
            return {"status": "paste_failed", "action": action}

        self.session_pasted_text = new_text
        self.pending_preview_text = ""
        self._record(
            "command",
            action=action,
            old_text=old_text,
            new_text=new_text,
            deleted=rewrite.chars_to_delete,
            inserted=rewrite.text_to_insert,
            backend=self._insertion_backend(),
        )
        return {"status": "command", "action": action, "success": True, "backend": self._insertion_backend()}

    def _snapshot(self):
        if not self.history or self.history[-1] != self.session_pasted_text:
            self.history.append(self.session_pasted_text)
            self.history = self.history[-20:]

    @staticmethod
    def _len_or_none(value):
        return len(value) if isinstance(value, str) else value

    def _summarize_record_payload(self, payload: dict) -> str:
        fields = []
        for key in ("backend", "reason", "deleted"):
            if key in payload and payload[key] not in (None, ""):
                fields.append(f"{key}={payload[key]}")
        for key in ("raw_text", "text", "inserted", "committed", "session_text", "old_text", "new_text"):
            if key in payload:
                fields.append(f"{key}_len={self._len_or_none(payload[key])}")
        return " ".join(fields)

    def _record(self, event_type: str, **payload):
        payload["type"] = event_type
        payload["session_text"] = self.session_pasted_text
        self.journal.append(payload)
        self.journal = self.journal[-200:]
        logger.info("Injector event: type=%s %s", event_type, self._summarize_record_payload(payload))
