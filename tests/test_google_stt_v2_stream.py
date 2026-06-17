import tempfile
import unittest

from hebrew_live_dictation.config import Config
from hebrew_live_dictation.google_stt_v2_stream import GoogleSTTV2Stream, infer_project_id_from_credentials


try:
    from google.cloud.speech_v2.types import cloud_speech
except Exception:  # pragma: no cover - dependency availability guard
    cloud_speech = None


class GoogleSTTV2RuntimeTests(unittest.TestCase):
    def test_v2_no_response_while_active_retries_before_clear_error_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            events = []
            stream = GoogleSTTV2Stream(config, on_event_callback=events.append)
            stream.active = True
            calls = 0

            def stream_once():
                nonlocal calls
                calls += 1
                return 0

            stream._stream_once = stream_once

            stream._run_stream()

            self.assertEqual(stream.active, False)
            self.assertEqual(calls, 4)
            self.assertGreaterEqual(sum(1 for event in events if event.get("type") == "status"), 3)
            self.assertTrue(any(event.get("type") == "error" for event in events))
            self.assertTrue(
                any("returned no recognition responses" in event.get("message", "") for event in events)
            )

    def test_v2_no_response_with_auto_stop_enabled_emits_clear_error_immediately(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            config.update({"speech.auto_stop_on_silence": True})
            events = []
            stream = GoogleSTTV2Stream(config, on_event_callback=events.append)
            stream.active = True
            stream._stream_once = lambda: 0

            stream._run_stream()

            self.assertEqual(stream.active, False)
            self.assertTrue(any(event.get("type") == "error" for event in events))
            self.assertIn("returned no recognition responses", events[0]["message"])


@unittest.skipIf(cloud_speech is None, "google-cloud-speech v2 is not installed")
class GoogleSTTV2StreamTests(unittest.TestCase):
    def test_project_id_can_be_inferred_from_service_account_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            creds_path = f"{tmp}/service-account.json"
            with open(creds_path, "w", encoding="utf-8") as f:
                f.write('{"type": "service_account", "project_id": "json-project"}')
            config.update(
                {
                    "google.project_id": "",
                    "google.credential_mode": "service_account_json",
                    "google.credentials_path": creds_path,
                }
            )

            self.assertEqual(infer_project_id_from_credentials(config), "json-project")
            stream = GoogleSTTV2Stream(config)
            stream._active_location = "eu"
            self.assertEqual(stream._recognizer_name(), "projects/json-project/locations/eu/recognizers/_")

    def test_v2_config_builds_with_languages_model_and_adaptation(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            config.update(
                {
                    "google.project_id": "demo-project",
                    "google.location": "eu",
                    "google.recognizer_id": "_",
                    "google.model": "chirp_3",
                    "audio.sample_rate": 16000,
                    "languages.primary": "iw-IL",
                    "languages.alternatives": ["en-US"],
                    "languages.custom_code": "fr-FR",
                    "languages.custom_phrases": ["\u05e9\u05dc\u05d5\u05dd \u05e2\u05d5\u05dc\u05dd", "Codex"],
                }
            )

            stream = GoogleSTTV2Stream(config)
            recognition_config = stream._recognition_config()

            self.assertEqual(stream._recognizer_name(), "projects/demo-project/locations/eu/recognizers/_")
            self.assertEqual(recognition_config.model, "chirp_3")
            self.assertEqual(list(recognition_config.language_codes), ["iw-IL", "en-US", "fr-FR"])
            self.assertEqual(recognition_config.explicit_decoding_config.sample_rate_hertz, 16000)
            self.assertTrue(recognition_config.features.enable_automatic_punctuation)
            self.assertFalse(recognition_config.features.enable_word_confidence)
            self.assertTrue(recognition_config.adaptation.phrase_sets)

    def test_v2_streaming_config_requests_interim_and_voice_activity(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            config.update(
                {
                    "google.project_id": "demo-project",
                    "google.location": "eu",
                    "google.recognizer_id": "_",
                    "google.model": "chirp_3",
                    "google.interim_results": True,
                }
            )

            stream = GoogleSTTV2Stream(config)
            stream._active_location = "eu"
            stream.audio_queue = None
            first_request = next(stream._request_generator())

            self.assertTrue(first_request.streaming_config.streaming_features.interim_results)
            self.assertTrue(first_request.streaming_config.streaming_features.enable_voice_activity_events)
            self.assertFalse(
                first_request.streaming_config.streaming_features._pb.HasField("voice_activity_timeout")
            )

    def test_v2_streaming_config_adds_voice_activity_timeout_when_auto_stop_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            config.update(
                {
                    "google.project_id": "demo-project",
                    "google.location": "eu",
                    "google.recognizer_id": "_",
                    "google.model": "chirp_3",
                    "google.interim_results": True,
                    "speech.auto_stop_on_silence": True,
                }
            )

            stream = GoogleSTTV2Stream(config)
            stream._active_location = "eu"
            stream.audio_queue = None
            first_request = next(stream._request_generator())

            self.assertTrue(first_request.streaming_config.streaming_features.interim_results)
            self.assertTrue(first_request.streaming_config.streaming_features.enable_voice_activity_events)
            self.assertTrue(first_request.streaming_config.streaming_features._pb.HasField("voice_activity_timeout"))
            timeout = first_request.streaming_config.streaming_features.voice_activity_timeout
            self.assertEqual(timeout.speech_start_timeout.seconds, 5)
            self.assertEqual(timeout.speech_end_timeout.seconds, 1)

    def test_audio_chunks_are_kept_below_google_streaming_limit(self):
        chunks = list(GoogleSTTV2Stream._bounded_audio_chunks(b"x" * 50000))

        self.assertEqual([len(chunk) for chunk in chunks], [24000, 24000, 2000])

    def test_switch_to_fallback_updates_active_location_and_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            config.update(
                {
                    "google.location": "eu",
                    "google.model": "chirp_3",
                    "google.fallback_location": "us",
                    "google.fallback_model": "chirp_3",
                }
            )

            stream = GoogleSTTV2Stream(config)
            stream._active_location = "eu"
            stream._active_model = "chirp_3"
            created_clients = []
            stream._create_client = lambda location: created_clients.append(location) or object()

            self.assertTrue(stream._switch_to_fallback())
            self.assertEqual(stream._active_location, "us")
            self.assertEqual(stream._active_model, "chirp_3")
            self.assertEqual(created_clients, ["us"])
            self.assertFalse(stream._switch_to_fallback())


if __name__ == "__main__":
    unittest.main()
