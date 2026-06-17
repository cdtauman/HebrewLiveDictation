import re
from dataclasses import dataclass, field


WORD_BOUNDARY = r"\w\u0590-\u05FF\u0600-\u06FF\u0400-\u04FF"


@dataclass(frozen=True)
class VoiceCommand:
    action: str
    phrase: str
    args: dict[str, str] = field(default_factory=dict)


LANGUAGE_PRESETS = {
    "iw-IL": {"name": "עברית", "command_pack": "he", "rtl": True},
    "he-IL": {"name": "עברית", "command_pack": "he", "rtl": True},
    "en-US": {"name": "English (US)", "command_pack": "en", "rtl": False},
    "ar-XA": {"name": "Arabic", "command_pack": "ar", "rtl": True},
    "ar": {"name": "Arabic", "command_pack": "ar", "rtl": True},
    "ru-RU": {"name": "Russian", "command_pack": "ru", "rtl": False},
    "fr-FR": {"name": "French", "command_pack": "fr", "rtl": False},
    "es-ES": {"name": "Spanish", "command_pack": "es", "rtl": False},
}

LANGUAGE_PRESETS.update(
    {
        "en-GB": {"name": "English (UK)", "command_pack": "en", "rtl": False},
        "ar-EG": {"name": "Arabic (Egypt)", "command_pack": "ar", "rtl": True},
    }
)


PACKS = {
    "he": {
        "punctuation": (
            ("סימן שאלה", "?"),
            ("סימן קריאה", "!"),
            ("נקודה ופסיק", ";"),
            ("נקודתיים", ":"),
            ("פסקה חדשה", "\n\n"),
            ("שורה חדשה", "\n"),
            ("שורה הבאה", "\n"),
            ("רד שורה", "\n"),
            ("פסיק", ","),
            ("נקודה", "."),
            ("פתח סוגריים", " ("),
            ("סגור סוגריים", ") "),
            ("פתח מרכאות", ' "'),
            ("סגור מרכאות", '" '),
        ),
        "emoji": (
            ("אימוג'י סמיילי", "😊"),
            ("אימוג׳י סמיילי", "😊"),
            ("אימוגי סמיילי", "😊"),
            ("אימוג'י לב", "❤️"),
            ("אימוג׳י לב", "❤️"),
            ("אימוגי לב", "❤️"),
            ("אימוג'י צוחק", "😂"),
            ("אימוג׳י צוחק", "😂"),
            ("אימוגי צוחק", "😂"),
            ("אימוג'י אש", "🔥"),
            ("אימוג׳י אש", "🔥"),
            ("אימוגי אש", "🔥"),
            ("אימוג'י וי", "✅"),
            ("אימוג׳י וי", "✅"),
            ("אימוגי וי", "✅"),
        ),
        "commands": {
            "עצור": "stop",
            "הפסק": "stop",
            "תפסיק": "stop",
            "סיים הכתבה": "stop",
            "מחק מילה אחרונה": "delete_last_word",
            "מחק את המילה האחרונה": "delete_last_word",
            "מחק משפט אחרון": "delete_last_sentence",
            "מחק את המשפט האחרון": "delete_last_sentence",
            "נקה הכל": "clear_all",
            "נקה את הכל": "clear_all",
            "מחק הכל": "clear_all",
            "מחק את הכל": "clear_all",
            "בטל": "undo",
            "בטל פעולה": "undo",
            "חזור אחורה": "undo",
            "שלח": "send",
            "שלח הודעה": "send",
            "שליחה": "send",
            "עבור לשדה הבא": "next_field",
            "שדה הבא": "next_field",
            "הבא": "next_field",
            "טאב": "next_field",
            "בחר מילה אחרונה": "select_last_word",
            "בחר את המילה האחרונה": "select_last_word",
            "בחר משפט אחרון": "select_last_sentence",
            "בחר את המשפט האחרון": "select_last_sentence",
        },
        "patterns": (
            ("replace_phrase", r"^(?:החלף|תחליף|תקן)\s+(.+?)\s+(?:ב|ל)-?\s*(.+)$", ("old", "new")),
            ("delete_phrase", r"^מחק\s+(?:את\s+)?(.+)$", ("target",)),
        ),
    },
    "en": {
        "punctuation": (
            ("question mark", "?"),
            ("exclamation mark", "!"),
            ("new paragraph", "\n\n"),
            ("new line", "\n"),
            ("comma", ","),
            ("period", "."),
            ("full stop", "."),
            ("colon", ":"),
            ("semicolon", ";"),
        ),
        "emoji": (("smiley emoji", "😊"), ("heart emoji", "❤️"), ("laughing emoji", "😂")),
        "commands": {
            "stop": "stop",
            "delete last word": "delete_last_word",
            "delete last sentence": "delete_last_sentence",
            "clear all": "clear_all",
            "undo": "undo",
            "send": "send",
            "next field": "next_field",
            "tab": "next_field",
            "select last word": "select_last_word",
            "select the last word": "select_last_word",
            "select last sentence": "select_last_sentence",
            "select the last sentence": "select_last_sentence",
        },
        "patterns": (
            ("replace_phrase", r"^replace\s+(.+?)\s+with\s+(.+)$", ("old", "new")),
            ("delete_phrase", r"^delete\s+(.+)$", ("target",)),
        ),
    },
    "ar": {
        "punctuation": (
            ("علامة استفهام", "?"),
            ("علامة تعجب", "!"),
            ("سطر جديد", "\n"),
            ("فقرة جديدة", "\n\n"),
            ("فاصلة", ","),
            ("نقطة", "."),
        ),
        "emoji": (("إيموجي ابتسامة", "😊"), ("إيموجي قلب", "❤️")),
        "commands": {
            "توقف": "stop",
            "احذف آخر كلمة": "delete_last_word",
            "امسح الكل": "clear_all",
            "تراجع": "undo",
            "أرسل": "send",
        },
        "patterns": (),
    },
    "ru": {
        "punctuation": (
            ("вопросительный знак", "?"),
            ("восклицательный знак", "!"),
            ("новая строка", "\n"),
            ("новый абзац", "\n\n"),
            ("запятая", ","),
            ("точка", "."),
        ),
        "emoji": (("смайлик эмодзи", "😊"),),
        "commands": {
            "стоп": "stop",
            "удалить последнее слово": "delete_last_word",
            "очистить всё": "clear_all",
            "отменить": "undo",
            "отправить": "send",
        },
        "patterns": (),
    },
    "fr": {
        "punctuation": (
            ("point d'interrogation", "?"),
            ("point d’exclamation", "!"),
            ("nouvelle ligne", "\n"),
            ("nouveau paragraphe", "\n\n"),
            ("virgule", ","),
            ("point", "."),
        ),
        "emoji": (("emoji sourire", "😊"),),
        "commands": {
            "stop": "stop",
            "arrêter": "stop",
            "supprimer le dernier mot": "delete_last_word",
            "tout effacer": "clear_all",
            "annuler": "undo",
            "envoyer": "send",
        },
        "patterns": (),
    },
    "es": {
        "punctuation": (
            ("signo de interrogación", "?"),
            ("signo de exclamación", "!"),
            ("nueva línea", "\n"),
            ("nuevo párrafo", "\n\n"),
            ("coma", ","),
            ("punto", "."),
        ),
        "emoji": (("emoji sonrisa", "😊"),),
        "commands": {
            "detener": "stop",
            "borrar última palabra": "delete_last_word",
            "borrar todo": "clear_all",
            "deshacer": "undo",
            "enviar": "send",
        },
        "patterns": (),
    },
}


def command_pack_for_language(language_code: str, explicit_pack: str | None = None) -> str:
    if explicit_pack and explicit_pack in PACKS:
        return explicit_pack
    preset = LANGUAGE_PRESETS.get(language_code)
    if preset:
        return preset["command_pack"]
    return (language_code or "he").split("-")[0].lower()


def get_pack(language_code: str = "iw-IL", command_pack: str | None = None) -> dict:
    pack_name = command_pack_for_language(language_code, command_pack)
    return PACKS.get(pack_name, PACKS["he"])


def normalize_spaces(text: str) -> str:
    text = re.sub(r"[ \t\r\f\v]+", " ", text or "")
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.lstrip()
    text = re.sub(r"[ \t]+$", "", text)
    return text


def normalize_command_text(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[\"'׳״`.,!?;:()\[\]{}]+", "", text)
    return normalize_spaces(text)


def _phrase_pattern(phrase: str) -> re.Pattern:
    escaped = re.escape(phrase)
    return re.compile(rf"(?<![{WORD_BOUNDARY}]){escaped}(?![{WORD_BOUNDARY}])", re.IGNORECASE)


def _replace_spoken_phrase(text: str, phrase: str, replacement: str) -> str:
    padded = replacement if replacement.startswith("\n") else f" {replacement} "
    return _phrase_pattern(phrase).sub(padded, text)


def format_text(text: str, language_code: str = "iw-IL", command_pack: str | None = None) -> str:
    pack = get_pack(language_code, command_pack)
    for phrase, replacement in pack.get("emoji", ()):
        text = _replace_spoken_phrase(text, phrase, replacement)
    for phrase, replacement in pack.get("punctuation", ()):
        text = _replace_spoken_phrase(text, phrase, replacement)

    text = normalize_spaces(text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"([,.;:!?])(?=\S)", r"\1 ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.lstrip()
    return re.sub(r"[ \t]+$", "", text)


def parse_voice_command(
    text: str,
    language_code: str = "iw-IL",
    command_pack: str | None = None,
) -> VoiceCommand | None:
    pack = get_pack(language_code, command_pack)
    phrase = normalize_command_text(text)
    action = pack.get("commands", {}).get(phrase)
    if action:
        return VoiceCommand(action=action, phrase=phrase)

    for action, pattern, arg_names in pack.get("patterns", ()):
        match = re.match(pattern, phrase, flags=re.IGNORECASE)
        if match:
            args = {name: match.group(index + 1).strip() for index, name in enumerate(arg_names)}
            return VoiceCommand(action=action, phrase=phrase, args=args)
    return None


def needs_leading_space(committed: str, fragment: str) -> bool:
    if not committed or not fragment:
        return False
    if committed[-1] in (" ", "\n") or fragment[0] in (" ", "\n"):
        return False
    return fragment[0] not in ".,;:!?"


def _normalized_for_overlap(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def dedupe_fragment(committed: str, incoming: str) -> str:
    incoming = (incoming or "").strip()
    if not committed or not incoming:
        return incoming

    committed_norm = _normalized_for_overlap(committed)
    incoming_norm = _normalized_for_overlap(incoming)
    if not committed_norm or not incoming_norm:
        return incoming
    if committed_norm.endswith(incoming_norm):
        return ""

    max_len = min(len(committed_norm), len(incoming_norm))
    for size in range(max_len, 2, -1):
        if committed_norm[-size:] == incoming_norm[:size]:
            return incoming_norm[size:].lstrip()

    committed_words = committed_norm.split()
    incoming_words = incoming_norm.split()
    for count in range(min(len(committed_words), len(incoming_words)), 0, -1):
        if committed_words[-count:] == incoming_words[:count]:
            return " ".join(incoming_words[count:])

    return incoming


def prepare_text_for_insert(
    raw_text: str,
    committed: str = "",
    language_code: str = "iw-IL",
    command_pack: str | None = None,
) -> str:
    fragment = dedupe_fragment(committed, format_text(raw_text, language_code, command_pack))
    if needs_leading_space(committed, fragment):
        fragment = " " + fragment
    return fragment


def merge_transcript_segments(
    segments: list[str],
    language_code: str = "iw-IL",
    command_pack: str | None = None,
) -> str:
    merged = ""
    for segment in segments:
        segment = normalize_spaces(segment)
        if not segment:
            continue
        merged += prepare_text_for_insert(segment, merged, language_code, command_pack)
    return merged.strip()


def delete_last_word_text(text: str) -> str:
    stripped = (text or "").rstrip()
    if not stripped:
        return ""
    return re.sub(r"\s*\S+$", "", stripped).rstrip()


def delete_last_sentence_text(text: str) -> str:
    stripped = (text or "").rstrip()
    if not stripped:
        return ""

    scan_end = len(stripped) - 1
    while scan_end >= 0 and stripped[scan_end] in ".?!":
        scan_end -= 1

    last_boundary = -1
    for mark in ".?!\n":
        last_boundary = max(last_boundary, stripped.rfind(mark, 0, scan_end + 1))

    if last_boundary == -1:
        return ""
    return stripped[: last_boundary + 1].rstrip()
