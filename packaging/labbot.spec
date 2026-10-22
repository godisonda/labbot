# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller-сборка LabBot.

macOS:  make app   → dist/LabBot.app
Windows: make exe  → dist/LabBot/LabBot.exe
"""
import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
WEB = ROOT / "orchestrator" / "labbot" / "web"

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[(str(WEB), "web")],
    hiddenimports=[
        "orchestrator.labbot.cli",
        "orchestrator.labbot.gui",
        "docx",
        "docx2txt",
        "pypdf",
        "openai",
        "pydantic",
        "pydantic_core",
        "matplotlib.backends.backend_agg",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "PyQt5", "PyQt6", "PySide6", "IPython", "notebook", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LabBot",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=sys.platform != "darwin",
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="LabBot",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="LabBot.app",
        icon=None,
        bundle_identifier="ru.mtuci.labbot",
        info_plist={
            "CFBundleName": "LabBot",
            "CFBundleDisplayName": "LabBot",
            "CFBundleShortVersionString": "1.0.0",
            "NSHighResolutionCapable": True,
        },
    )
