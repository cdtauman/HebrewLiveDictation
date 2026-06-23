import unittest
from unittest import mock

from hebrew_live_dictation.dictation_controller import DictationController
from hebrew_live_dictation.i18n import tr


class DummyConfig:
    def __init__(self, values=None):
        self.values = values or {}

    def get(self, key, default=None):
        return self.values.get(key, default)


class FakeInjector:
    def __init__(self):
        self.calls = []

    def reset_session(self):
        self.calls.append(("reset_session",))

    def inject_interim(self, text):
        self.calls.append(("interim", text))
        return {"status": "preview_only"}

    def inject_final(self, text):
        self.calls.append(("final", text))
        if text == "עצור" or text == "stop":
            return {"status": "command", "action": "stop"}
        return {"status": "inserted"}

    def _language_code(self):
        return "he-IL"

    def _command_pack(self):
        return "he"


class DictationControllerModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtCore import QCoreApplication
        cls.app = QCoreApplication.instance()
        if cls.app is None:
            cls.app = QCoreApplication([])

    def _controller(self, config_values=None):
        texts = []
        config = DummyConfig(config_values)
        controller = DictationController(config, on_text=lambda text, final, mode: texts.append((text, final, mode)))
        controller.injector = FakeInjector()
        return controller, texts

    def _pump_events(self, duration=0.05):
        from PySide6.QtCore import QCoreApplication
        import time
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            QCoreApplication.processEvents()
            time.sleep(0.005)

    def test_preview_mode_never_calls_text_injector(self):
        controller, texts = self._controller()
        controller.state = "listening"
        controller.output_mode = "preview"

        controller.handle_stt_event({"type": "interim", "text": "hello"})
        controller.handle_stt_event({"type": "final", "text": "hello world"})

        self.assertEqual(texts, [("hello", False, "preview"), ("hello world", True, "preview")])
        self.assertEqual(controller.injector.calls, [])

    def test_external_mode_does_not_update_internal_preview(self):
        # By default config is final_only, so we end with a period to trigger the sentence finalization buffer commit
        controller, texts = self._controller()
        controller.state = "listening"
        controller.output_mode = "external"

        controller.handle_stt_event({"type": "interim", "text": "hello"})
        controller.handle_stt_event({"type": "final", "text": "hello world."})

        self.assertEqual(texts, [("hello", False, "external"), ("hello world.", True, "external")])
        self.assertEqual(controller.injector.calls, [("final", "hello world.")])

    def test_stale_generation_event_is_ignored(self):
        controller, texts = self._controller()
        controller.state = "listening"
        controller.output_mode = "external"
        controller.generation = 2

        controller.handle_stt_event({"type": "final", "text": "hello world.", "generation": 1})

        self.assertEqual(texts, [])
        self.assertEqual(controller.injector.calls, [])

    def test_stale_session_event_is_ignored(self):
        controller, texts = self._controller()
        controller.state = "listening"
        controller.output_mode = "external"
        controller.session_id = "current"

        controller.handle_stt_event({"type": "final", "text": "hello world.", "session_id": "old"})

        self.assertEqual(texts, [])
        self.assertEqual(controller.injector.calls, [])

    def test_detached_preview_result_emits_status_without_command(self):
        statuses = []
        config = DummyConfig()
        controller = DictationController(
            config,
            on_text=lambda text, final, mode: None,
            on_status=lambda state, message, mode: statuses.append((state, message, mode)),
        )
        controller.state = "listening"
        controller.output_mode = "external"

        controller._handle_injector_result({"status": "detached_preview", "text": "hello"})

        self.assertEqual(statuses, [("listening", tr(config, "target_detached_preview"), "external")])
        self.assertEqual(controller.latest_interim_text, "hello")

    def test_sentence_level_accumulation_flushes_on_punctuation(self):
        controller, texts = self._controller({"dictation.live_typing_mode": "final_only"})
        controller.state = "listening"
        controller.output_mode = "external"

        # Final event without punctuation: accumulated, not injected
        controller.handle_stt_event({"type": "final", "text": "hello"})
        self.assertEqual(controller.injector.calls, [])
        self.assertEqual(controller.accumulated_final_text, "hello")

        # Final event with punctuation: triggers commit
        controller.handle_stt_event({"type": "final", "text": "world."})
        self.assertEqual(controller.injector.calls, [("final", "hello world.")])
        self.assertEqual(controller.accumulated_final_text, "")

    def test_sentence_level_accumulation_flushes_on_stop(self):
        controller, texts = self._controller({"dictation.live_typing_mode": "final_only"})
        controller.state = "listening"
        controller.output_mode = "external"

        controller.handle_stt_event({"type": "final", "text": "hello"})
        self.assertEqual(controller.injector.calls, [])

        # Stopping listening flushes the accumulated buffer
        controller.stop_listening()
        self.assertIn(("final", "hello"), controller.injector.calls)
        self.assertEqual(controller.accumulated_final_text, "")

    def test_voice_command_flushes_accumulation_and_runs(self):
        controller, texts = self._controller({"dictation.live_typing_mode": "final_only"})
        controller.state = "listening"
        controller.output_mode = "external"

        # Dictate text (accumulates)
        controller.handle_stt_event({"type": "final", "text": "hello"})
        self.assertEqual(controller.injector.calls, [])

        # Speak command
        controller.handle_stt_event({"type": "final", "text": "עצור"})
        # Should flush "hello", then execute "עצור"
        self.assertEqual(controller.injector.calls, [("final", "hello"), ("final", "עצור")])
        self.assertEqual(controller.accumulated_final_text, "")

    def test_sentence_level_accumulation_formats_spoken_punctuation(self):
        controller, texts = self._controller({"dictation.live_typing_mode": "final_only"})
        controller.state = "listening"
        controller.output_mode = "external"

        # "שלום נקודה" gets formatted to "שלום." which ends with a period and triggers commit!
        controller.handle_stt_event({"type": "final", "text": "שלום נקודה"})
        self.assertEqual(controller.injector.calls, [("final", "שלום.")])
        self.assertEqual(controller.accumulated_final_text, "")

    def test_sentence_level_accumulation_timer_timeout(self):
        from PySide6.QtCore import QCoreApplication
        import time
        controller, texts = self._controller({
            "dictation.live_typing_mode": "final_only",
            "dictation.pause_commit_timeout_seconds": 0.05
        })
        controller.state = "listening"
        controller.output_mode = "external"

        controller.handle_stt_event({"type": "final", "text": "שלום לכולם"})
        self.assertEqual(controller.injector.calls, [])

        # Spin the Qt event loop to allow the QTimer to fire
        start_time = time.monotonic()
        while time.monotonic() - start_time < 0.15:
            QCoreApplication.processEvents()
            time.sleep(0.01)

        self.assertEqual(controller.injector.calls, [("final", "שלום לכולם")])
        self.assertEqual(controller.accumulated_final_text, "")


    def test_start_listening_passes_advanced_audio_vad_settings_to_audio_stream(self):
        seen = {}

        class FakeAudioStream:
            def __init__(self, **kwargs):
                seen["audio_kwargs"] = kwargs

            def start(self):
                return True

            def get_queue(self):
                return object()

            def stop(self):
                seen["audio_stopped"] = True

        class FakeSttStream:
            def start(self, audio_queue):
                seen["stt_started"] = audio_queue

        config = DummyConfig({
            "audio.sample_rate": 16000,
            "speech.frame_ms": 50,
            "microphone_device": 7,
            "speech.vad_enabled": True,
            "speech.vad_threshold": 0.35,
            "speech.vad_padding_ms": 180,
            "speech.vad_min_silence_ms": 650,
        })
        controller = DictationController(config)
        controller.injector = FakeInjector()

        with mock.patch("hebrew_live_dictation.dictation_controller.AudioStream", FakeAudioStream):
            with mock.patch("hebrew_live_dictation.dictation_controller.create_stt_stream",
                            return_value=FakeSttStream()):
                controller.start_listening()

        self.assertEqual(seen["audio_kwargs"], {
            "device_id": 7,
            "sample_rate": 16000,
            "block_size": 800,
            "vad_enabled": True,
            "vad_threshold": 0.35,
            "vad_padding_ms": 180,
            "vad_min_silence_ms": 650,
        })
        self.assertIsNotNone(seen["stt_started"])

    def test_pause_resume_keeps_session_and_ignores_old_stream_events(self):
        streams = []
        audios = []

        class FakeAudioStream:
            def __init__(self, **kwargs):
                self.queue = object()
                self.stopped = False
                audios.append(self)

            def start(self):
                return True

            def get_queue(self):
                return self.queue

            def stop(self):
                self.stopped = True

        class FakeSttStream:
            def __init__(self, callback):
                self.callback = callback
                self.started_with = None
                self.canceled = False

            def start(self, audio_queue):
                self.started_with = audio_queue

            def cancel(self):
                self.canceled = True

            def stop(self):
                self.canceled = True

            def emit(self, event):
                self.callback(event)

        def fake_create_stt_stream(config, callback):
            stream = FakeSttStream(callback)
            streams.append(stream)
            return stream

        controller, _ = self._controller({
            "dictation.live_typing_mode": "final_only",
            "dictation.pause_commit_timeout_seconds": 60,
        })

        with mock.patch("hebrew_live_dictation.dictation_controller.AudioStream", FakeAudioStream):
            with mock.patch("hebrew_live_dictation.dictation_controller.create_stt_stream",
                            side_effect=fake_create_stt_stream):
                controller.start_listening()
                self._pump_events()
                session_id = controller.session_id
                first_generation = controller.generation

                streams[0].emit({"type": "final", "text": "first"})
                self._pump_events()
                self.assertEqual(controller.accumulated_final_text, "first")

                controller.pause_listening()
                self._pump_events()
                self.assertEqual(controller.state, "paused")
                self.assertEqual(controller.session_id, session_id)
                self.assertNotEqual(controller.generation, first_generation)

                streams[0].emit({"type": "final", "text": "old."})
                self._pump_events()
                self.assertEqual(controller.accumulated_final_text, "first")
                self.assertNotIn(("final", "old."), controller.injector.calls)

                controller.resume_listening()
                self._pump_events()
                self.assertEqual(controller.state, "listening")
                self.assertEqual(controller.session_id, session_id)
                self.assertEqual(len(streams), 2)
                self.assertEqual(controller.injector.calls, [("reset_session",)])

                streams[1].emit({"type": "final", "text": "second."})
                self._pump_events()

        self.assertEqual(len(audios), 2)
        self.assertIn(("final", "first second."), controller.injector.calls)
        self.assertEqual(controller.accumulated_final_text, "")

    def test_stop_while_paused_flushes_accumulated_final_once(self):
        controller, _ = self._controller({"dictation.live_typing_mode": "final_only"})
        controller.state = "paused"
        controller.output_mode = "external"
        controller.accumulated_final_text = "שלום עולם"

        controller.stop_listening()

        self.assertEqual(controller.state, "idle")
        self.assertEqual(controller.injector.calls, [("final", "שלום עולם")])
        self.assertEqual(controller.accumulated_final_text, "")


if __name__ == "__main__":
    unittest.main()
