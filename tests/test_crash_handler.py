import logging
import sys
import unittest

from hebrew_live_dictation import crash_handler


class CrashHandlerTests(unittest.TestCase):
    def setUp(self):
        self._saved_excepthook = sys.excepthook

    def tearDown(self):
        sys.excepthook = self._saved_excepthook

    def _capture_logs(self):
        records = []

        class _Capture(logging.Handler):
            def emit(self, record):
                records.append(record)

        handler = _Capture()
        crash_handler.logger.addHandler(handler)
        self.addCleanup(crash_handler.logger.removeHandler, handler)
        return records

    def test_install_sets_excepthook(self):
        crash_handler.install_crash_handlers(show_dialog=False)
        self.assertIsNotNone(sys.excepthook)
        self.assertNotEqual(sys.excepthook, self._saved_excepthook)

    def test_unhandled_exception_is_logged_critical(self):
        records = self._capture_logs()
        crash_handler.install_crash_handlers(show_dialog=False)
        try:
            raise ValueError("boom")
        except ValueError:
            sys.excepthook(*sys.exc_info())
        self.assertTrue(any(r.levelno == logging.CRITICAL for r in records))
        self.assertTrue(any("Unhandled exception" in r.getMessage() for r in records))

    def test_keyboard_interrupt_delegates_to_original(self):
        called = []
        sys.excepthook = lambda *a: called.append(a)
        crash_handler.install_crash_handlers(show_dialog=False)
        try:
            raise KeyboardInterrupt()
        except KeyboardInterrupt:
            info = sys.exc_info()
            sys.excepthook(*info)
        # The original hook (captured at install time) should have been invoked.
        self.assertEqual(len(called), 1)
        self.assertIs(called[0][0], KeyboardInterrupt)


if __name__ == "__main__":
    unittest.main()
