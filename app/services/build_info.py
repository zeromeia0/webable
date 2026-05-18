"""
Runtime build identity for `/api/build-info` and deployment-aware UI.

Reads semantic version from (in order):
  - WEBABLE_APP_VERSION environment variable
  - /app/VERSION inside Docker
  - VERSION file at repository root (local dev)

build_time: WEBABLE_BUILD_TIME env, else /app/.webable-build-time, else unknown
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _read_version() -> str:
    v = (os.environ.get("WEBABLE_APP_VERSION") or "").strip()
    if v:
        return v
    for candidate in (
        Path("/app/VERSION"),
        _repo_root() / "VERSION",
    ):
        try:
            if candidate.is_file():
                t = candidate.read_text(encoding="utf-8", errors="replace").strip()
                if t:
                    return t.splitlines()[0].strip()
        except OSError:
            continue
    return "0.0.0-dev"


def _read_commit() -> str:
    env_c = (os.environ.get("WEBABLE_LOCAL_GIT_COMMIT") or os.environ.get("WEBABLE_GIT_COMMIT") or "").strip()
    if env_c:
        return env_c[:40]
    for candidate in (Path("/app/.webable-git-rev"), _repo_root() / ".webable-git-rev"):
        try:
            if candidate.is_file():
                t = candidate.read_text(encoding="utf-8", errors="replace").strip()
                if t:
                    return t[:40]
        except OSError:
            continue
    return "unknown"


def _read_build_time() -> str:
    bt = (os.environ.get("WEBABLE_BUILD_TIME") or "").strip()
    if bt:
        return bt
    for candidate in (Path("/app/.webable-build-time"), _repo_root() / ".webable-build-time"):
        try:
            if candidate.is_file():
                t = candidate.read_text(encoding="utf-8", errors="replace").strip()
                if t:
                    return t.splitlines()[0].strip()
        except OSError:
            continue
    return "unknown"


@lru_cache(maxsize=1)
def get_static_identity() -> dict[str, Any]:
    version = _read_version()
    commit = _read_commit()
    channel = (os.environ.get("WEBABLE_CHANNEL") or "stable").strip() or "stable"
    build_id = f"{version}+{commit}"
    return {
        "version": version,
        "commit": commit,
        "build_id": build_id,
        "channel": channel,
        "build_time": _read_build_time(),
    }


def clear_build_identity_cache() -> None:
    get_static_identity.cache_clear()


def _deployment_capabilities() -> dict[str, Any]:
    from . import deployment_mode

    return {
        "deployment_mode": deployment_mode.get_deployment_mode(),
        "auto_update_supported": deployment_mode.auto_update_supported_aggregate(),
        "auto_update_enabled": deployment_mode.auto_update_enabled_aggregate(),
        "watchtower_expected": deployment_mode.watchtower_expected(),
        "update_action_supported": deployment_mode.update_action_supported(),
        "update_action_mode": deployment_mode.get_update_action_mode(),
    }


def live_capabilities_dict() -> dict[str, Any]:
    from . import update_orchestration

    out = _deployment_capabilities()
    out["update_in_progress"] = update_orchestration.update_in_progress()
    return out


def build_info_dict() -> dict[str, Any]:
    """Full public dict for GET /api/build-info."""
    return {**get_static_identity(), **live_capabilities_dict()}
