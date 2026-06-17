from .language_packs import (
    VoiceCommand,
    delete_last_sentence_text,
    delete_last_word_text,
    format_text,
    merge_transcript_segments as _merge_transcript_segments,
    parse_voice_command as _parse_voice_command,
    prepare_text_for_insert as _prepare_text_for_insert,
)


DEFAULT_HEBREW_LANGUAGE = "iw-IL"
DEFAULT_HEBREW_COMMAND_PACK = "he"


def format_hebrew_text(text: str) -> str:
    return format_text(text, DEFAULT_HEBREW_LANGUAGE, DEFAULT_HEBREW_COMMAND_PACK)


def parse_voice_command(text: str) -> VoiceCommand | None:
    return _parse_voice_command(text, DEFAULT_HEBREW_LANGUAGE, DEFAULT_HEBREW_COMMAND_PACK)


def prepare_text_for_insert(raw_text: str, committed: str = "") -> str:
    return _prepare_text_for_insert(raw_text, committed, DEFAULT_HEBREW_LANGUAGE, DEFAULT_HEBREW_COMMAND_PACK)


def merge_transcript_segments(segments: list[str]) -> str:
    return _merge_transcript_segments(segments, DEFAULT_HEBREW_LANGUAGE, DEFAULT_HEBREW_COMMAND_PACK)
