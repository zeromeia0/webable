# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — Webable Windows desktop (onedir, windowed release build).
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None
ROOT = Path(os.path.abspath(SPECPATH))
version_file = ROOT / "assets" / "version_info.txt"

import sys

PYTHON_BASE = Path(sys.base_prefix)
TCL_DIR = PYTHON_BASE / "tcl" / "tcl8.6"
TK_DIR = PYTHON_BASE / "tcl" / "tk8.6"

datas = [
    (str(ROOT / "app" / "templates"), "app/templates"),
    (str(ROOT / "app" / "static"), "app/static"),
    (str(ROOT / "VERSION"), "."),
    (str(ROOT / "update.md"), "."),

    (str(TCL_DIR), "_tcl_data"),
    (str(TK_DIR), "_tk_data"),
]

# SQLAlchemy 2.x: do NOT use sqlalchemy.sql.defaultcomparator (removed).
hiddenimports = [
    "uvicorn",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "uvicorn.config",
    "uvicorn.server",
    "uvicorn.main",
    "h11",
    "httptools",
    "websockets",
    "anyio",
    "anyio._backends",
    "anyio._backends._asyncio",
    "sniffio",
    "fastapi",
    "starlette",
    "starlette.routing",
    "starlette.responses",
    "starlette.staticfiles",
    "starlette.templating",
    "sqlalchemy",
    "sqlalchemy.dialects",
    "sqlalchemy.dialects.sqlite",
    "sqlalchemy.orm",
    "sqlalchemy.engine",
    "sqlalchemy.pool",
    "sqlalchemy.sql",
    "sqlalchemy.ext",
    "multipart",
    "python_multipart",
    "dateutil",
    "dateutil.relativedelta",
    "reportlab",
    "reportlab.pdfgen",
    "reportlab.lib",
    "matplotlib",
    "matplotlib.backends.backend_agg",
    "pypdf",
    "markdown",
    "bleach",
    "tkinter",
    "jinja2",
    "jinja2.ext",
    "app",
    "app.main",
    "app.auth",
    "app.db",
    "app.models",
    "app.cli",
    "webapp",
    "windows",
    "windows.bootstrap",
    "windows.import_app",
]

hiddenimports += collect_submodules("app.services")

a = Analysis(
    [str(ROOT / "windows_launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[
        str(ROOT / "hook-freeze.py"),
        str(ROOT / "hook-mpl.py"),
    ],
    excludes=["pytest", "tests", "test"],
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
