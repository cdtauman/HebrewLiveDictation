import unittest
from pathlib import Path


class UnicodeIntegrityTests(unittest.TestCase):
    def test_user_facing_sources_do_not_contain_common_mojibake_markers(self):
        root = Path(__file__).resolve().parents[1]
        source_files = (
            [path for path in (root / "src").rglob("*.py")]
            + [path for path in root.glob("*.py") if path.name not in {"hebrew_live_dictation.log"}]
            + list((root / "tests").glob("test_*.py"))
        )
        geresh = chr(0x05F3)
        forbidden = (
            geresh + chr(0x00A9),
            geresh + chr(0x00DE),
            geresh + chr(0x00DC),
            geresh + chr(0x00A2),
            geresh + chr(0x00A0),
            geresh + chr(0x00A4),
            geresh + chr(0x00AA),
            chr(0x05E0) + chr(0x009F),
            chr(0x05D2) + chr(0x009D),
            chr(0x05D2) + chr(0x20AC),
        )

        offenders = []
        for path in source_files:
            text = path.read_text(encoding="utf-8", errors="replace")
            hits = [marker for marker in forbidden if marker in text]
            if hits:
                offenders.append(f"{path.relative_to(root)}: {hits!r}")

        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
