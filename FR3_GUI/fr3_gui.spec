# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec. Run on each target OS separately - PyInstaller
does not cross-compile (see PACKAGING.md). Produces a one-directory build
on every platform (more antivirus/startup-time friendly than one-file, and
required for a proper macOS .app bundle):

    Windows -> dist/FR3 Board Control/FR3 Board Control.exe
    Linux   -> dist/FR3 Board Control/FR3 Board Control
    macOS   -> dist/FR3 Board Control.app

Add an icon later by dropping app.ico (Windows) / app.icns (macOS) next to
this file - both are picked up automatically if present."""

import sys
from pathlib import Path

APP_NAME = "FR3 Board Control"
project_root = Path(SPECPATH)

sys.path.insert(0, str(project_root))
from fr3_gui.version import __version__ as APP_VERSION  # noqa: E402

datas = [
    (str(project_root / "data" / "am3153_sparams"), "data/am3153_sparams"),
    (str(project_root / "data" / "lo_suppression.csv"), "data"),
    (str(project_root / "fr3_gui" / "resources" / "icon.png"), "fr3_gui/resources"),
]

icon_ico = project_root / "app.ico"
icon_icns = project_root / "app.icns"

a = Analysis(
    ["main.py"],
    pathex=[str(project_root)],
    datas=datas,
    hiddenimports=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(icon_ico) if sys.platform == "win32" and icon_ico.exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=str(icon_icns) if icon_icns.exists() else None,
        bundle_identifier="com.pi-radio.fr3-board-control",
        info_plist={
            "NSHighResolutionCapable": True,
            "CFBundleShortVersionString": APP_VERSION,
        },
    )
