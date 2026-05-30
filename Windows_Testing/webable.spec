# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Webable Windows desktop (onedir — recommended over onefile).
import os
from pathlib import Path

block_cipher = None
ROOT = Path(os.path.abspath(SPECPATH))
version_file = ROOT / "assets" / "version_info.txt"

datas = [
    (str(ROOT / "app" / "templates"), "app/templates"),
    (str(ROOT / "app" / "static"), "app/static"),
    (str(ROOT / "VERSION"), "."),
    (str(ROOT / "update.md"), "."),
]

hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "sqlalchemy.dialects.sqlite",
    "sqlalchemy.sql.defaultcomparator",
    "multipart",
    "dateutil",
    "reportlab",
    "reportlab.pdfgen",
    "matplotlib.backends.backend_agg",
    "pypdf",
    "markdown",
    "bleach",
    "tkinter",
    "app.main",
    "app.auth",
    "app.db",
    "app.models",
    "app.cli",
    "webapp",
]

a = Analysis(
    [str(ROOT / "windows_launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(ROOT / "hook-mpl.py")],
    excludes=["pytest", "test", "tests"],
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
    name="Webable",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "webable.ico") if (ROOT / "assets" / "webable.ico").is_file() else None,
    version=str(version_file) if version_file.is_file() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Webable",
)
