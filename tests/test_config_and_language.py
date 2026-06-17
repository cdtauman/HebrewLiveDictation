import json
import tempfile
import unittest
from pathlib import Path

from hebrew_live_dictation.audio_stream import AudioStream
import hebrew_live_dictation.audio_stream as audio_stream_module
from hebrew_live_dictation.config import Config
from hebrew_live_dictation.i18n import friendly_error, tr
from hebrew_live_dictation.language_packs import format_text, parse_voice_command, prepare_text_for_insert
from hebrew_live_dictation.text_diff import compute_end_rewrite


class ConfigAndLanguageTests(unittest.TestCase):
    def test_legacy_settings_migrate_to_schema_v4(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(
                json.dumps(
                    {
                        "hotkey": "f8",
                        "mode": "toggle",
                        "language_code": "he-IL",
                        "alternative_language_code": "en-US",
                        "google_credentials_path": "C:/creds.json",
                        "aggressive_live_typing": True,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            config = Config(tmp)
            self.assertEqual(config.get("schema_version"), 4)
            self.assertEqual(config.get("hotkey"), "f8")
            self.assertEqual(config.get("dictation.live_typing_mode"), "final_only")
            self.assertEqual(config.get("dictation.input_backend"), "v1")
            self.assertEqual(config.get("dictation.paste_method"), "unicode")
            self.assertEqual(config.get("languages.primary"), "iw-IL")
            self.assertEqual(config.get("languages.alternatives"), ["en-US"])
            self.assertEqual(config.get("google.api_version"), "v2")
            self.assertEqual(config.get("google.location"), "eu")
            self.assertEqual(config.get("google.model"), "chirp_3")
            self.assertEqual(config.get("speech.frame_ms"), 100)
            self.assertTrue(config.get("speech.endpointing"))
            self.assertFalse(config.get("speech.auto_stop_on_silence"))
            self.assertEqual(config.get("tsf.handshake_timeout_ms"), 100)
            self.assertFalse(config.get("tsf.experimental_transport_enabled"))
            self.assertEqual(config.get("google.credentials_path"), "C:/creds.json")
            self.assertEqual(config.get("app.theme"), "light")

    def test_schema_v2_aggressive_live_typing_migrates_to_final_only_v4(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "dictation": {
                            "aggressive_live_typing": False,
                            "restore_clipboard": True,
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            config = Config(tmp)
            self.assertEqual(config.get("schema_version"), 4)
            self.assertEqual(config.get("dictation.live_typing_mode"), "final_only")
            self.assertIsNone(config.get("dictation.aggressive_live_typing"))

    def test_v1_beta_normalizes_google_surface(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 3,
                        "google": {
                            "api_version": "v1",
                            "location": "europe-west4",
                            "model": "chirp_2",
                            "fallback_location": "global",
                            "fallback_model": "latest_long",
                        },
                        "audio": {"sample_rate": 16000, "block_size": 1024},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            config = Config(tmp)

            self.assertEqual(config.get("google.api_version"), "v2")
            self.assertEqual(config.get("google.location"), "eu")
            self.assertEqual(config.get("google.fallback_location"), "us")
            self.assertEqual(config.get("google.model"), "chirp_3")
            self.assertEqual(config.get("google.fallback_model"), "chirp_3")
            self.assertEqual(config.get("audio.block_size"), 1600)

    def test_english_pack_formats_punctuation(self):
        self.assertEqual(format_text("hello comma world period", "en-US"), "hello, world.")

    def test_hebrew_replace_command_pattern(self):
        command = parse_voice_command("תקן עולם לכולם", "iw-IL", "he")
        self.assertEqual(command.action, "replace_phrase")
        self.assertEqual(command.args["old"], "עולם")
        self.assertEqual(command.args["new"], "כולם")

    def test_prepare_text_for_insert_respects_language(self):
        self.assertEqual(prepare_text_for_insert("world period", "hello", "en-US", "en"), " world.")

    def test_select_phrase_is_not_a_supported_command(self):
        self.assertIsNone(parse_voice_command("select hello", "en-US", "en"))
        self.assertIsNone(parse_voice_command("choose hello", "en-US", "en"))

    def test_minimal_end_rewrite(self):
        plan = compute_end_rewrite("שלום עולם יפה", "שלום עולם")
        self.assertEqual(plan.common_prefix, "שלום עולם")
        self.assertEqual(plan.chars_to_delete, 4)
        self.assertEqual(plan.text_to_insert, "")

    def test_i18n_returns_hebrew_and_friendly_adc_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            config.update({"app.ui_language": "he"})
            self.assertEqual(tr(config, "ready"), "מוכן")
            self.assertIn("ADC", friendly_error(config, "Your default credentials were not found"))

    def test_audio_filters_virtual_windows_devices(self):
        self.assertTrue(AudioStream._is_virtual_or_mapper("Microsoft Sound Mapper - Input"))
        self.assertTrue(AudioStream._is_virtual_or_mapper("Input (@System32\\drivers\\bthhfenum.sys)"))
        self.assertFalse(AudioStream._is_virtual_or_mapper("Headset (Baseus Bass EH10 NC)"))

    def test_audio_retries_device_default_rate_and_resamples_to_16khz(self):
        created_streams = []

        class FakeRawInputStream:
            def __init__(self, samplerate, blocksize, device, channels, dtype, callback):
                if samplerate == 16000:
                    raise RuntimeError("Invalid sample rate")
                self.samplerate = samplerate
                self.blocksize = blocksize
                self.callback = callback
                created_streams.append(self)

            def start(self):
                return None

            def stop(self):
                return None

            def close(self):
                return None

        class FakeSoundDevice:
            RawInputStream = FakeRawInputStream

            @staticmethod
            def query_devices(device=None, kind=None):
                if kind == "input":
                    return {"default_samplerate": 48000}
                return []

        original_sounddevice = audio_stream_module._sounddevice
        audio_stream_module._sounddevice = lambda: FakeSoundDevice
        try:
            stream = AudioStream(sample_rate=16000, block_size=1600)
            self.assertTrue(stream.start())
            self.assertEqual(stream.stream_sample_rate, 48000)
            self.assertEqual(stream.stream_block_size, 4800)

            silence_48k_100ms = b"\x00\x00" * 4800
            stream._audio_callback(silence_48k_100ms, 4800, None, None)
            converted = stream.get_queue().get_nowait()
            self.assertEqual(len(converted), 3200)
        finally:
            audio_stream_module._sounddevice = original_sounddevice


if __name__ == "__main__":
    unittest.main()
