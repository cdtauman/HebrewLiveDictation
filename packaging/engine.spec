# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the headless VoiceType engine sidecar (engine.exe).

Onedir build: dist/engine/engine.exe + dist/engine/_internal/...  The WinUI shell spawns
this exe directly (RepoPaths packaged path) with --pipe <name>; on a dev tree with no
packaged engine present, the shell falls back to `python -m hebrew_live_dictation.bridge`.

console=True so the child's stdout/stderr pipe correctly to the shell's log drain; the shell
spawns it with CreateNoWindow=true, so no console window ever appears.
"""

import os

from PyInstaller.utils.hooks import collect_all

# Paths are anchored to the spec file (SPECPATH = the packaging/ dir) so the build works
# regardless of the current working directory. See build_engine.ps1.
ENTRY = os.path.join(SPECPATH, "engine_main.py")
REPO = os.path.dirname(SPECPATH)          # packaging/ -> repo root
SRC = os.path.join(REPO, "src")

datas = []
binaries = []

# The STT providers are imported lazily via the registry, so PyInstaller can't see them by
# static analysis — name them explicitly so a packaged engine can actually run every provider.
hiddenimports = [
    "hebrew_live_dictation.bridge.sidecar",
    "hebrew_live_dictation.stt.registry",
    "hebrew_live_dictation.stt.whisper_local",
    "hebrew_live_dictation.stt.deepgram",
    "hebrew_live_dictation.stt.groq",
    "hebrew_live_dictation.stt.fallback",
    "hebrew_live_dictation.stt.auto_select",
    "hebrew_live_dictation.google_stt_v2_stream",
    # Cloud + platform deps (mirrors the legacy app spec):
    "google.cloud.speech_v2",
    "google.cloud.speech_v2.types.cloud_speech",
    "google.protobuf.duration_pb2",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    # Dynamic text-insertion backends (editing_backend imports these LAZILY, so static analysis
    # misses them): Word COM via comtypes.client, and the UIA path via uiautomation. Without these
    # a packaged engine starts fine but cannot inject into Word / UIA targets. Mirrors the legacy spec.
    "comtypes",
    "comtypes.client",
    "uiautomation",
    "keyring.backends.Windows",
    "keyring.backends.chainer",
    "cryptography.hazmat.primitives.asymmetric.ed25519",
    "requests",
    "websockets",
    "websockets.sync.client",
    "psutil",
]

# REQUIRED deps — collect FAIL-FAST. If any of these can't be collected, the resulting engine.exe
# could not actually run dictation; failing the build here is far better than shipping a silently
# broken freeze (the previous blanket try/except hid exactly that). 'sounddevice' is included
# explicitly so the PortAudio runtime DLL (_sounddevice_data/portaudio-binaries/libportaudio64bit.dll)
# is collected deterministically rather than relying on PyInstaller's bundled hook — without it the
# package launches and self-tests but CANNOT capture microphone audio.
# 'docx' (python-docx) is imported lazily by export.py for DOCX history export and ships a default
# template (docx/templates/default.docx) that PyInstaller must collect — without it, packaged DOCX
# export raises at runtime (the packaged self-test now proves this works).
for _pkg in ("faster_whisper", "ctranslate2", "tokenizers", "huggingface_hub", "sounddevice", "docx"):
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h

# OPTIONAL/transitive deps — best-effort. faster-whisper runs without these in our usage (we feed
# numpy PCM and use our own segmenter, not faster-whisper's onnx VAD or PyAV decode), so a missing
# one must not break the build.
for _pkg in ("av", "onnxruntime"):
    try:
        _d, _b, _h = collect_all(_pkg)
        datas += _d
        binaries += _b
        hiddenimports += _h
    except Exception:
        pass

a = Analysis(
    [ENTRY],
    pathex=[SRC],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Headless engine: keep the obvious heavy GUI-only bits out where safe.
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "tkinter",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="engine",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="engine",
)
