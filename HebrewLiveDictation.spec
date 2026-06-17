# -*- mode: python ; coding: utf-8 -*-

import os

block_cipher = None

native_release = os.path.join("native", "tsf_hello_peer", "build", "Release", "VoiceTypeTsfHelloPeer.exe")
native_dll = os.path.join("native", "tsf_hello_peer", "build", "Release", "VoiceTypeTsfTextService.dll")
native_binaries = []
if os.path.exists(native_release):
    native_binaries.append((native_release, "native/tsf"))
if os.path.exists(native_dll):
    native_binaries.append((native_dll, "native/tsf"))

a = Analysis(
    ["main.py"],
    pathex=["src"],
    binaries=native_binaries,
    datas=[
        ("assets/app_icon.png", "assets"),
        ("assets/app_icon.ico", "assets"),
        ("native/tsf_hello_peer/README.md", "native/tsf_hello_peer"),
        ("native/tsf_hello_peer/build_local.ps1", "native/tsf_hello_peer"),
    ],
    hiddenimports=[
        "google.cloud.speech_v2",
        "google.cloud.speech_v2.types.cloud_speech",
        "google.protobuf.duration_pb2",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "comtypes",
        "comtypes.client",
        "uiautomation",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="HebrewLiveDictation",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/app_icon.ico",
    manifest="app.manifest",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="HebrewLiveDictation",
)
