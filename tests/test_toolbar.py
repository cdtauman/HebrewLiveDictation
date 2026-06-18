import tempfile
import unittest

from hebrew_live_dictation.config import Config
from hebrew_live_dictation.qt_app import clamp_position


class ClampPositionTests(unittest.TestCase):
    SCREEN = (0, 0, 1920, 1080)

    def test_in_bounds_unchanged(self):
        self.assertEqual(clamp_position(100, 100, 160, 52, self.SCREEN), (100, 100))

    def test_off_right_and_bottom_clamped(self):
        x, y = clamp_position(5000, 5000, 160, 52, self.SCREEN)
        self.assertEqual(x, 1920 - 160)
        self.assertEqual(y, 1080 - 52)

    def test_negative_clamped_to_origin(self):
        self.assertEqual(clamp_position(-50, -50, 160, 52, self.SCREEN), (0, 0))

    def test_respects_screen_offset(self):
        x, y = clamp_position(-10, -10, 100, 40, (1920, 0, 1920, 1080))
        self.assertEqual((x, y), (1920, 0))


class ToolbarConfigTests(unittest.TestCase):
    def test_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            self.assertFalse(config.get("toolbar.enabled"))
            self.assertFalse(config.get("toolbar.idle_button"))
            self.assertIsNone(config.get("toolbar.position"))

    def test_position_roundtrip_and_invalid_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            config.update({"toolbar.position": {"x": 10, "y": 20}})
            self.assertEqual(config.get("toolbar.position"), {"x": 10, "y": 20})
            config.update({"toolbar.position": "garbage"})
            self.assertIsNone(config.get("toolbar.position"))


if __name__ == "__main__":
    unittest.main()
