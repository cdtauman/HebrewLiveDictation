import unittest

from hebrew_live_dictation.hotkeys import (
    COPILOT_HOTKEY,
    HotkeyListener,
    VK_F23,
    canonical_key_name,
    parse_hotkey_string,
)


class HotkeyTests(unittest.TestCase):
    def test_copilot_hotkey_alias_parses(self):
        self.assertEqual(parse_hotkey_string("copilot"), {COPILOT_HOTKEY})

    def test_f23_sequence_is_treated_as_copilot_key(self):
        self.assertEqual(parse_hotkey_string("meta+shift+f23"), {COPILOT_HOTKEY})
        self.assertEqual(parse_hotkey_string("f23"), {COPILOT_HOTKEY})

    def test_f23_virtual_key_is_named(self):
        class Key:
            char = None
            vk = VK_F23

        self.assertEqual(canonical_key_name(Key()), "f23")

    def test_suppressed_copilot_key_drives_push_to_talk(self):
        class Config:
            def get(self, key, default=None):
                return {"hotkey": COPILOT_HOTKEY, "mode": "push_to_talk"}.get(key, default)

        events = []
        listener = HotkeyListener(
            Config(),
            on_start_requested=lambda: events.append("start"),
            on_stop_requested=lambda: events.append("stop"),
        )

        listener._handle_suppressed_key(256, COPILOT_HOTKEY)
        listener._handle_suppressed_key(257, COPILOT_HOTKEY)

        self.assertEqual(events, ["start", "stop"])

    def test_legacy_meta_shift_f23_config_drives_toggle(self):
        class Config:
            def get(self, key, default=None):
                return {"hotkey": "meta+shift+f23", "mode": "toggle"}.get(key, default)

        events = []
        listener = HotkeyListener(
            Config(),
            on_start_requested=lambda: events.append("start"),
            on_stop_requested=lambda: events.append("stop"),
        )

        listener._handle_suppressed_key(256, COPILOT_HOTKEY)

        self.assertEqual(events, ["start"])

    def test_suppressed_f23_starts_even_with_unexpected_message_code(self):
        class Config:
            def get(self, key, default=None):
                return {"hotkey": COPILOT_HOTKEY, "mode": "toggle"}.get(key, default)

        events = []
        listener = HotkeyListener(
            Config(),
            on_start_requested=lambda: events.append("start"),
            on_stop_requested=lambda: events.append("stop"),
        )

        listener._handle_suppressed_key("unexpected", COPILOT_HOTKEY)

        self.assertEqual(events, ["start"])

    def test_direct_copilot_event_does_not_require_pressed_key_subset(self):
        class Config:
            def get(self, key, default=None):
                return {"hotkey": "meta+shift+f23", "mode": "toggle"}.get(key, default)

        events = []
        listener = HotkeyListener(
            Config(),
            on_start_requested=lambda: events.append("start"),
            on_stop_requested=lambda: events.append("stop"),
        )
        listener.current_pressed.clear()

        listener._handle_direct_hotkey_event(256, label="test")

        self.assertEqual(events, ["start"])

    def test_direct_copilot_event_stops_push_to_talk_on_release(self):
        class Config:
            def get(self, key, default=None):
                return {"hotkey": "f23", "mode": "push_to_talk"}.get(key, default)

        events = []
        listener = HotkeyListener(
            Config(),
            on_start_requested=lambda: events.append("start"),
            on_stop_requested=lambda: events.append("stop"),
        )

        listener._handle_direct_hotkey_event(256, label="test")
        listener._handle_direct_hotkey_event(257, label="test")

        self.assertEqual(events, ["start", "stop"])

    def test_win32_filter_starts_before_suppress_event_raises(self):
        class Config:
            def get(self, key, default=None):
                return {"hotkey": "f23", "mode": "toggle"}.get(key, default)

        class Data:
            vkCode = VK_F23
            flags = 0

        class SuppressionRaised(Exception):
            pass

        class Listener:
            def suppress_event(self):
                raise SuppressionRaised()

        events = []
        listener = HotkeyListener(
            Config(),
            on_start_requested=lambda: events.append("start"),
            on_stop_requested=lambda: events.append("stop"),
        )
        listener.listener = Listener()

        with self.assertRaises(SuppressionRaised):
            listener._win32_event_filter(256, Data())

        self.assertEqual(events, ["start"])

    def test_copilot_accepts_f23_from_normal_press_path(self):
        class Config:
            def get(self, key, default=None):
                return {"hotkey": COPILOT_HOTKEY, "mode": "toggle"}.get(key, default)

        class F23Key:
            char = None
            vk = VK_F23

        events = []
        listener = HotkeyListener(
            Config(),
            on_start_requested=lambda: events.append("start"),
            on_stop_requested=lambda: events.append("stop"),
        )

        listener._on_press(F23Key())

        self.assertEqual(events, ["start"])

    def test_copilot_accepts_win_c_from_normal_press_path(self):
        class Config:
            def get(self, key, default=None):
                return {"hotkey": COPILOT_HOTKEY, "mode": "toggle"}.get(key, default)

        class CKey:
            char = "c"
            vk = None

        events = []
        listener = HotkeyListener(
            Config(),
            on_start_requested=lambda: events.append("start"),
            on_stop_requested=lambda: events.append("stop"),
        )
        listener.current_pressed.add("win")

        listener._on_press(CKey())

        self.assertEqual(events, ["start"])


    def test_pause_hotkey_toggles_via_normal_press_path(self):
        class Config:
            def get(self, key, default=None):
                return {"hotkey": "f8", "mode": "toggle", "hotkeys.pause_hotkey": "f9"}.get(key, default)

        class F9:
            char = None
            vk = 120  # F9

        events = []
        listener = HotkeyListener(
            Config(),
            on_start_requested=lambda: events.append("start"),
            on_stop_requested=lambda: events.append("stop"),
            on_pause_requested=lambda: events.append("pause"),
        )

        listener._on_press(F9())
        listener._on_release(F9())
        listener._on_press(F9())

        self.assertEqual(events, ["pause", "pause"])

    def test_no_pause_hotkey_means_no_pause_events(self):
        class Config:
            def get(self, key, default=None):
                return {"hotkey": "f8", "mode": "toggle"}.get(key, default)

        class F9:
            char = None
            vk = 120

        events = []
        listener = HotkeyListener(
            Config(),
            on_start_requested=lambda: events.append("start"),
            on_stop_requested=lambda: events.append("stop"),
            on_pause_requested=lambda: events.append("pause"),
        )

        listener._on_press(F9())
        self.assertEqual(events, [])  # f9 is not the main hotkey and no pause hotkey set

    def test_main_hotkey_still_works_alongside_pause_hotkey(self):
        class Config:
            def get(self, key, default=None):
                return {"hotkey": "f8", "mode": "toggle", "hotkeys.pause_hotkey": "f9"}.get(key, default)

        class F8:
            char = None
            vk = 119  # F8

        events = []
        listener = HotkeyListener(
            Config(),
            on_start_requested=lambda: events.append("start"),
            on_stop_requested=lambda: events.append("stop"),
            on_pause_requested=lambda: events.append("pause"),
        )

        listener._on_press(F8())
        self.assertEqual(events, ["start"])


if __name__ == "__main__":
    unittest.main()
