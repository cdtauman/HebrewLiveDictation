import os
import sys


def configure_process_dpi_awareness():
    os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")
    if sys.platform != "win32":
        return
    try:
        import ctypes

        DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
        ctypes.windll.user32.SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass


def main():
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
    app_dir = os.path.dirname(os.path.abspath(__file__))
    src_dir = os.path.join(app_dir, "src")
    if os.path.isdir(src_dir) and src_dir not in sys.path:
        sys.path.insert(0, src_dir)

    appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
    config_dir = os.path.join(appdata, "VoiceType")
    
    if not os.path.exists(config_dir):
        os.makedirs(config_dir, exist_ok=True)
        
    try:
        from hebrew_live_dictation.qt_app import QtDictationApp
    except ModuleNotFoundError as e:
        if e.name == "PySide6":
            print("PySide6 is required for the modern app UI.")
            print("Install dependencies with: pip install -r requirements.txt")
            return 1
        raise

    app = QtDictationApp(app_dir, config_dir)
    return app.run()


if __name__ == "__main__":
    sys.exit(main())
