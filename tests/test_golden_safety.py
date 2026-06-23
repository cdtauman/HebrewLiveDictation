import tempfile
import unittest

from hebrew_live_dictation.bridge import sidecar
from hebrew_live_dictation.bridge.sidecar import make_callbacks
from hebrew_live_dictation.config import Config
from hebrew_live_dictation.dictation_controller import DictationController


class _FakeConfig:
    def __init__(self, values=None, config_dir=None):
        self.values = dict(values or {})
        if config_dir is not None:
            self.config_dir = config_dir

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value
        return True


class _FakeHotkeys:
    def __init__(self):
        self.listening = None

    def set_listening_state(self, state):
        self.listening = state


class _RecordingServer:
    def __init__(self):
        self.events = []

    def send_event(self, event):
        self.events.append(event)


class _FakeInjector:
    def __init__(self):
        self.calls = []

    def reset_session(self):
        self.calls.append(("reset_session",))

    def inject_interim(self, text):
        self.calls.append(("interim", text))
        return {"status": "preview_only"}

    def inject_final(self, text):
        self.calls.append(("final", text))
        return {"status": "inserted"}

    def _language_code(self):
        return "iw-IL"

    def _command_pack(self):
        return "he"


class GoldenGoogleRuntimeConfigTests(unittest.TestCase):
    def test_proven_google_combo_persists_in_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)

            self.assertTrue(config.set("stt.provider", "google_v2"))
            self.assertTrue(config.set("stt.mode", "api"))
            self.assertTrue(config.set("google.model", "latest_long"))
            self.assertTrue(config.set("google.location", "eu"))
            self.assertTrue(config.set("google.recognizer_id", "_"))
            self.assertTrue(config.set("languages.primary", "iw-IL"))

            self.assertEqual(config.get("stt.provider"), "google_v2")
            self.assertEqual(config.get("stt.mode"), "api")
            self.assertEqual(config.get("google.model"), "latest_long")
            self.assertEqual(config.get("google.location"), "eu")
            self.assertEqual(config.get("google.recognizer_id"), "_")
            self.assertEqual(config.get("languages.primary"), "iw-IL")
            self.assertEqual(config.get("dictation.live_typing_mode"), "final_only")

    def test_verified_proven_google_combo_reports_runtime_truth(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _FakeConfig(
                {
                    "stt.provider": "google_v2",
                    "stt.mode": "api",
                    "google.project_id": "project-id",
                    "google.location": "eu",
                    "google.model": "latest_long",
                    "google.recognizer_id": "_",
                    "google.credential_mode": "adc",
                    "languages.primary": "iw-IL",
                },
                config_dir=tmp,
            )

            sidecar._set_google_verified(cfg)

            status = sidecar.google_config_status(cfg)
            self.assertTrue(status["verified"])
            self.assertEqual(status["provider"], "google_v2")
            self.assertEqual(status["model"], "latest_long")
            self.assertEqual(status["location"], "eu")
            self.assertEqual(status["language"], "iw-IL")
            self.assertEqual(status["recognizer"], "_")
            self.assertEqual(status["credentialMode"], "adc")
            self.assertFalse(sidecar.recover_unconfigured_cloud(cfg))
            self.assertEqual(cfg.get("stt.provider"), "google_v2")

    def test_changing_proven_google_combo_invalidates_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _FakeConfig(
                {
                    "stt.provider": "google_v2",
                    "stt.mode": "api",
                    "google.project_id": "project-id",
                    "google.location": "eu",
                    "google.model": "latest_long",
                    "google.recognizer_id": "_",
                    "google.credential_mode": "adc",
                    "languages.primary": "iw-IL",
                },
                config_dir=tmp,
            )

            sidecar._set_google_verified(cfg)
            self.assertTrue(sidecar._google_verified(cfg))

            cfg.set("google.model", "chirp_3")
            self.assertFalse(sidecar._google_verified(cfg))
            self.assertTrue(sidecar.recover_unconfigured_cloud(cfg))
            self.assertEqual(cfg.get("stt.provider"), "whisper_local")
            self.assertEqual(cfg.get("stt.mode"), "local")


class GoldenFinalOnlyInsertionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtCore import QCoreApplication

        cls.app = QCoreApplication.instance()
        if cls.app is None:
            cls.app = QCoreApplication([])

    def test_interims_are_display_only_in_final_only_mode(self):
        texts = []
        controller = DictationController(
            _FakeConfig({"dictation.live_typing_mode": "final_only"}),
            on_text=lambda text, final, mode: texts.append((text, final, mode)),
        )
        controller.injector = _FakeInjector()
        controller.state = "listening"
        controller.output_mode = "external"

        controller.handle_stt_event({"type": "interim", "text": "live words"})
        controller.handle_stt_event({"type": "final", "text": "final words"})

        self.assertEqual(texts, [("live words", False, "external"), ("final words", True, "external")])
        self.assertEqual(controller.injector.calls, [])

        controller.stop_listening()
        self.assertIn(("final", "final words"), controller.injector.calls)

    def test_cloud_interims_do_not_create_history_or_no_text_failure(self):
        server = _RecordingServer()
        sessions = []
        cfg = _FakeConfig({"stt.provider": "google_v2", "stt.mode": "api"})
        on_status, on_text, _, _ = make_callbacks(
            _FakeHotkeys(),
            lambda: server,
            on_session_end=sessions.append,
            config=cfg,
        )

        on_status("listening", "recording", "external")
        on_text("live words only", False, "external")
        on_status("idle", "ready", "external")

        self.assertEqual(sessions, [])
        self.assertFalse([e for e in server.events if e.get("cloudNoText")])
        text_events = [e for e in server.events if e.get("kind") == "text"]
        self.assertEqual(text_events, [{"kind": "text", "text": "live words only", "final": False, "outputMode": "external"}])


class GoldenSelfTargetSafetyTests(unittest.TestCase):
    def test_voicetype_shell_name_is_never_a_target_label(self):
        self.assertEqual(sidecar.friendly_app_name("VoiceType.exe"), "")
        self.assertEqual(sidecar.friendly_app_name("voicetype.exe"), "")

    def test_known_target_label_is_stable_for_session(self):
        server = _RecordingServer()
        on_status, _, _, _ = make_callbacks(_FakeHotkeys(), lambda: server)
        names = iter(["Word", "Chrome"])

        original = sidecar.injection_target_label
        try:
            sidecar.injection_target_label = lambda: next(names)
            on_status("listening", "recording", "external")
            on_status("listening", "still recording", "external")
        finally:
            sidecar.injection_target_label = original

        self.assertEqual([event.get("target") for event in server.events], ["Word", "Word"])


if __name__ == "__main__":
    unittest.main()
