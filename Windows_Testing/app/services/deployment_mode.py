"""
Explicit deployment mode: git working tree vs immutable image-style layout.

Detection order:
  1) WEBABLE_DEPLOYMENT_MODE=git|image (override)
  2) .git directory exists at repo root → git
  3) otherwise → image
"""

from __future__ import annotations

import os
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Literal

DeploymentMode = Literal["git", "image"]


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


@lru_cache(maxsize=1)
def get_deployment_mode() -> DeploymentMode:
    override = (os.environ.get("WEBABLE_DEPLOYMENT_MODE") or "").strip().lower()
    if override in ("git", "image"):
        return override  # type: ignore[return-value]
    root = _repo_root()
    if (root / ".git").is_dir():
        return "git"
    return "image"


def clear_deployment_mode_cache() -> None:
    get_deployment_mode.cache_clear()


def git_cli_available() -> bool:
    try:
        r = subprocess.run(["git", "--version"], capture_output=True, text=True, timeout=5)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def has_git_repo() -> bool:
    return (_repo_root() / ".git").is_dir()


def auto_update_supported_git() -> bool:
    """Git-based unattended update (WEBABLE_AUTO_UPDATE) is technically possible."""
    if get_deployment_mode() != "git":
        return False
    if not has_git_repo():
        return False
    if not _env_truthy("WEBABLE_AUTO_UPDATE"):
        return False
    return git_cli_available()


def auto_update_enabled_git() -> bool:
    return get_deployment_mode() == "git" and _env_truthy("WEBABLE_AUTO_UPDATE")


def image_self_update_configured() -> bool:
    return _env_truthy("WEBABLE_ALLOW_IMAGE_SELF_UPDATE")


def watchtower_expected() -> bool:
    return _env_truthy("WEBABLE_EXPECT_EXTERNAL_UPDATER")


def get_update_action_mode() -> str:
    """
    internal_git | docker_compose | external_only
    """
    mode = get_deployment_mode()
    if mode == "git":
        if auto_update_supported_git():
            return "internal_git"
        return "external_only"
    # image
    from . import safe_compose

    ok, _ = safe_compose.validate_compose_file_path()
    if image_self_update_configured() and ok:
        return "docker_compose"
    return "external_only"


def update_action_supported() -> bool:
    return get_update_action_mode() in ("internal_git", "docker_compose")


def auto_update_supported_aggregate() -> bool:
    """
    Broad \"auto update is a meaningful concept\" for this deployment.
    Git: WEBABLE_AUTO_UPDATE + repo + git.
    Image: self-serve compose pull OR external updater expected.
    """
    mode = get_deployment_mode()
    if mode == "git":
        return auto_update_supported_git()
    from . import safe_compose

    ok, _ = safe_compose.validate_compose_file_path()
    if image_self_update_configured() and ok:
        return True
    return watchtower_expected()


def auto_update_enabled_aggregate() -> bool:
    """Enabled flags meaningful to the active mode (git auto-update OR image self-update)."""
    mode = get_deployment_mode()
    if mode == "git":
        return auto_update_enabled_git()
    from . import safe_compose

    ok, _ = safe_compose.validate_compose_file_path()
    return image_self_update_configured() and ok
