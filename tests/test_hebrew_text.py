import unittest

from hebrew_live_dictation.hebrew_text import (
    delete_last_sentence_text,
    delete_last_word_text,
    format_hebrew_text,
    merge_transcript_segments,
    parse_voice_command,
    prepare_text_for_insert,
)


class HebrewTextTests(unittest.TestCase):
    def test_spoken_punctuation(self):
        self.assertEqual(
            format_hebrew_text("שלום נקודה מה נשמע סימן שאלה"),
            "שלום. מה נשמע?",
        )

    def test_newline_and_paragraph(self):
        self.assertEqual(
            format_hebrew_text("שלום שורה חדשה עולם פסקה חדשה סוף"),
            "שלום\nעולם\n\nסוף",
        )

    def test_common_voice_commands(self):
        self.assertEqual(parse_voice_command("מחק מילה אחרונה").action, "delete_last_word")
        self.assertEqual(parse_voice_command("נקה הכל").action, "clear_all")
        self.assertEqual(parse_voice_command("עצור").action, "stop")
        self.assertIsNone(parse_voice_command("שלום עצור בבקשה"))

    def test_dedupe_against_committed_text(self):
        self.assertEqual(
            prepare_text_for_insert("עולם חדש", "שלום עולם"),
            " חדש",
        )
        self.assertEqual(
            prepare_text_for_insert("שלום עולם", "שלום עולם"),
            "",
        )

    def test_merge_transcript_segments(self):
        self.assertEqual(
            merge_transcript_segments(["שלום עולם", "עולם חדש", "חדש מאוד"]),
            "שלום עולם חדש מאוד",
        )

    def test_delete_last_word(self):
        self.assertEqual(delete_last_word_text("שלום עולם"), "שלום")
        self.assertEqual(delete_last_word_text("שלום עולם  "), "שלום")

    def test_delete_last_sentence(self):
        self.assertEqual(delete_last_sentence_text("שלום עולם. מה נשמע"), "שלום עולם.")
        self.assertEqual(delete_last_sentence_text("שלום עולם."), "")


if __name__ == "__main__":
    unittest.main()
