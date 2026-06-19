import json
import os
import tempfile
import unittest

from hebrew_live_dictation.bridge.sidecar import (
    _clear_history,
    compute_health,
    engine_label,
    full_history,
    recent_history,
)


def _write_history(tmp, rows):
    with open(os.path.join(tmp, "history.jsonl"), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


class _FakeConfig:
    def __init__(self, d, config_dir=None):
        self.d = d
        if config_dir is not None:
            self.config_dir = config_dir

    def get(self, key, default=None):
        return self.d.get(key, default)


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
        self.assertTrue(compute_health(_FakeConfig({"providers.whisper.enabled": True}))["offline"]["ready"])
        self.assertTrue(compute_health(_FakeConfig({"stt.mode": "auto_fallback"}))["offline"]["ready"])
        self.assertFalse(compute_health(_FakeConfig({}))["offline"]["ready"])

    def test_health_shape(self):
        h = compute_health(_FakeConfig({"stt.provider": "google_v2", "google.model": "chirp_2"}))
        self.assertEqual(h["engine"]["label"], "Google · Chirp 2")
        self.assertIn("ok", h["microphone"])
        self.assertIn("ready", h["offline"])

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

    def test_full_history_count_clamped(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_history(tmp, [{"ts": i, "text": f"t{i}"} for i in range(20)])
            c = _FakeConfig({}, config_dir=tmp)
            self.assertLessEqual(len(full_history(c, 9999)), 500)       # upper clamp
            self.assertGreaterEqual(len(full_history(c, "bad")), 1)     # bad -> default

    def test_clear_history_removes_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_history(tmp, [{"ts": 1, "text": "a"}, {"ts": 2, "text": "b"}])
            c = _FakeConfig({}, config_dir=tmp)
            self.assertTrue(_clear_history(c))
            self.assertEqual(full_history(c, 200), [])


if __name__ == "__main__":
    unittest.main()
