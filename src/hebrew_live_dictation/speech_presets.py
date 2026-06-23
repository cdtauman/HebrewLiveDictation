from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LanguagePreset:
    code: str
    label: str
    command_pack: str
    rtl: bool = False
    primary_model: str = "chirp_3"
    primary_location: str = "eu"
    fallback_location: str = "us"


@dataclass(frozen=True)
class ModelPreset:
    model: str
    label: str
    stable: bool
    warning: str = ""


SUPPORTED_LOCATIONS = (
    "eu",
    "us",
    "global",
    "asia-southeast1",
    "asia-northeast1",
    "asia-south1",
    "europe-west2",
    "europe-west3",
    "europe-west4",
    "northamerica-northeast1",
    "us-central1",
)


LANGUAGE_PRESET_LIST = (
    LanguagePreset("iw-IL", "Hebrew", "he", True),
    LanguagePreset("he-IL", "Hebrew (diagnostic alias)", "he", True),
    LanguagePreset("en-US", "English (United States)", "en"),
    LanguagePreset("en-GB", "English (United Kingdom)", "en", primary_location="eu", fallback_location="us"),
    LanguagePreset("ar-XA", "Arabic", "ar", True, primary_location="asia-southeast1", fallback_location="global"),
    LanguagePreset("ar-EG", "Arabic (Egypt)", "ar", True, primary_location="asia-southeast1", fallback_location="global"),
    LanguagePreset("fr-FR", "French (France)", "fr", primary_location="eu", fallback_location="global"),
    LanguagePreset("es-ES", "Spanish (Spain)", "es", primary_location="eu", fallback_location="global"),
    LanguagePreset("ru-RU", "Russian", "ru", primary_location="eu", fallback_location="global"),
)


LANGUAGE_PRESETS = {preset.code: preset for preset in LANGUAGE_PRESET_LIST}


MODEL_PRESET_LIST = (
    ModelPreset("chirp_3", "Chirp 3", True),
    ModelPreset("chirp_2", "Chirp 2", False, "Advanced mode: validate language and region support first."),
    ModelPreset("chirp", "Chirp", False, "Advanced mode: older Chirp family, not tuned for this beta."),
    ModelPreset("latest_long", "Latest Long", False, "Advanced mode: may not exist for every V2 region/language."),
    ModelPreset("latest_short", "Latest Short", False, "Advanced mode: short utterance model, not continuous dictation."),
)


MODEL_PRESETS = {preset.model: preset for preset in MODEL_PRESET_LIST}


def language_codes() -> list[str]:
    return [preset.code for preset in LANGUAGE_PRESET_LIST]


def model_ids(include_advanced: bool = False) -> list[str]:
    if include_advanced:
        return [preset.model for preset in MODEL_PRESET_LIST]
    return [preset.model for preset in MODEL_PRESET_LIST if preset.stable]


def location_ids(include_advanced: bool = False) -> list[str]:
    if include_advanced:
        return list(SUPPORTED_LOCATIONS)
    return ["eu", "us"]


def preset_for_language(code: str) -> LanguagePreset | None:
    if code == "he-IL":
        code = "iw-IL"
    return LANGUAGE_PRESETS.get(code)
