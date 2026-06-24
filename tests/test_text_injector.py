import unittest

from hebrew_live_dictation.text_injector import TextInjector


class DummyConfig:
    def __init__(self, values=None):
        self.values = {
            "dictation.live_typing_mode": "final_only",
            "dictation.paste_method": "unicode",
            "language_code": "en-US",
            "languages.command_pack": "en",
            "restore_clipboard": False,
            "debug_log_transcripts": False,
        }
        if values:
            self.values.update(values)

    def get(self, key, default=None):
        return self.values.get(key, default)


class FakeTarget:
    def __init__(self, valid=True, foreground=True, current_process=False, process_name="notepad.exe", hwnd=12345):
        self.valid = valid
        self.foreground = foreground
        self.current_process = current_process
        self.process_name = process_name
        self.hwnd = hwnd

    def is_valid(self):
        return self.valid

    def is_current_process(self):
        return self.current_process

    def is_blocked_system_target(self):
        return False

    def is_usable_external(self):
        return self.valid and not self.current_process and not self.is_blocked_system_target()

    def ensure_foreground(self):
        return self.foreground

    def describe(self):
        return "FakeTarget"


class FakeWordEditor:
    def __init__(self, succeeds=True):
        self.succeeds = succeeds
        self.calls = []

    def insert_text(self, text, target=None):
        self.calls.append((text, getattr(target, "process_name", "")))
        return self.succeeds


class TextInjectorTests(unittest.TestCase):
    def setUp(self):
        from hebrew_live_dictation.editing_backend import WindowTarget
        self._orig_capture_best_target = WindowTarget.capture_best_target
        self._orig_capture_foreground = WindowTarget.capture_foreground
        self.injector_target = FakeTarget()
        WindowTarget.capture_best_target = lambda: self.injector_target
        WindowTarget.capture_foreground = lambda: self.injector_target

    def tearDown(self):
        from hebrew_live_dictation.editing_backend import WindowTarget
        WindowTarget.capture_best_target = self._orig_capture_best_target
        WindowTarget.capture_foreground = self._orig_capture_foreground

    def _injector(self, values=None):
        injector = TextInjector(DummyConfig(values))
        injector.target = self.injector_target
        self.ops = []
        injector._insert_text = lambda text, prefer_clipboard=False: self.ops.append(("insert", text)) or True
        injector._send_backspaces = lambda count: self.ops.append(("backspace", count)) or True
        return injector

    def test_interim_is_preview_only_and_never_touches_target(self):
        injector = self._injector()

        first = injector.inject_interim("hello wor")
        second = injector.inject_interim("hello world")

        self.assertEqual(first["status"], "preview_only")
        self.assertEqual(second["status"], "preview_only")
        self.assertEqual(injector.pending_preview_text, "hello world")
        self.assertEqual(injector.session_pasted_text, "")
        self.assertEqual(self.ops, [])

    def test_final_commits_once_to_target(self):
        injector = self._injector()

        injector.inject_interim("hello wor")
        result = injector.inject_final("hello world")

        self.assertEqual(result["status"], "inserted")
        self.assertEqual(result["backend"], "unicode_keyboard")
        self.assertEqual(self.ops, [("insert", "hello world")])
        self.assertEqual(injector.session_pasted_text, "hello world")
        self.assertEqual(injector.pending_preview_text, "")

    def test_word_target_uses_word_com_before_keyboard_events(self):
        injector = TextInjector(DummyConfig())
        injector.target = FakeTarget(process_name="winword.exe")
        injector.word_editor = FakeWordEditor(succeeds=True)
        self.ops = []
        injector._type_unicode_text = lambda text: self.ops.append(("unicode", text)) or True

        result = injector.inject_final("hello word")

        self.assertEqual(result["status"], "inserted")
        self.assertEqual(result["backend"], "word_com")
        self.assertEqual(injector.word_editor.calls, [("hello word", "winword.exe")])
        self.assertEqual(self.ops, [])

    def test_duplicate_final_is_not_inserted_twice(self):
        injector = self._injector()

        injector.inject_final("hello world")
        result = injector.inject_final("hello world")

        self.assertEqual(result["status"], "duplicate")
        self.assertEqual(self.ops, [("insert", "hello world")])

    def test_legacy_live_mode_is_still_preview_only(self):
        injector = self._injector({"dictation.live_typing_mode": "legacy_aggressive"})

        result = injector.inject_interim("hello world")

        self.assertEqual(result["status"], "preview_only")
        self.assertEqual(self.ops, [])

    def test_target_app_window_blocks_final_injection(self):
        injector = self._injector()
        injector.target = FakeTarget(current_process=True)
        from hebrew_live_dictation.editing_backend import WindowTarget
        orig_capture = WindowTarget.capture_best_target
        WindowTarget.capture_best_target = lambda: FakeTarget(current_process=True)
        
        try:
            injector._insert_text = TextInjector._insert_text.__get__(injector, TextInjector)
            result = injector.inject_final("hello world")
            self.assertEqual(result["status"], "target_unavailable")
            self.assertEqual(injector.session_pasted_text, "")
        finally:
            WindowTarget.capture_best_target = orig_capture

    def test_live_typing_interim_and_final(self):
        injector = self._injector({
            "dictation.live_typing_mode": "live",
            "labs.live_target_typing_enabled": True,
        })
        
        res = injector.inject_interim("hello")
        self.assertEqual(res["status"], "inserted")
        self.assertEqual(self.ops, [("insert", "hello")])
        self.assertEqual(injector.session_interim_text, "hello")
        self.assertEqual(injector.session_pasted_text, "")
        
        self.ops.clear()
        res = injector.inject_interim("hello world")
        self.assertEqual(res["status"], "inserted")
        self.assertEqual(self.ops, [("insert", " world")])
        self.assertEqual(injector.session_interim_text, "hello world")
        
        self.ops.clear()
        res = injector.inject_final("hello world!")
        self.assertEqual(res["status"], "inserted")
        self.assertEqual(self.ops, [("insert", "!")])
        self.assertEqual(injector.session_interim_text, "")
        self.assertEqual(injector.session_pasted_text, "hello world!")

    def test_live_typing_user_interrupt_abort(self):
        injector = self._injector({
            "dictation.live_typing_mode": "live",
            "labs.live_target_typing_enabled": True,
        })
        
        # Simulating user keyboard interrupt mid-typing by making _insert_text set abort_requested
        def mock_insert(text, prefer_clipboard=False):
            injector.abort_requested = True
            return False
            
        injector._insert_text = mock_insert
        res = injector.inject_interim("hello")
        self.assertEqual(res["status"], "target_unavailable")

    def test_diagnostic_log_summarizes_lengths_without_text_content(self):
        injector = self._injector()

        with self.assertLogs("TextInjector", level="INFO") as logs:
            injector._record("final", raw_text="secret phrase", text="secret phrase", backend="unicode_keyboard")

        joined_logs = "\n".join(logs.output)
        self.assertIn("raw_text_len=13", joined_logs)
        self.assertIn("text_len=13", joined_logs)
        self.assertNotIn("secret phrase", joined_logs)

    def test_delete_last_word_uses_backspace_diff(self):
        injector = self._injector()
        injector.inject_final("hello world")

        result = injector.inject_final("delete last word")

        self.assertEqual(result["status"], "command")
        self.assertEqual(result["action"], "delete_last_word")
        self.assertEqual(self.ops, [("insert", "hello world"), ("backspace", 6)])
        self.assertEqual(injector.session_pasted_text, "hello")

    def test_undo_restores_previous_session_text(self):
        injector = self._injector()
        injector.inject_final("hello")
        injector.inject_final("world")

        result = injector.inject_final("undo")

        self.assertEqual(result["status"], "command")
        self.assertEqual(result["action"], "undo")
        self.assertEqual(self.ops, [("insert", "hello"), ("insert", " world"), ("backspace", 6)])
        self.assertEqual(injector.session_pasted_text, "hello")

    def test_dynamic_window_switching_detaches_live_text_without_new_target_write(self):
        injector = self._injector({
            "dictation.live_typing_mode": "live",
            "labs.live_target_typing_enabled": True,
        })
        
        # Initial typing
        res = injector.inject_interim("hello")
        self.assertEqual(res["status"], "inserted")
        self.assertEqual(self.ops, [("insert", "hello")])
        self.assertEqual(injector.session_interim_text, "hello")
        
        # Switch window focus! We change self.injector_target to a new FakeTarget with a different hwnd
        self.ops.clear()
        self.injector_target = FakeTarget(hwnd=67890, process_name="word.exe")
        
        res = injector.inject_interim("hello world")
        self.assertEqual(res["status"], "detached_preview")
        self.assertEqual(res["reason"], "target_changed")
        self.assertEqual(self.ops, [])
        self.assertEqual(injector.session_interim_text, "")
        self.assertEqual(injector.session_pasted_text, "")

    def test_final_after_focus_change_is_preview_only(self):
        injector = self._injector()
        self.injector_target = FakeTarget(hwnd=67890, process_name="chrome.exe")

        result = injector.inject_final("hello world")

        self.assertEqual(result["status"], "detached_preview")
        self.assertEqual(self.ops, [])
        self.assertEqual(injector.session_pasted_text, "")

    def test_replace_phrase_requires_single_session_match(self):
        injector = self._injector()
        injector.inject_final("alpha beta alpha")
        self.ops.clear()

        result = injector.inject_final("replace alpha with gamma")

        self.assertEqual(result["status"], "command")
        self.assertFalse(result["success"])
        self.assertEqual(self.ops, [])
        self.assertEqual(injector.session_pasted_text, "alpha beta alpha")

    def test_delete_phrase_requires_single_session_match(self):
        injector = self._injector()
        injector.inject_final("alpha beta alpha")
        self.ops.clear()

        result = injector.inject_final("delete alpha")

        self.assertEqual(result["status"], "command")
        self.assertFalse(result["success"])
        self.assertEqual(self.ops, [])
        self.assertEqual(injector.session_pasted_text, "alpha beta alpha")

    def test_send_closes_editable_scope(self):
        injector = self._injector()
        injector._press_key = lambda key: True
        injector.inject_final("hello world")

        result = injector.inject_final("send")

        self.assertEqual(result["status"], "command")
        self.assertTrue(result["success"])
        self.assertEqual(injector.session_pasted_text, "")
        self.assertEqual(injector.history, [])

    def test_tsf_requested_falls_back_without_native_peer(self):
        injector = self._injector({"dictation.input_backend": "tsf"})

        self.assertEqual(injector.input_backend, "v1")
        self.assertEqual(injector.tsf_status.status, "fallback")
        self.assertEqual(injector.tsf_status.reason, "labs_gate_disabled")

    def test_live_mode_without_labs_gate_is_preview_only(self):
        injector = self._injector({"dictation.live_typing_mode": "live"})

        result = injector.inject_interim("hello world")

        self.assertEqual(result["status"], "preview_only")
        self.assertEqual(self.ops, [])
        self.assertEqual(injector.session_interim_text, "")


if __name__ == "__main__":
    unittest.main()
