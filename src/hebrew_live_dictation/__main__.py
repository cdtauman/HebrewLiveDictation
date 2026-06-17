
def configure_process_dpi_awareness() -> None:
    import os
    import sys

    os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass


def main() -> int:
    import os
    import sys

    if sys.platform == "win32":
        # Force single-threaded apartment (STA) for COM initialization
        sys.coinit_flags = 2  # COINIT_APARTMENTTHREADED
        try:
            import ctypes
            ctypes.windll.ole32.CoInitialize(None)
        except Exception:
            pass

    configure_process_dpi_awareness()
    app_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
    config_dir = os.path.join(appdata, "VoiceType")

    from .qt_app import QtDictationApp
    app = QtDictationApp(app_dir, config_dir)
    return app.run()


if __name__ == "__main__":
    raise SystemExit(main())

