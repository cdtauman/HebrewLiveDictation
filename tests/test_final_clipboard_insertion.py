"""P5 regression: a final (complete utterance) must be inserted via CLIPBOARD PASTE (atomic, exact
Hebrew/Unicode), not the per-character unicode SendInput backend that races under load and corrupts
the text in apps like Notepad (the "זזזזזז" garble). Clipboard is preferred for finals, falls back to
unicode if the paste fails, and is NOT used for Word (COM) or for non-final (live/interim) inserts.

Tests target TextInjector._insert_text's routing directly; the instance is built via __new__ so the
real Windows keyboard hook / COM editors in __init__ are never started."""

import unittest
from unittest import mock

import hebrew_live_dictation.text_injector as ti_module


class _Cfg:
    def __init__(self, d=None):
        self.d = dict(d or {})

    def get(self, key, default=None):
        return self.d.get(key, default)


def _make_injector(preferred_backend="unicode_keyboard"):
    ti = ti_module.TextInjector.__new__(ti_module.TextInjector)   # bypass __init__ (no real hooks)
    ti.config = _Cfg({"restore_clipboard": True})
    ti.last_insert_backend = ""
    ti.word_editor = mock.Mock()
    ti.word_editor.insert_text.return_value = (preferred_backend == "word_com")

    target = mock.Mock()
    target.is_usable_external.return_value = True
    target.describe.return_value = "target"
    prof = mock.Mock()
    prof.preferred_backend = preferred_backend
    target.profile.return_value = prof
    ti.target = target

    ti._paste_text = mock.Mock(return_value=True)
    ti._type_unicode_text = mock.Mock(return_value=True)
    return ti


class FinalClipboardInsertionTests(unittest.TestCase):
    def test_final_prefers_clipboard(self):
        ti = _make_injector()
        self.assertTrue(ti._insert_text("שלום עולם זה מבחן", prefer_clipboard=True))
        ti._paste_text.assert_called_once_with("שלום עולם זה מבחן")
        ti._type_unicode_text.assert_not_called()
        self.assertEqual(ti.last_insert_backend, "clipboard")

    def test_final_falls_back_to_unicode_when_paste_fails(self):
        ti = _make_injector()
        ti._paste_text.return_value = False
        self.assertTrue(ti._insert_text("שלום", prefer_clipboard=True))
        ti._paste_text.assert_called_once()
        ti._type_unicode_text.assert_called_once_with("שלום")
        self.assertEqual(ti.last_insert_backend, "unicode_keyboard")

    def test_non_final_insert_uses_unicode_not_clipboard(self):
        # prefer_clipboard defaults False (e.g. live/interim edits) -> unchanged behavior.
        ti = _make_injector()
        self.assertTrue(ti._insert_text("שלום"))
        ti._paste_text.assert_not_called()
        ti._type_unicode_text.assert_called_once_with("שלום")
        self.assertEqual(ti.last_insert_backend, "unicode_keyboard")

    def test_word_target_uses_com_not_clipboard(self):
        # A Word target keeps its precise COM editor even for finals; clipboard is not used.
        ti = _make_injector(preferred_backend="word_com")
        self.assertTrue(ti._insert_text("שלום", prefer_clipboard=True))
        ti._paste_text.assert_not_called()
        self.assertEqual(ti.last_insert_backend, "word_com")


if __name__ == "__main__":
    unittest.main()
