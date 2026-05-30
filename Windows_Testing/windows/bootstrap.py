"""
Windows desktop bootstrap — sets paths before the FastAPI app loads.
Only used by windows_launcher.py (not imported by the main web app in Docker).
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 17890

log = logging.getLogger("webable.bootstrap")


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_root() -> Path:
    """Directory containing bundled app/templates and app/static."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent.parent


def install_dir() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return bundle_root()


def default_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "Webable"


def configure_environment(*, port: int = DEFAULT_PORT) -> Path:
    """Apply env vars and working directory for Windows desktop runs."""
    data = Path(os.environ.get("WEBABLE_DATA_DIR", "") or default_data_dir())
    data.mkdir(parents=True, exist_ok=True)
    (data / "logs").mkdir(parents=True, exist_ok=True)

    os.environ["WEBABLE_DATA_DIR"] = str(data)
    os.environ.setdefault("WEBABLE_DEPLOYMENT_MODE", "image")
    os.environ.setdefault("WEBABLE_APP_VERSION", _read_version_file())
    os.environ.setdefault("APP_ENV", "production")
    os.environ.setdefault("WEBABLE_AI_ENABLED", "0")

    root = bundle_root()
    if is_frozen():
        os.chdir(root)
        log.info("chdir bundle_root=%s", root)

    return data


def verify_bundle_resources(logger: logging.Logger | None = None) -> dict[str, bool]:
    """Log presence of bundled templates/static/config (PyInstaller datas check)."""
    lg = logger or log
    root = bundle_root()
    checks = {
        "app/templates": (root / "app" / "templates").is_dir(),
        "app/static": (root / "app" / "static").is_dir(),
        "VERSION": (root / "VERSION").is_file(),
        "update.md": (root / "update.md").is_file(),
    }
    for label, ok in checks.items():
        lg.info("bundle resource %s: %s", label, "OK" if ok else "MISSING")
    sample_tpl = root / "app" / "templates" / "home.html"
    sample_js = root / "app" / "static" / "js" / "webable-currency.js"
    lg.info("sample template home.html: %s", "OK" if sample_tpl.is_file() else "MISSING")
    lg.info("sample static webable-currency.js: %s", "OK" if sample_js.is_file() else "MISSING")
    return checks


def _read_version_file() -> str:
    for candidate in (bundle_root() / "VERSION", install_dir() / "VERSION"):
        try:
            if candidate.is_file():
                line = candidate.read_text(encoding="utf-8", errors="replace").strip().splitlines()[0]
                if line:
                    return line
        except OSError:
            continue
    return "1.0.0"


def apply_frozen_import_patches() -> None:
    """Make build_info/deployment_mode resolve bundled resources when frozen."""
    if not is_frozen():
        return
    root = bundle_root()

    import app.services.build_info as build_info
    import app.services.deployment_mode as deployment_mode

    def _repo_root() -> Path:
        return root

    build_info._repo_root = _repo_root  # type: ignore[method-assign]
    deployment_mode._repo_root = _repo_root  # type: ignore[method-assign]
    try:
        build_info.build_info_dict.cache_clear()
    except AttributeError:
        pass
    deployment_mode.clear_deployment_mode_cache()


def app_url(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> str:
    return f"http://{host}:{port}/"
