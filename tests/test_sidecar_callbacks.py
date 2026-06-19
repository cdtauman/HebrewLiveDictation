import unittest

from hebrew_live_dictation.bridge.sidecar import make_callbacks


class _FakeHotkeys:
    def __init__(self):
        self.listening_state = None

    def set_listening_state(self, state):
        self.listening_state = state


class _FakeServer:
    def __init__(self, sink):
        self.sink = sink

    def send_event(self, event):
        self.sink.append(event)


class SidecarCallbackTests(unittest.TestCase):
    def test_status_syncs_toggle_listening_state(self):
        # Regression guard: the toggle hotkey depends on listening_state being kept
        # in sync (legacy qt_app called set_listening_state on every status). Without
        # this, F8 starts dictation but never stops it.
        events = []
        hk = _FakeHotkeys()
        on_status, _, _, _ = make_callbacks(hk, lambda: _FakeServer(events))

        on_status("listening", "rec", "external")
        self.assertTrue(hk.listening_state)

        on_status("stopping", "processing", "external")
        self.assertFalse(hk.listening_state)

        on_status("idle", "ready", "external")
        self.assertFalse(hk.listening_state)

    def test_status_event_shape(self):
        events = []
        hk = _FakeHotkeys()
        srv = _FakeServer(events)
        on_status, _, _, _ = make_callbacks(hk, lambda: srv)
        on_status("listening", "rec", "external")
        self.assertEqual(events[-1]["kind"], "status")
        self.assertEqual(events[-1]["state"], "listening")
        self.assertEqual(events[-1]["message"], "rec")

    def test_text_error_command_events(self):
        events = []
        hk = _FakeHotkeys()
        srv = _FakeServer(events)
        _, on_text, on_error, on_command = make_callbacks(hk, lambda: srv)
        on_text("hello", True, "external")
        self.assertEqual(events[-1]["kind"], "text")
        self.assertTrue(events[-1]["final"])
        on_error("boom")
        self.assertEqual(events[-1]["kind"], "error")
        on_command("stop", {})
        self.assertEqual(events[-1]["kind"], "command")

    def test_server_none_is_safe_but_still_syncs_hotkeys(self):
        hk = _FakeHotkeys()
        on_status, on_text, on_error, on_command = make_callbacks(hk, lambda: None)
        on_status("listening", "", "external")  # must not raise when no client connected
        self.assertTrue(hk.listening_state)
        on_text("x", False, "external")
        on_error("y")
        on_command("z", {})


if __name__ == "__main__":
    unittest.main()
