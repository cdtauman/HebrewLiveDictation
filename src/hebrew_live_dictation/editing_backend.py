import logging
import ctypes
import os
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass


logger = logging.getLogger("EditingBackend")


def _is_uipi_mismatch(e: Exception) -> bool:
    hresult = getattr(e, "hresult", None)
    if hresult in (0x80070005, 0x8001011B):
        return True
    args = getattr(e, "args", None)
    if args and isinstance(args, tuple):
        for arg in args:
            if arg in (5, 0x80070005, 0x8001011B):
                return True
            if isinstance(arg, str) and ("access is denied" in arg.lower() or "0x80070005" in arg or "0x8001011b" in arg.lower()):
                return True
    err_str = str(e).lower()
    if "access is denied" in err_str or "0x80070005" in err_str or "0x8001011b" in err_str or "unauthorized" in err_str:
        return True
    return False



@dataclass(frozen=True)
class TargetProfile:
    name: str
    process_names: tuple[str, ...]
    preferred_backend: str
    supports_suffix_replace: bool
    notes: str = ""


TARGET_PROFILES = (
    TargetProfile("word", ("winword.exe",), "word_com", True),
    TargetProfile("notepad", ("notepad.exe",), "unicode_keyboard", True),
    TargetProfile("chrome", ("chrome.exe", "msedge.exe", "firefox.exe"), "unicode_keyboard", False),
    TargetProfile("electron", ("code.exe", "teams.exe", "slack.exe", "discord.exe"), "unicode_keyboard", False),
)


def profile_for_process(process_name: str) -> TargetProfile:
    normalized = (process_name or "").lower()
    for profile in TARGET_PROFILES:
        if normalized in profile.process_names:
            return profile
    return TargetProfile("generic", (normalized,), "unicode_keyboard", True)


BLOCKED_TARGET_PROCESSES = {
    "searchhost.exe",
    "searchapp.exe",
    "startmenuexperiencehost.exe",
    "shellexperiencehost.exe",
    "textinputhost.exe",
    "applicationframehost.exe",
}

GW_HWNDNEXT = 2
GA_ROOT = 2
EVENT_SYSTEM_FOREGROUND = 0x0003
WINEVENT_OUTOFCONTEXT = 0x0000
WINEVENT_SKIPOWNPROCESS = 0x0002
WinEventProc = ctypes.WINFUNCTYPE(
    None,
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.HWND,
    wintypes.LONG,
    wintypes.LONG,
    wintypes.DWORD,
    wintypes.DWORD,
)


def _process_info_for_hwnd(hwnd: int) -> tuple[int, str]:
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        if not hwnd:
            return 0, ""

        process_id = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        if not process_id.value:
            return 0, ""

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, process_id.value)
        if not handle:
            return int(process_id.value), ""

        try:
            buffer = ctypes.create_unicode_buffer(32768)
            size = ctypes.c_ulong(len(buffer))
            if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return int(process_id.value), os.path.basename(buffer.value).lower()
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return 0, ""
    return 0, ""


def _process_name_for_hwnd(hwnd: int) -> str:
    return _process_info_for_hwnd(hwnd)[1]


def _window_text(hwnd: int) -> str:
    try:
        user32 = ctypes.windll.user32
        length = user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, len(buffer))
        return buffer.value
    except Exception:
        return ""


def _foreground_hwnd() -> int:
    try:
        return int(ctypes.windll.user32.GetForegroundWindow())
    except Exception:
        return 0


def _foreground_process_name() -> str:
    return _process_name_for_hwnd(_foreground_hwnd())


def _is_top_level_visible_window(hwnd: int) -> bool:
    if not hwnd:
        return False
    try:
        user32 = ctypes.windll.user32
        if not user32.IsWindow(hwnd) or not user32.IsWindowVisible(hwnd):
            return False
        root = user32.GetAncestor(hwnd, GA_ROOT)
        return not root or int(root) == int(hwnd)
    except Exception:
        return False


class WindowTarget:
    SW_RESTORE = 9
    REMEMBERED_TARGET_MAX_AGE_SECONDS = 30.0
    _last_external = None
    _tracker_started = False
    _tracker_lock = threading.Lock()
    _event_hook = None
    _event_callback = None

    def __init__(
        self,
        hwnd: int = 0,
        process_id: int = 0,
        process_name: str = "",
        title: str = "",
        captured_at: float | None = None,
    ):
        self.hwnd = int(hwnd or 0)
        self.process_id = int(process_id or 0)
        self.process_name = process_name or ""
        self.title = title or ""
        self.captured_at = captured_at if captured_at is not None else time.monotonic()

    @classmethod
    def capture_window(cls, hwnd: int):
        process_id, process_name = _process_info_for_hwnd(hwnd)
        return cls(hwnd, process_id, process_name, _window_text(hwnd), time.monotonic())

    @classmethod
    def capture_foreground(cls):
        target = cls.capture_window(_foreground_hwnd())
        cls.remember_if_external(target)
        return target

    @classmethod
    def capture_best_target(cls):
        foreground = cls.capture_foreground()
        if foreground.is_usable_external():
            return foreground
        z_order_target = cls.capture_next_external_window_after(foreground.hwnd)
        if z_order_target:
            logger.info(
                "Using z-order external target instead of foreground target: foreground=%s target=%s",
                foreground.describe(),
                z_order_target.describe(),
            )
            cls.remember_if_external(z_order_target)
            return z_order_target
        remembered = cls.last_external()
        if remembered and remembered.is_fresh() and remembered.is_usable_external():
            logger.info("Using remembered external target instead of foreground target: foreground=%s remembered=%s", foreground.describe(), remembered.describe())
            return remembered
        return foreground

    @classmethod
    def capture_next_external_window_after(cls, hwnd: int, limit: int = 80):
        if not hwnd:
            return None
        try:
            user32 = ctypes.windll.user32
            candidate_hwnd = user32.GetWindow(hwnd, GW_HWNDNEXT)
            checked = 0
            while candidate_hwnd and checked < limit:
                checked += 1
                if _is_top_level_visible_window(candidate_hwnd):
                    target = cls.capture_window(candidate_hwnd)
                    if target.is_usable_external():
                        return target
                candidate_hwnd = user32.GetWindow(candidate_hwnd, GW_HWNDNEXT)
        except Exception as e:
            logger.debug("Could not inspect z-order targets: %s", e)
        return None

    @classmethod
    def remember_if_external(cls, target):
        if target and target.is_usable_external():
            with cls._tracker_lock:
                cls._last_external = target

    @classmethod
    def last_external(cls):
        with cls._tracker_lock:
            return cls._last_external

    @classmethod
    def start_tracker(cls, interval_seconds: float = 0.25):
        with cls._tracker_lock:
            if cls._tracker_started:
                return
            cls._tracker_started = True

        cls._install_foreground_event_hook()

        def track():
            while True:
                try:
                    cls.capture_foreground()
                except Exception:
                    pass
                time.sleep(interval_seconds)

        thread = threading.Thread(target=track, name="WindowTargetTracker", daemon=True)
        thread.start()

    @classmethod
    def _install_foreground_event_hook(cls):
        try:
            user32 = ctypes.windll.user32

            def on_foreground_change(hook, event, hwnd, object_id, child_id, event_thread, event_time):
                if event != EVENT_SYSTEM_FOREGROUND or object_id != 0 or not hwnd:
                    return
                try:
                    cls.remember_if_external(cls.capture_window(hwnd))
                except Exception:
                    pass

            cls._event_callback = WinEventProc(on_foreground_change)
            cls._event_hook = user32.SetWinEventHook(
                EVENT_SYSTEM_FOREGROUND,
                EVENT_SYSTEM_FOREGROUND,
                0,
                cls._event_callback,
                0,
                0,
                WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS,
            )
            if cls._event_hook:
                logger.info("Foreground window event hook installed.")
            else:
                logger.info("Foreground window event hook was not installed; polling fallback remains active.")
        except Exception as e:
            logger.info("Foreground window event hook unavailable: %s", e)

    def is_valid(self) -> bool:
        if not self.hwnd:
            return False
        try:
            return bool(ctypes.windll.user32.IsWindow(self.hwnd))
        except Exception:
            return False

    def is_responsive(self) -> bool:
        if not self.hwnd:
            return False
        try:
            user32 = ctypes.windll.user32
            if hasattr(user32, "IsHungAppWindow") and user32.IsHungAppWindow(self.hwnd):
                logger.warning("Target window is hung/unresponsive (IsHungAppWindow): %s", self.describe())
                return False
            dwResult = ctypes.c_ulong()
            result = user32.SendMessageTimeoutW(
                self.hwnd,
                0,  # WM_NULL
                0,
                0,
                2,  # SMTO_ABORTIFHUNG
                50, # 50 ms timeout
                ctypes.byref(dwResult)
            )
            if not result:
                logger.warning("Target window failed responsiveness check (SendMessageTimeout): %s", self.describe())
                return False
            return True
        except Exception as e:
            logger.debug("Error checking window responsiveness: %s", e)
            return True

    def is_blocked_system_target(self) -> bool:
        return (self.process_name or "").lower() in BLOCKED_TARGET_PROCESSES

    def is_foreground(self) -> bool:
        return self.is_valid() and _foreground_hwnd() == self.hwnd

    def is_fresh(self) -> bool:
        return time.monotonic() - self.captured_at <= self.REMEMBERED_TARGET_MAX_AGE_SECONDS

    def activate(self) -> bool:
        if not self.is_valid():
            return False
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            user32.ShowWindow(self.hwnd, self.SW_RESTORE)
            if user32.SetForegroundWindow(self.hwnd) and self.is_foreground():
                return True

            current_thread = kernel32.GetCurrentThreadId()
            foreground_hwnd = _foreground_hwnd()
            foreground_thread = user32.GetWindowThreadProcessId(foreground_hwnd, None) if foreground_hwnd else 0
            target_thread = user32.GetWindowThreadProcessId(self.hwnd, None)
            attached_foreground = False
            attached_target = False
            try:
                if foreground_thread and foreground_thread != current_thread:
                    attached_foreground = bool(user32.AttachThreadInput(current_thread, foreground_thread, True))
                if target_thread and target_thread != current_thread:
                    attached_target = bool(user32.AttachThreadInput(current_thread, target_thread, True))
                user32.BringWindowToTop(self.hwnd)
                user32.SetForegroundWindow(self.hwnd)
                user32.SetFocus(self.hwnd)
                return self.is_foreground()
            finally:
                if attached_target:
                    user32.AttachThreadInput(current_thread, target_thread, False)
                if attached_foreground:
                    user32.AttachThreadInput(current_thread, foreground_thread, False)
        except Exception:
            return False

    def ensure_foreground(self) -> bool:
        if self.is_foreground():
            return True
        return self.activate()

    def is_current_process(self) -> bool:
        return bool(self.process_id) and self.process_id == os.getpid()

    def is_usable_external(self) -> bool:
        return self.is_valid() and not self.is_current_process() and not self.is_blocked_system_target()

    def describe(self) -> str:
        if not self.hwnd:
            return "no_target"
        return f"hwnd={self.hwnd} pid={self.process_id or 'unknown'} process={self.process_name or 'unknown'} title={self.title or ''}"

    def profile(self) -> TargetProfile:
        return profile_for_process(self.process_name)


class WordCOMEditor:
    wd_character = 1
    wd_move = 0
    wd_extend = 1
    wd_collapse_end = 0

    def __init__(self):
        self.available = False
        self._client = None
        self._last_failure_reason = ""
        self.target = None
        try:
            import comtypes.client  # type: ignore

            self._client = comtypes.client
            self.available = True
        except Exception as e:
            self._last_failure_reason = f"word_com_unavailable:{e}"
            logger.debug("Word COM backend unavailable: %s", e)

    def set_target(self, target):
        self.target = target

    def insert_text(self, text: str, target=None) -> bool:
        if not text:
            return True
        if not self.available:
            self._last_failure_reason = "word_com_unavailable"
            return False
        target = target or self.target
        if target and hasattr(target, "is_usable_external") and not target.is_usable_external():
            self._last_failure_reason = "target_unavailable"
            return False
        if target and hasattr(target, "is_responsive") and not target.is_responsive():
            self._last_failure_reason = "target_unresponsive"
            return False
        if target and getattr(target, "process_name", "") and target.process_name != "winword.exe":
            self._last_failure_reason = "target_not_word"
            return False

        try:
            word = self._client.GetActiveObject("Word.Application")
            selection = word.Selection
            if selection is None:
                self._last_failure_reason = "word_no_selection"
                return False
            selection.TypeText(text)
            self._last_failure_reason = ""
            logger.info("Inserted final text through Word COM.")
            return True
        except Exception as e:
            if _is_uipi_mismatch(e):
                self._last_failure_reason = "uipi_privilege_mismatch"
                logger.warning("UIPI Privilege Mismatch detected: Target application is running elevated (Admin). Word COM access denied. error=%s", e)
            else:
                self._last_failure_reason = f"word_com_insert_exception:{type(e).__name__}"
                logger.info("Word COM final insert failed: %s", e)
            return False

    def append_or_replace_suffix(self, committed_suffix: str, preview_suffix: str, new_preview: str) -> bool:
        expected_suffix = (committed_suffix or "") + (preview_suffix or "")
        replacement_suffix = (committed_suffix or "") + (new_preview or "")
        return self.replace_focused_suffix(expected_suffix, replacement_suffix)

    def replace_session_suffix(self, old_session_text: str, new_session_text: str) -> bool:
        if not old_session_text:
            return False
        return self.replace_focused_suffix(old_session_text, new_session_text)

    def replace_focused_suffix(self, old_suffix: str, new_suffix: str) -> bool:
        if not self.available:
            self._last_failure_reason = "word_com_unavailable"
            return False
        if self.target and self.target.process_name != "winword.exe":
            self._last_failure_reason = "target_not_word"
            return False
        if self.target and hasattr(self.target, "is_responsive") and not self.target.is_responsive():
            self._last_failure_reason = "target_unresponsive"
            return False
        if self.target and not self.target.ensure_foreground():
            self._last_failure_reason = "target_activation_failed"
            return False
        if _foreground_process_name() != "winword.exe":
            self._last_failure_reason = "foreground_not_word"
            return False

        try:
            word = self._client.GetActiveObject("Word.Application")
            selection = word.Selection
            if selection is None:
                self._last_failure_reason = "word_no_selection"
                return False

            old_suffix = old_suffix or ""
            if old_suffix:
                end = int(selection.End)
                try:
                    story_start = int(selection.StoryRange.Start)
                except Exception:
                    story_start = 0
                start = max(story_start, end - len(old_suffix))
                target_range = selection.Document.Range(Start=start, End=end)
                selected_text = target_range.Text
                if selected_text != old_suffix:
                    selection.SetRange(Start=end, End=end)
                    self._last_failure_reason = "word_suffix_mismatch"
                    logger.info(
                        "Word COM edit unavailable: suffix mismatch (selected_len=%s expected_len=%s).",
                        len(selected_text or ""),
                        len(old_suffix),
                    )
                    return False
                target_range.Text = new_suffix or ""
                new_end = target_range.End
                selection.SetRange(Start=new_end, End=new_end)
            else:
                selection.TypeText(new_suffix or "")
            self._last_failure_reason = ""
            logger.info("Updated text through Word COM range replacement.")
            return True
        except Exception as e:
            if _is_uipi_mismatch(e):
                self._last_failure_reason = "uipi_privilege_mismatch"
                logger.warning("UIPI Privilege Mismatch detected: Target application is running elevated (Admin). Word COM access denied. error=%s", e)
            else:
                self._last_failure_reason = f"word_com_exception:{type(e).__name__}"
                logger.info("Word COM edit attempt failed: %s", e)
            return False

    def focused_control_description(self) -> str:
        if not self.available:
            return "word_com_unavailable"
        foreground = _foreground_process_name()
        if foreground != "winword.exe":
            return f"foreground:{foreground or 'unknown'}"
        return "WordCOM:Selection"

    def last_failure_reason(self) -> str:
        return self._last_failure_reason

    def focused_control_diagnostics(self) -> dict:
        return {
            "available": self.available,
            "focused_control": self.focused_control_description(),
            "last_failure": self._last_failure_reason,
            "foreground_process": _foreground_process_name(),
        }


class UIAutomationEditor:
    def __init__(self):
        self.available = False
        self._automation = None
        self._last_failure_reason = ""
        self.target = None
        try:
            import uiautomation as automation  # type: ignore

            self._automation = automation
            self.available = True
        except Exception as e:
            self._last_failure_reason = f"uia_unavailable:{e}"
            logger.debug(f"UI Automation backend unavailable: {e}")

    def set_target(self, target):
        self.target = target

    def replace_session_suffix(self, old_session_text: str, new_session_text: str) -> bool:
        if not old_session_text:
            return False
        return self.replace_focused_suffix(old_session_text, new_session_text)

    def replace_focused_suffix(self, old_suffix: str, new_suffix: str) -> bool:
        if not self.available:
            self._last_failure_reason = "uia_unavailable"
            return False
        if self.target and hasattr(self.target, "is_responsive") and not self.target.is_responsive():
            self._last_failure_reason = "target_unresponsive"
            return False
        if self.target and not self.target.ensure_foreground():
            self._last_failure_reason = "target_activation_failed"
            return False

        try:
            control = self._automation.GetFocusedControl()
            if not control:
                self._last_failure_reason = "no_focused_control"
                return False

            value_pattern = control.GetValuePattern()
            if not value_pattern:
                self._last_failure_reason = "focused_control_has_no_value_pattern"
                logger.info(
                    "UIA edit unavailable: no ValuePattern on focused control (%s).",
                    self.focused_control_description(),
                )
                return False

            current_value = value_pattern.Value
            if not isinstance(current_value, str) or not current_value.endswith(old_suffix):
                current_len = len(current_value) if isinstance(current_value, str) else None
                self._last_failure_reason = "focused_value_suffix_mismatch"
                logger.info(
                    "UIA edit unavailable: suffix mismatch on focused control (%s, current_len=%s, expected_suffix_len=%s).",
                    self.focused_control_description(),
                    current_len,
                    len(old_suffix or ""),
                )
                return False

            prefix = current_value[: -len(old_suffix)] if old_suffix else current_value
            value_pattern.SetValue(prefix + new_suffix)
            self._last_failure_reason = ""
            logger.info("Updated text through UI Automation ValuePattern.")
            return True
        except Exception as e:
            if _is_uipi_mismatch(e):
                self._last_failure_reason = "uipi_privilege_mismatch"
                logger.warning("UIPI Privilege Mismatch detected: Target application is running elevated (Admin). UI Automation access denied. error=%s", e)
            else:
                self._last_failure_reason = f"uia_exception:{type(e).__name__}"
                logger.debug(f"UI Automation edit attempt failed: {e}")
            return False

    def append_or_replace_suffix(self, committed_suffix: str, preview_suffix: str, new_preview: str) -> bool:
        expected_suffix = (committed_suffix or "") + (preview_suffix or "")
        replacement_suffix = (committed_suffix or "") + (new_preview or "")
        return self.replace_focused_suffix(expected_suffix, replacement_suffix)

    def focused_control_description(self) -> str:
        if not self.available:
            return "uia_unavailable"
        try:
            control = self._automation.GetFocusedControl()
            if not control:
                return "no_focused_control"
            name = getattr(control, "Name", "") or ""
            control_type = getattr(control, "ControlTypeName", "") or control.__class__.__name__
            return f"{control_type}:{name}".strip(":")
        except Exception as e:
            return f"uia_error:{e}"

    def last_failure_reason(self) -> str:
        return self._last_failure_reason

    def focused_control_diagnostics(self) -> dict:
        diagnostics = {
            "available": self.available,
            "last_failure": self._last_failure_reason,
        }
        if not self.available:
            return diagnostics

        try:
            control = self._automation.GetFocusedControl()
            if not control:
                diagnostics["focused_control"] = "none"
                return diagnostics

            diagnostics.update(
                {
                    "focused_control": self.focused_control_description(),
                    "class_name": getattr(control, "ClassName", "") or "",
                    "automation_id": getattr(control, "AutomationId", "") or "",
                    "process_id": getattr(control, "ProcessId", "") or "",
                    "has_value_pattern": bool(control.GetValuePattern()),
                    "has_text_pattern": bool(control.GetTextPattern()),
                }
            )

            get_text_edit_pattern = getattr(control, "GetTextEditPattern", None)
            if callable(get_text_edit_pattern):
                diagnostics["has_text_edit_pattern"] = bool(get_text_edit_pattern())
        except Exception as e:
            diagnostics["diagnostic_error"] = f"{type(e).__name__}:{e}"
        return diagnostics
