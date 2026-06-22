"""P5 regression: offline (whisper_local) emits its single final AFTER stop, once the controller's
stop-flush has already run with an empty accumulator. That post-stop final must be injected ONCE,
verbatim (no trailing-punctuation requirement), without double-insertion, and WITHOUT changing the
behavior of a streaming provider whose finals arrive while still listening.

See dictation_controller.handle_stt_event (the post-stop inject branch in the external/final path)."""

import unittest
from unittest import mock

# DictationController is a QObject (signals + a QTimer in the accumulation path). Without a Qt
# application context, Qt cleanup at interpreter shutdown aborts the process (unittest prints OK but
# the process exits non-zero — seen in CI). A headless QCoreApplication gives it a clean context.
from PySide6.QtCore import QCoreApplication

_qt_app = QCoreApplication.instance() or QCoreApplication([])

import hebrew_live_dictation.dictation_controller as dc


class _Cfg:
    def __init__(self, d):
        self.d = dict(d)

    def get(self, key, default=None):
        return self.d.get(key, default)

    def set(self, key, value):
        self.d[key] = value
        return True


def _make_controller(live_mode=False):
    cfg = _Cfg({
        "dictation.live_typing_mode": "live" if live_mode else "final_only",
        "language_code": "he-IL",
        "languages.command_pack": "he",
        "debug_log_transcripts": False,
    })
    with mock.patch.object(dc, "TextInjector"):
        c = dc.DictationController(cfg)
    c.injector.inject_final.return_value = {"status": "inserted"}
    c.injector.inject_interim.return_value = {"status": "interim"}
    c.injector._language_code.return_value = "he-IL"
    c.injector._command_pack.return_value = "he"
    c.session_id = "S"
    c.generation = 1
    return c


def _final(text):
    return {"type": "final", "text": text, "session_id": "S", "generation": 1}


class PostStopFinalInjectionTests(unittest.TestCase):
    def test_offline_final_without_punctuation_injected_once(self):
        c = _make_controller()
        c.output_mode = "external"
        c.state = "stopping"            # the offline final arrives after stop
        c.has_pasted_final = False
        c.handle_stt_event(_final("שלום מה שלומך"))   # no trailing punctuation
        c.injector.inject_final.assert_called_once_with("שלום מה שלומך")

    def test_offline_final_with_punctuation_injected_once(self):
        c = _make_controller()
        c.output_mode = "external"
        c.state = "stopping"
        c.has_pasted_final = False
        c.handle_stt_event(_final("שלום."))
        c.injector.inject_final.assert_called_once_with("שלום.")

    def test_late_final_after_idle_injected_once(self):
        # Even if the teardown already moved the session to idle before the final lands, inject it once.
        c = _make_controller()
        c.output_mode = "external"
        c.state = "idle"
        c.has_pasted_final = False
        c.handle_stt_event(_final("טקסט מאוחר"))
        c.injector.inject_final.assert_called_once_with("טקסט מאוחר")

    def test_no_duplicate_when_already_pasted(self):
        # The stop-flush (or an earlier inject) already pasted this session -> the post-stop branch
        # must NOT fire again.
        c = _make_controller()
        c.output_mode = "external"
        c.state = "stopping"
        c.has_pasted_final = True
        c.handle_stt_event(_final("שלום"))
        c.injector.inject_final.assert_not_called()

    def test_second_post_stop_final_not_duplicated(self):
        # First post-stop final injects (sets has_pasted_final); a duplicate post-stop final must not
        # inject a second time.
        c = _make_controller()
        c.output_mode = "external"
        c.state = "stopping"
        c.has_pasted_final = False
        c.handle_stt_event(_final("שלום"))
        c.handle_stt_event(_final("שלום"))
        c.injector.inject_final.assert_called_once_with("שלום")

    def test_cloud_final_while_listening_unchanged(self):
        # state == "listening" (a streaming provider's mid-session final): the post-stop branch is
        # skipped; final_only accumulation applies (no immediate inject for non-punctuation text).
        c = _make_controller()
        c.output_mode = "external"
        c.state = "listening"
        c.has_pasted_final = False
        c.handle_stt_event(_final("שלום מה שלומך"))
        c.injector.inject_final.assert_not_called()
        self.assertIn("שלום", c.accumulated_final_text)


if __name__ == "__main__":
    unittest.main()
