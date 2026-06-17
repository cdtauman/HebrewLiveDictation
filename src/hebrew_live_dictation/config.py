import copy
import json
import logging
import os
from typing import Any

from .speech_presets import SUPPORTED_LOCATIONS, language_codes, model_ids, preset_for_language

logger = logging.getLogger("Config")

SCHEMA_VERSION = 4

DEFAULT_SETTINGS = {
    "schema_version": SCHEMA_VERSION,
    "app": {
        "ui_language": "he",
        "theme": "light",
        "startup_minimized": False,
        "show_overlay": True,
        "minimize_on_close": True,
        "start_with_windows": False,
        "first_run_completed": False,
    },
    "hotkeys": {
        "hotkey": "f8",
        "mode": "toggle",
    },
    "stt": {
        "provider": "google_v2",
        "mode": "api",
    },
    "google": {
        "api_version": "v2",
        "project_id": "",
        "location": "eu",
        "fallback_location": "us",
        "recognizer_id": "_",
        "model": "chirp_3",
        "fallback_model": "chirp_3",
        "credential_mode": "service_account_json",
        "credentials_path": "",
        "automatic_punctuation": True,
        "interim_results": True,
        "enable_spoken_punctuation": False,
        "enable_spoken_emoji": False,
        "phrase_boost": 15.0,
        "advanced_options": False,
    },
    "languages": {
        "primary": "iw-IL",
        "alternatives": [],
        "custom_code": "",
        "custom_phrases": [],
        "command_pack": "he",
    },
    "dictation": {
        "input_backend": "v1",
        "live_typing_mode": "final_only",
        "paste_method": "unicode",
        "restore_clipboard": True,
        "editing_strategy": "auto",
        "show_internal_preview": False,
        "debug_log_transcripts": False,
    },
    "audio": {
        "microphone_device": None,
        "sample_rate": 16000,
        "block_size": 1600,
    },
    "speech": {
        "frame_ms": 100,
        "endpointing": True,
        "auto_stop_on_silence": False,
        "speech_start_timeout_seconds": 5.0,
        "speech_end_timeout_seconds": 1.0,
        "max_stream_seconds": 285,
        "vad_enabled": False,
        "vad_threshold": 0.5,
        "vad_padding_ms": 240,
        "vad_min_silence_ms": 500,
    },
    "tsf": {
        "handshake_timeout_ms": 100,
        "experimental_transport_enabled": False,
        "allow_low_integrity_label": False,
    },
    "release": {
        "channel": "beta",
        "tsf_ime_target": "v2",
    },
    "packaging": {
        "app_name": "Hebrew Live Dictation",
        "company_name": "Local",
    },
}


ALIASES = {
    "hotkey": "hotkeys.hotkey",
    "mode": "hotkeys.mode",
    "language_code": "languages.primary",
    "alternative_language_code": "languages.alternatives.0",
    "automatic_punctuation": "google.automatic_punctuation",
    "interim_results": "google.interim_results",
    "aggressive_live_typing": "dictation.live_typing_mode",
    "live_typing_mode": "dictation.live_typing_mode",
    "input_backend": "dictation.input_backend",
    "paste_method": "dictation.paste_method",
    "restore_clipboard": "dictation.restore_clipboard",
    "microphone_device": "audio.microphone_device",
    "google_credentials_path": "google.credentials_path",
    "debug_log_transcripts": "dictation.debug_log_transcripts",
    "google_api_version": "google.api_version",
    "google_project_id": "google.project_id",
    "google_location": "google.location",
    "google_recognizer_id": "google.recognizer_id",
    "google_model": "google.model",
    "google_advanced_options": "google.advanced_options",
    "speech_frame_ms": "speech.frame_ms",
    "speech_endpointing": "speech.endpointing",
    "speech_auto_stop_on_silence": "speech.auto_stop_on_silence",
    "speech_vad_enabled": "speech.vad_enabled",
    "speech_vad_threshold": "speech.vad_threshold",
    "credential_mode": "google.credential_mode",
    "ui_language": "app.ui_language",
    "theme": "app.theme",
    "startup_minimized": "app.startup_minimized",
    "minimize_on_close": "app.minimize_on_close",
    "start_with_windows": "app.start_with_windows",
    "show_overlay": "app.show_overlay",
    "editing_strategy": "dictation.editing_strategy",
}


class Config:
    def __init__(self, config_dir: str):
        self.config_dir = config_dir
        if not os.path.exists(config_dir):
            os.makedirs(config_dir, exist_ok=True)
        self.filepath = os.path.join(config_dir, "settings.json")
        self.settings = copy.deepcopy(DEFAULT_SETTINGS)
        self.load()

    def load(self):
        if not os.path.exists(self.filepath):
            logger.info("settings.json not found. Creating default config.")
            self.save()
            return

        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)

            if self._is_legacy_settings(data):
                self.settings = self._migrate_legacy_settings(data)
                self._normalize_settings()
                logger.info("Migrated legacy settings.json to schema version %s.", SCHEMA_VERSION)
                self.save()
            else:
                incoming_schema_version = int(data.get("schema_version", 0) or 0)
                self.settings = self._deep_merge(copy.deepcopy(DEFAULT_SETTINGS), data)
                self.settings["schema_version"] = SCHEMA_VERSION
                before_normalize = copy.deepcopy(self.settings)
                if incoming_schema_version < 4 and self.settings.get("audio", {}).get("block_size") == 1024:
                    self.settings["audio"]["block_size"] = DEFAULT_SETTINGS["audio"]["block_size"]
                self._normalize_settings()
                if (
                    data.get("schema_version") != SCHEMA_VERSION
                    or "aggressive_live_typing" in data.get("dictation", {})
                    or self.settings != before_normalize
                ):
                    self.save()
                logger.info("Config loaded successfully.")
        except Exception as e:
            logger.error(f"Error loading settings.json: {e}. Using defaults.")
            self.settings = copy.deepcopy(DEFAULT_SETTINGS)

    def save(self):
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=2, ensure_ascii=False)
            logger.info("Config saved successfully.")
        except Exception as e:
            logger.error(f"Error saving settings.json: {e}")

    def get(self, key: str, default: Any = None):
        return self._get_path(self._resolve_key(key), default)

    def set(self, key: str, value: Any):
        self._set_path(self._resolve_key(key), value)
        self._normalize_settings()
        self.save()

    def update(self, values: dict[str, Any]):
        for key, value in values.items():
            self._set_path(self._resolve_key(key), value)
        self._normalize_settings()
        self.save()

    def as_dict(self):
        return copy.deepcopy(self.settings)

    def _resolve_key(self, key: str) -> str:
        return ALIASES.get(key, key)

    def _get_path(self, path: str, default=None):
        current = self.settings
        for part in path.split("."):
            if isinstance(current, list):
                try:
                    current = current[int(part)]
                except (ValueError, IndexError):
                    return default
            elif isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return default
        return current

    def _set_path(self, path: str, value: Any):
        current = self.settings
        parts = path.split(".")
        for part in parts[:-1]:
            if isinstance(current, list):
                index = int(part)
                while len(current) <= index:
                    current.append({})
                current = current[index]
            else:
                current = current.setdefault(part, {})

        last = parts[-1]
        if isinstance(current, list):
            index = int(last)
            while len(current) <= index:
                current.append(None)
            current[index] = value
        else:
            current[last] = value

    @staticmethod
    def _deep_merge(base: dict, incoming: dict) -> dict:
        for key, value in incoming.items():
            if isinstance(value, dict) and isinstance(base.get(key), dict):
                base[key] = Config._deep_merge(base[key], value)
            else:
                base[key] = value
        return base

    @staticmethod
    def _is_legacy_settings(data: dict) -> bool:
        return "schema_version" not in data and any(key in data for key in ALIASES)

    def _migrate_legacy_settings(self, data: dict) -> dict:
        migrated = copy.deepcopy(DEFAULT_SETTINGS)

        for legacy_key, path in ALIASES.items():
            if legacy_key in data:
                value = data[legacy_key]
                if legacy_key == "aggressive_live_typing":
                    value = "final_only"
                self.settings = migrated
                self._set_path(path, value)
                migrated = self.settings

        if "language_code" in data:
            migrated["languages"]["primary"] = data["language_code"]
        if "alternative_language_code" in data and data["alternative_language_code"]:
            migrated["languages"]["alternatives"] = [data["alternative_language_code"]]
        if "google_credentials_path" in data:
            migrated["google"]["credentials_path"] = data["google_credentials_path"]

        migrated["schema_version"] = SCHEMA_VERSION
        return migrated

    def _normalize_settings(self):
        google = self.settings.setdefault("google", {})
        google["api_version"] = "v2"
        google["advanced_options"] = bool(google.get("advanced_options", False))
        allowed_locations = set(SUPPORTED_LOCATIONS if google["advanced_options"] else ("eu", "us"))
        allowed_models = set(model_ids(include_advanced=google["advanced_options"]))
        if google.get("location") not in allowed_locations:
            google["location"] = DEFAULT_SETTINGS["google"]["location"]
        if google.get("fallback_location") not in allowed_locations:
            google["fallback_location"] = DEFAULT_SETTINGS["google"]["fallback_location"]
        if google.get("fallback_location") == google.get("location"):
            google["fallback_location"] = "us" if google.get("location") == "eu" else "eu"
            if google["fallback_location"] not in allowed_locations:
                google["fallback_location"] = "global" if "global" in allowed_locations else "us"
        if google.get("model") not in allowed_models:
            google["model"] = DEFAULT_SETTINGS["google"]["model"]
        if google.get("fallback_model") not in allowed_models:
            google["fallback_model"] = DEFAULT_SETTINGS["google"]["fallback_model"]

        dictation = self.settings.setdefault("dictation", {})

        if (
            "aggressive_live_typing" in dictation
            and dictation.get("live_typing_mode") == DEFAULT_SETTINGS["dictation"]["live_typing_mode"]
        ):
            dictation["live_typing_mode"] = "final_only"
        elif "live_typing_mode" not in dictation:
            dictation["live_typing_mode"] = "final_only"

        if isinstance(dictation.get("live_typing_mode"), bool):
            dictation["live_typing_mode"] = "final_only"

        if dictation.get("live_typing_mode") not in {"final_only", "live"}:
            dictation["live_typing_mode"] = "final_only"

        if dictation.get("input_backend") not in {"v1", "tsf"}:
            dictation["input_backend"] = "v1"

        if dictation.get("paste_method") not in {"unicode", "clipboard"}:
            dictation["paste_method"] = "unicode"
        if dictation.get("paste_method") == "clipboard":
            dictation["paste_method"] = "unicode"

        dictation.pop("aggressive_live_typing", None)

        languages = self.settings.setdefault("languages", {})
        custom_code = str(languages.get("custom_code", "") or "").strip()
        primary = custom_code or languages.get("primary", "iw-IL")
        if primary == "he-IL":
            primary = "iw-IL"
            languages["primary"] = primary
        alternatives = languages.get("alternatives", [])
        if isinstance(alternatives, str):
            alternatives = [part.strip() for part in alternatives.split(",") if part.strip()]

        known_codes = set(language_codes())
        if not custom_code and primary not in known_codes:
            primary = DEFAULT_SETTINGS["languages"]["primary"]
            languages["primary"] = primary

        preset = preset_for_language(languages.get("primary", primary))
        if preset and not google["advanced_options"]:
            google["location"] = preset.primary_location
            google["fallback_location"] = preset.fallback_location
            google["model"] = preset.primary_model
            google["fallback_model"] = DEFAULT_SETTINGS["google"]["fallback_model"]
            languages["command_pack"] = preset.command_pack

        if primary in ("he-IL", "iw-IL"):
            alternatives = [code for code in alternatives if code != primary]
            alternatives = [code for code in alternatives if code != "he-IL"]
            languages["command_pack"] = languages.get("command_pack") or "he"

        languages["alternatives"] = alternatives

        audio = self.settings.setdefault("audio", {})
        audio["sample_rate"] = int(audio.get("sample_rate") or DEFAULT_SETTINGS["audio"]["sample_rate"])
        audio["block_size"] = int(audio.get("block_size") or DEFAULT_SETTINGS["audio"]["block_size"])

        speech = self.settings.setdefault("speech", {})
        speech["frame_ms"] = int(speech.get("frame_ms") or DEFAULT_SETTINGS["speech"]["frame_ms"])
        if speech["frame_ms"] < 20 or speech["frame_ms"] > 1000:
            speech["frame_ms"] = DEFAULT_SETTINGS["speech"]["frame_ms"]
        speech["endpointing"] = bool(speech.get("endpointing", True))
        speech["auto_stop_on_silence"] = bool(speech.get("auto_stop_on_silence", False))
        speech["vad_enabled"] = bool(speech.get("vad_enabled", False))
        speech["vad_threshold"] = max(0.0, min(1.0, float(speech.get("vad_threshold", 0.5))))
        speech["speech_start_timeout_seconds"] = max(
            0.5,
            min(60.0, float(speech.get("speech_start_timeout_seconds", 5.0))),
        )
        speech["speech_end_timeout_seconds"] = max(
            0.5,
            min(60.0, float(speech.get("speech_end_timeout_seconds", 1.0))),
        )
        speech["max_stream_seconds"] = max(30, min(295, int(speech.get("max_stream_seconds", 285))))
        speech["vad_padding_ms"] = max(0, int(speech.get("vad_padding_ms", 240)))
        speech["vad_min_silence_ms"] = max(100, int(speech.get("vad_min_silence_ms", 500)))

        stt = self.settings.setdefault("stt", {})
        provider = stt.get("provider")
        if not isinstance(provider, str) or not provider.strip():
            stt["provider"] = DEFAULT_SETTINGS["stt"]["provider"]
        if stt.get("mode") not in {"api", "local", "auto_fallback"}:
            stt["mode"] = DEFAULT_SETTINGS["stt"]["mode"]

        tsf = self.settings.setdefault("tsf", {})
        tsf["handshake_timeout_ms"] = max(50, min(150, int(tsf.get("handshake_timeout_ms", 100))))
        tsf["experimental_transport_enabled"] = bool(tsf.get("experimental_transport_enabled", False))
        tsf["allow_low_integrity_label"] = bool(tsf.get("allow_low_integrity_label", False))

        release = self.settings.setdefault("release", {})
        release["channel"] = release.get("channel") or DEFAULT_SETTINGS["release"]["channel"]
        release["tsf_ime_target"] = release.get("tsf_ime_target") or DEFAULT_SETTINGS["release"]["tsf_ime_target"]
