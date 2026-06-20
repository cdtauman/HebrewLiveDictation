import json
import os
import sys
import tempfile
import unittest
from unittest import mock

from hebrew_live_dictation.bridge import sidecar
from hebrew_live_dictation.bridge.sidecar import (
    _clear_history,
    command_reference,
    compute_health,
    engine_label,
    friendly_app_name,
    full_history,
    injection_target_label,
    list_microphones,
    make_callbacks,
    recent_history,
)


def _write_history(tmp, rows):
    with open(os.path.join(tmp, "history.jsonl"), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


class _FakeHotkeys:
    def __init__(self):
        self.listening = None

    def set_listening_state(self, on):
        self.listening = on


class _RecordingServer:
    def __init__(self):
        self.events = []

    def send_event(self, event):
        self.events.append(event)


class _FakeConfig:
    def __init__(self, d, config_dir=None):
        self.d = d
        if config_dir is not None:
            self.config_dir = config_dir

    def get(self, key, default=None):
        return self.d.get(key, default)

    def set(self, key, value):
        self.d[key] = value
        return True


class HealthTests(unittest.TestCase):
    def test_engine_label_google_pretty(self):
        c = _FakeConfig({"stt.provider": "google_v2", "stt.mode": "api", "google.model": "chirp_3"})
        self.assertEqual(engine_label(c), "Google · Chirp 3")

    def test_engine_label_offline(self):
        self.assertIn("Whisper", engine_label(_FakeConfig({"stt.mode": "local"})))
        self.assertIn("Whisper", engine_label(_FakeConfig({"stt.provider": "whisper_local"})))

    def test_engine_label_other_providers(self):
        self.assertEqual(engine_label(_FakeConfig({"stt.provider": "deepgram"})), "Deepgram")
        self.assertEqual(engine_label(_FakeConfig({"stt.provider": "groq"})), "Groq")

    def test_health_offline_ready(self):
        # Ready requires BOTH fallback configured AND the local Whisper engine enabled.
        self.assertTrue(compute_health(
            _FakeConfig({"stt.mode": "auto_fallback", "providers.whisper.enabled": True}))["offline"]["ready"])
        self.assertTrue(compute_health(
            _FakeConfig({"stt.mode": "local", "providers.whisper.enabled": True}))["offline"]["ready"])
        # auto_fallback WITHOUT Whisper = configured but NOT ready (the overclaim fix).
        cfg = compute_health(_FakeConfig({"stt.mode": "auto_fallback"}))
        self.assertFalse(cfg["offline"]["ready"])
        self.assertTrue(cfg["offline"]["configured"])
        # Whisper enabled but no fallback configured (mode=api) = not ready, not configured.
        notcfg = compute_health(_FakeConfig({"providers.whisper.enabled": True}))
        self.assertFalse(notcfg["offline"]["ready"])
        self.assertFalse(notcfg["offline"]["configured"])
        # Nothing set = not ready.
        self.assertFalse(compute_health(_FakeConfig({}))["offline"]["ready"])

    def test_health_shape(self):
        h = compute_health(_FakeConfig({"stt.provider": "google_v2", "google.model": "chirp_2"}))
        self.assertEqual(h["engine"]["label"], "Google · Chirp 2")
        self.assertIn("ok", h["microphone"])
        self.assertIn("ready", h["offline"])
        self.assertIn("configured", h["offline"])

    def test_recent_history_empty_and_safe(self):
        # Empty config dir -> no history file -> empty list, never raises.
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(recent_history(_FakeConfig({}, config_dir=tmp), 5), [])

    def test_recent_history_sanitized_and_truncated(self):
        with tempfile.TemporaryDirectory() as tmp:
            long_text = "א" * 200
            _write_history(tmp, [
                {"ts": 1000, "target": "winword.exe", "text": "ראשון"},
                {"ts": 2000, "target": "secret-app.exe", "text": long_text},
            ])
            items = recent_history(_FakeConfig({}, config_dir=tmp), 5)
            self.assertEqual(len(items), 2)
            self.assertEqual(items[0]["ts"], 2000)               # newest first
            self.assertEqual(set(items[0].keys()), {"ts", "text"})  # target dropped
            self.assertTrue(items[0]["text"].endswith("…"))         # truncated
            self.assertLessEqual(len(items[0]["text"]), 81)

    def test_recent_history_count_clamped(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_history(tmp, [{"ts": i, "text": f"t{i}"} for i in range(100)])
            c = _FakeConfig({}, config_dir=tmp)
            self.assertLessEqual(len(recent_history(c, 9999)), 50)   # upper clamp
            self.assertGreaterEqual(len(recent_history(c, "bad")), 1)  # bad -> default

    def test_recent_history_skips_blank_and_nondict(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_history(tmp, [{"ts": 1, "text": "  "}, {"ts": 2, "text": "ok"}])
            items = recent_history(_FakeConfig({}, config_dir=tmp), 5)
            self.assertEqual([i["text"] for i in items], ["ok"])

    def test_full_history_untruncated_newest_first_with_target(self):
        # The History room shows the user's complete record: full text + target, newest first.
        with tempfile.TemporaryDirectory() as tmp:
            long_text = "א" * 200
            _write_history(tmp, [
                {"ts": 1000, "target": "winword.exe", "text": "ראשון"},
                {"ts": 2000, "target": "chrome.exe", "text": long_text},
            ])
            items = full_history(_FakeConfig({}, config_dir=tmp), 200)
            self.assertEqual(items[0]["ts"], 2000)                      # newest first
            self.assertEqual(items[0]["text"], long_text)              # NOT truncated
            self.assertEqual(items[0]["target"], "chrome.exe")        # target preserved
            self.assertEqual(set(items[0].keys()), {"ts", "text", "target"})

    def test_full_history_count_clamped_to_store_cap(self):
        # >500 rows on disk: the default cap (history.max_entries=500) bounds the result,
        # and the NEWEST rows are returned (tail read, not a whole-file slice).
        with tempfile.TemporaryDirectory() as tmp:
            _write_history(tmp, [{"ts": i, "text": f"t{i}"} for i in range(620)])
            c = _FakeConfig({}, config_dir=tmp)
            items = full_history(c, 9999)
            self.assertEqual(len(items), 500)               # clamped to default cap
            self.assertEqual(items[0]["text"], "t619")      # newest first
            self.assertEqual(items[-1]["text"], "t120")     # only the last 500 kept
            self.assertGreaterEqual(len(full_history(c, "bad")), 1)   # bad count -> default

    def test_full_history_honors_higher_max_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_history(tmp, [{"ts": i, "text": f"t{i}"} for i in range(620)])
            c = _FakeConfig({"history.max_entries": 1000}, config_dir=tmp)
            self.assertEqual(len(full_history(c, 9999)), 620)   # cap above count -> all rows

    def test_clear_history_removes_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_history(tmp, [{"ts": 1, "text": "a"}, {"ts": 2, "text": "b"}])
            c = _FakeConfig({}, config_dir=tmp)
            self.assertTrue(_clear_history(c))
            self.assertEqual(full_history(c, 200), [])


    def test_command_reference_he_deduped_and_friendly(self):
        ref = command_reference(_FakeConfig({"languages.primary": "iw-IL", "languages.command_pack": "he"}))
        says = [p["say"] for p in ref["punctuation"]]
        # The many newline alternates collapse to a single entry (first phrase kept,
        # deduped by inserted symbol — "שורה הבאה"/"רד שורה" share "\n" with "שורה חדשה").
        self.assertEqual(says.count("שורה חדשה"), 1)
        self.assertNotIn("שורה הבאה", says)
        self.assertNotIn("רד שורה", says)
        self.assertIn("נקודה", says)
        # Actions: one row per action, with a friendly Hebrew label; first phrase kept.
        self.assertEqual(len(ref["actions"]), 9)
        stop = next(a for a in ref["actions"] if a["does"] == "עצירת הכתבה")
        self.assertEqual(stop["say"], "עצור")

    def test_command_reference_safe_on_bad_pack(self):
        ref = command_reference(_FakeConfig({"languages.primary": "zz-ZZ"}))
        self.assertIn("punctuation", ref)
        self.assertIn("actions", ref)

    def test_list_microphones_shapes_devices(self):
        # Prefers display_name, falls back to name, drops blank/invalid, keeps the index.
        fake = [
            {"index": 3, "display_name": "USB Mic", "name": "USB Mic (2- USB Audio)"},
            {"index": 1, "name": "Internal"},
            {"index": 9, "display_name": "  "},  # no usable name -> dropped
        ]
        with mock.patch("hebrew_live_dictation.audio_stream.AudioStream.list_devices", return_value=fake):
            items = list_microphones()["items"]
        self.assertEqual([i["index"] for i in items], [3, 1])
        self.assertEqual(items[0]["name"], "USB Mic")   # display_name preferred
        self.assertEqual(items[1]["name"], "Internal")  # falls back to raw name

    def test_list_microphones_safe_on_error(self):
        with mock.patch("hebrew_live_dictation.audio_stream.AudioStream.list_devices",
                        side_effect=RuntimeError("no audio")):
            self.assertEqual(list_microphones(), {"items": []})

    def test_list_microphones_clears_stale_saved_index(self):
        # Saved device index 7 is gone -> normalized to null so the engine uses the
        # Windows default instead of opening a stale device.
        fake = [{"index": 3, "name": "USB Mic"}, {"index": 1, "name": "Internal"}]
        cfg = _FakeConfig({"audio.microphone_device": 7})
        with mock.patch("hebrew_live_dictation.audio_stream.AudioStream.list_devices", return_value=fake):
            list_microphones(cfg)
        self.assertIsNone(cfg.get("audio.microphone_device"))

    def test_list_microphones_keeps_valid_saved_index(self):
        fake = [{"index": 3, "name": "USB Mic"}, {"index": 1, "name": "Internal"}]
        cfg = _FakeConfig({"audio.microphone_device": 3})
        with mock.patch("hebrew_live_dictation.audio_stream.AudioStream.list_devices", return_value=fake):
            list_microphones(cfg)
        self.assertEqual(cfg.get("audio.microphone_device"), 3)  # present -> untouched

    def test_list_microphones_does_not_clear_when_enumeration_empty(self):
        # No devices enumerated (transient/failure) must NOT clobber a saved selection.
        cfg = _FakeConfig({"audio.microphone_device": 5})
        with mock.patch("hebrew_live_dictation.audio_stream.AudioStream.list_devices", return_value=[]):
            list_microphones(cfg)
        self.assertEqual(cfg.get("audio.microphone_device"), 5)

    def test_friendly_app_name_maps_known_and_falls_back(self):
        self.assertEqual(friendly_app_name("WINWORD.EXE"), "Word")    # case-insensitive map
        self.assertEqual(friendly_app_name("chrome.exe"), "Chrome")
        self.assertEqual(friendly_app_name("MyEditor.exe"), "Myeditor")  # fallback: strip .exe, cap
        self.assertEqual(friendly_app_name(""), "")
        self.assertEqual(friendly_app_name("VoiceType.exe"), "")     # our own shell suppressed


class HudTargetTests(unittest.TestCase):
    def _status_cb(self, server):
        on_status, _, _, _ = make_callbacks(_FakeHotkeys(), lambda: server)
        return on_status

    def test_target_captured_once_and_preserved_across_listening_refreshes(self):
        # If the target were recomputed per status, this iterator would hand out a new
        # app each call; captured-once must pin the FIRST value for the whole session.
        server = _RecordingServer()
        on_status = self._status_cb(server)
        changing = iter(["Word", "Chrome", "Excel"])
        with mock.patch.object(sidecar, "injection_target_label", lambda: next(changing)):
            on_status("listening", "", "external")   # captures "Word"
            on_status("listening", "", "external")   # refresh — must NOT recompute
            on_status("listening", "", "external")   # refresh — must NOT recompute
        self.assertEqual([e.get("target") for e in server.events], ["Word", "Word", "Word"])

    def test_target_reset_and_recaptured_for_next_session(self):
        server = _RecordingServer()
        on_status = self._status_cb(server)
        changing = iter(["Word", "Chrome"])
        with mock.patch.object(sidecar, "injection_target_label", lambda: next(changing)):
            on_status("listening", "", "external")   # session 1 -> "Word"
            on_status("idle", "", "external")         # session ends
            on_status("listening", "", "external")   # session 2 -> fresh capture "Chrome"
        self.assertEqual(server.events[0].get("target"), "Word")
        self.assertNotIn("target", server.events[1])  # non-listening carries no target claim
        self.assertEqual(server.events[2].get("target"), "Chrome")

    def test_unknown_target_carries_empty_safe_state_while_listening(self):
        server = _RecordingServer()
        on_status = self._status_cb(server)
        with mock.patch.object(sidecar, "injection_target_label", lambda: ""):
            on_status("listening", "", "external")
        # Listening always carries the field; "" tells the HUD to show its safe state
        # rather than name a window the injector might not actually write to.
        self.assertIn("target", server.events[0])
        self.assertEqual(server.events[0]["target"], "")

    @unittest.skipUnless(sys.platform == "win32", "Win32 target selection")
    def test_injection_target_label_uses_injector_selection_and_safety_gate(self):
        class _T:
            def __init__(self, name, usable):
                self.process_name = name
                self._usable = usable

            def is_usable_external(self):
                return self._usable

        with mock.patch("hebrew_live_dictation.editing_backend.WindowTarget.capture_best_target",
                        return_value=_T("winword.exe", True)):
            self.assertEqual(injection_target_label(), "Word")
        # Unsafe / blocked / our-own target -> no confident claim.
        with mock.patch("hebrew_live_dictation.editing_backend.WindowTarget.capture_best_target",
                        return_value=_T("winword.exe", False)):
            self.assertEqual(injection_target_label(), "")
        # Failure in the lookup is safe-empty, never raised.
        with mock.patch("hebrew_live_dictation.editing_backend.WindowTarget.capture_best_target",
                        side_effect=RuntimeError("boom")):
            self.assertEqual(injection_target_label(), "")


if __name__ == "__main__":
    unittest.main()
