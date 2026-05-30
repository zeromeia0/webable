"""Safe FastAPI app import with step logging (frozen + dev)."""

from __future__ import annotations

import logging
import os
import sys
import traceback
from pathlib import Path

from windows.bootstrap import bundle_root, is_frozen, verify_bundle_resources

log = logging.getLogger("webable.import")


def _log_paths() -> None:
    root = bundle_root()
    meipass = getattr(sys, "_MEIPASS", None)
    log.info("frozen=%s executable=%s", is_frozen(), getattr(sys, "executable", ""))
    log.info("bundle_root=%s", root)
    log.info("_MEIPASS=%s", meipass)
    log.info("cwd=%s", os.getcwd())
    log.info("WEBABLE_DATA_DIR=%s", os.environ.get("WEBABLE_DATA_DIR"))
    verify_bundle_resources(log)


def load_fastapi_app():
    """Import webapp.app with diagnostics; re-raise on failure."""
    _log_paths()
    try:
        log.info("import: webapp")
        from webapp import app  # noqa: WPS433

        log.info("import: webapp OK (routes=%s)", len(getattr(app, "routes", [])))
        return app
    except Exception:
        log.error("import: webapp FAILED\n%s", traceback.format_exc())
        raise


def import_smoke_test() -> None:
    """Import core modules individually to locate missing PyInstaller deps."""
    modules = [
        "uvicorn",
        "fastapi",
        "sqlalchemy",
        "sqlalchemy.dialects.sqlite",
        "jinja2",
        "multipart",
        "reportlab",
        "matplotlib",
        "pypdf",
        "bleach",
        "markdown",
        "app.db",
        "app.models",
        "app.auth",
        "app.main",
        "webapp",
    ]
    for name in modules:
        try:
            log.info("import smoke: %s", name)
            __import__(name)
            log.info("import smoke: %s OK", name)
        except Exception:
            log.error("import smoke: %s FAILED\n%s", name, traceback.format_exc())
            raise
