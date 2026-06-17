"""Global crash/exception handlers.

Installs a ``sys.excepthook`` and a ``threading.excepthook`` so unhandled
exceptions are written to the redacted application log (via the existing
``PrivacyFormatter``) instead of silently killing the process. A non-leaking
error dialog is shown when a Qt application is running.

Privacy: the dialog text is passed through ``redact_sensitive`` so credential
paths never surface in the UI.
"""

import logging
import sys
import threading


logger = logging.getLogger("CrashHandler")

_original_excepthook = None
_original_threading_excepthook = None


def _redact(text: str) -> str:
    try:
        from .app_logging import redact_sensitive

        return redact_sensitive(text)
    except Exception:  # pragma: no cover - redaction must never crash the handler
        return "<error details suppressed>"


def _show_dialog(message: str) -> None:
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        if QApplication.instance() is None:
            return
        QMessageBox.critical(
            None,
            "Hebrew Live Dictation",
            "An unexpected error occurred. Details were written to the log file.\n\n"
            + message,
        )
    except Exception:  # pragma: no cover - never let the dialog crash the handler
        pass


def install_crash_handlers(show_dialog: bool = True) -> None:
    global _original_excepthook, _original_threading_excepthook
    _original_excepthook = sys.excepthook
    _original_threading_excepthook = getattr(threading, "excepthook", None)

    def handle(exc_type, exc_value, exc_tb):
        # Let Ctrl+C behave normally.
        if issubclass(exc_type, KeyboardInterrupt):
            if _original_excepthook:
                _original_excepthook(exc_type, exc_value, exc_tb)
            return
        logger.critical("Unhandled exception", exc_info=(exc_type, exc_value, exc_tb))
        if show_dialog:
            _show_dialog(_redact(f"{exc_type.__name__}: {exc_value}"))

    sys.excepthook = handle

    def thread_handle(args):
        if issubclass(args.exc_type, SystemExit):
            return
        logger.critical(
            "Unhandled exception in thread %s",
            getattr(args.thread, "name", "?"),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    try:
        threading.excepthook = thread_handle
    except Exception:  # pragma: no cover - older runtimes
        pass
