import logging
from pynput import keyboard

logger = logging.getLogger("Hotkeys")

COPILOT_HOTKEY = "copilot"
VK_C = 0x43
VK_F23 = 0x86
VK_LWIN = 0x5B
VK_RWIN = 0x5C
KEYDOWN_MESSAGES = {256, 260}  # WM_KEYDOWN, WM_SYSKEYDOWN
KEYUP_MESSAGES = {257, 261}  # WM_KEYUP, WM_SYSKEYUP
LLKHF_UP = 0x80

def canonical_key_name(key):
    """
    Normalizes a pynput key object into a clean string representation.
    """
    if key is None:
        return None
        
    # Check for special keys (e.g., ctrl, alt, shift, cmd/win)
    if isinstance(key, keyboard.Key):
        name = key.name
        if name.startswith('ctrl'):
            return 'ctrl'
        if name.startswith('alt'):
            return 'alt'
        if name.startswith('shift'):
            return 'shift'
        if name.startswith('cmd') or name.startswith('win'):
            return 'win'
        return name  # e.g., 'space', 'enter', 'esc'
        
    # Check for alphanumeric keys
    if hasattr(key, 'char') and key.char is not None:
        if key.char == ' ':
            return 'space'
        return key.char.lower()
        
    # Virtual key codes (fallback)
    if hasattr(key, 'vk') and key.vk is not None:
        if key.vk == 32:
            return 'space'
        if key.vk == VK_F23:
            return 'f23'
        if 112 <= key.vk <= 135:
            return f"f{key.vk - 111}"
        return f"vk_{key.vk}"
        
    return str(key).lower()

def parse_hotkey_string(hotkey_str: str) -> set:
    """
    Parses a hotkey string (like '<ctrl>+<alt>+space') into a set of canonical key names.
    """
    if not hotkey_str:
        return set()

    parts = hotkey_str.lower().split('+')
    target_keys = set()
    for part in parts:
        part = part.strip()
        # Remove brackets if present: '<ctrl>' -> 'ctrl'
        if part.startswith('<') and part.endswith('>'):
            part = part[1:-1]
        if part in ('control', 'ctrl'):
            part = 'ctrl'
        elif part in ('command', 'win', 'cmd', 'meta'):
            part = 'win'
        elif part in ('copilot', 'copilot key'):
            part = COPILOT_HOTKEY
        target_keys.add(part)

    if 'f23' in target_keys or COPILOT_HOTKEY in target_keys:
        return {COPILOT_HOTKEY}

    return target_keys

def check_hotkey_conflict(hotkey_str: str) -> bool:
    """
    Checks if the given hotkey is already registered by another application globally.
    Returns True if there is a conflict.
    """
    import ctypes
    user32 = ctypes.windll.user32

    if COPILOT_HOTKEY in parse_hotkey_string(hotkey_str):
        return False
    
    parts = hotkey_str.lower().split('+')
    mod = 0
    vk = 0
    for p in parts:
        p = p.strip()
        if p == 'ctrl': mod |= 0x0002
        elif p == 'alt': mod |= 0x0001
        elif p == 'shift': mod |= 0x0004
        elif p in ('win', 'meta', 'cmd'): mod |= 0x0008
        else:
            if hasattr(keyboard.Key, p):
                vk = getattr(keyboard.Key, p).value.vk
            elif len(p) == 1:
                vk = user32.VkKeyScanW(ord(p)) & 0xFF
            elif p.startswith('f') and p[1:].isdigit():
                vk = 0x6F + int(p[1:])
    
    if not vk:
        return False # Can't check
        
    hotkey_id = 9999
    success = user32.RegisterHotKey(None, hotkey_id, mod, vk)
    if success:
        user32.UnregisterHotKey(None, hotkey_id)
        return False
    return True

class HotkeyListener:
    def __init__(self, config, on_start_requested, on_stop_requested):
        self.config = config
        self.on_start_requested = on_start_requested
        self.on_stop_requested = on_stop_requested
        
        self.hotkey_str = self.config.get("hotkey", "<ctrl>+<alt>+space")
        self.mode = self.config.get("mode", "push_to_talk")
        
        self.target_keys = parse_hotkey_string(self.hotkey_str)
        logger.info(f"Target hotkey set: {self.target_keys} (Mode: {self.mode})")
        
        self.current_pressed = set()
        self.hotkey_active = False
        self.listener = None
        self.listening_state = False  # Track if app thinks it's recording (for toggle mode)

    def update_settings(self):
        """Re-loads settings in case the hotkey or mode changed."""
        self.hotkey_str = self.config.get("hotkey", "<ctrl>+<alt>+space")
        self.mode = self.config.get("mode", "push_to_talk")
        self.target_keys = parse_hotkey_string(self.hotkey_str)
        self.current_pressed.clear()
        self.hotkey_active = False
        logger.info(f"Updated hotkey set: {self.target_keys} (Mode: {self.mode})")

    def _win32_event_filter(self, msg, data):
        vk_code = getattr(data, 'vkCode', None)

        if vk_code in (VK_LWIN, VK_RWIN):
            if self._is_keyup_event(msg, data):
                self.current_pressed.discard('win')
            else:
                self.current_pressed.add('win')
            return True

        if vk_code == VK_C and self._uses_copilot_key() and 'win' in self.current_pressed:
            self._handle_direct_hotkey_event(msg, data, "Win+C Copilot")
            self.listener.suppress_event()
            return True

        # Copilot keyboards commonly emit Win+Shift+F23. When that key is the
        # configured shortcut, suppress F23 so Windows Copilot does not open.
        if vk_code == VK_F23:
            if self._uses_copilot_key():
                self._handle_direct_hotkey_event(msg, data, "F23 Copilot")
                self.listener.suppress_event()
        return True

    def _uses_copilot_key(self):
        return COPILOT_HOTKEY in self.target_keys

    def _handle_direct_hotkey_event(self, msg, data=None, label="hotkey"):
        if self._is_keyup_event(msg, data):
            logger.info("%s up detected (msg=%r, flags=%r).", label, msg, getattr(data, 'flags', None))
            self.current_pressed.discard(COPILOT_HOTKEY)
            if self.hotkey_active:
                self.hotkey_active = False
                self._handle_hotkey_up()
            return

        logger.info("%s down detected (msg=%r, flags=%r).", label, msg, getattr(data, 'flags', None))
        self.current_pressed.add(COPILOT_HOTKEY)
        if not self.hotkey_active:
            self.hotkey_active = True
            self._handle_hotkey_down()

    def _message_code(self, msg):
        if isinstance(msg, int):
            return msg
        value = getattr(msg, 'value', None)
        if isinstance(value, int):
            return value
        try:
            return int(msg)
        except (TypeError, ValueError):
            return None

    def _is_keyup_event(self, msg, data=None):
        code = self._message_code(msg)
        if code in KEYUP_MESSAGES:
            return True
        if code in KEYDOWN_MESSAGES:
            return False
        flags = getattr(data, 'flags', 0) if data is not None else 0
        return bool(flags & LLKHF_UP)

    def _handle_suppressed_key(self, msg, key_name, data=None):
        if self._is_keyup_event(msg, data):
            if key_name == COPILOT_HOTKEY:
                logger.info("Copilot key up detected (msg=%r, flags=%r).", msg, getattr(data, 'flags', None))
            self.current_pressed.discard(key_name)
            self._deactivate_if_needed()
        else:
            if key_name == COPILOT_HOTKEY:
                logger.info("Copilot key down detected (msg=%r, flags=%r).", msg, getattr(data, 'flags', None))
            self.current_pressed.add(key_name)
            self._activate_if_needed()

    def _activate_if_needed(self):
        if not self.target_keys:
            return
        if self.target_keys.issubset(self.current_pressed):
            if not self.hotkey_active:
                self.hotkey_active = True
                logger.info(f"Hotkey combination {self.target_keys} pressed down.")
                logger.debug(f"Hotkey combination {self.target_keys} pressed down.")
                self._handle_hotkey_down()

    def _deactivate_if_needed(self):
        if self.hotkey_active and not self.target_keys.issubset(self.current_pressed):
            self.hotkey_active = False
            logger.debug(f"Hotkey combination {self.target_keys} released.")
            self._handle_hotkey_up()

    def start(self):
        self.listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
            win32_event_filter=self._win32_event_filter
        )
        self.listener.start()
        logger.info("Hotkey listener started.")

    def stop(self):
        if self.listener:
            self.listener.stop()
            self.listener = None
        logger.info("Hotkey listener stopped.")

    def set_listening_state(self, state: bool):
        """Updates the listening state so toggle mode can track it correctly."""
        self.listening_state = state

    def _on_press(self, key):
        name = canonical_key_name(key)
        name = self._normalize_pressed_key(name)
        if name:
            self.current_pressed.add(name)
        self._activate_if_needed()

    def _on_release(self, key):
        name = canonical_key_name(key)
        name = self._normalize_pressed_key(name)
        if name and name in self.current_pressed:
            self.current_pressed.remove(name)
        self._deactivate_if_needed()

    def _normalize_pressed_key(self, name):
        if not name:
            return name
        if self._uses_copilot_key():
            if name == 'f23':
                return COPILOT_HOTKEY
            if name == 'c' and 'win' in self.current_pressed:
                return COPILOT_HOTKEY
        return name

    def _handle_hotkey_down(self):
        if self.mode == "push_to_talk":
            self.on_start_requested()
        elif self.mode == "toggle":
            if self.listening_state:
                self.on_stop_requested()
            else:
                self.on_start_requested()

    def _handle_hotkey_up(self):
        if self.mode == "push_to_talk":
            self.on_stop_requested()
        # In toggle mode, releasing the keys does nothing.
