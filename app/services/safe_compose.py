"""
Tightly scoped docker compose invocation for image self-updates.

- No shell=True
- Compose file path must resolve under allowed roots
- Filename allowlist only
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .deployment_mode import _repo_root

COMPOSE_FILENAME_ALLOWLIST = frozenset(
    {
        "docker-compose.yml",
        "docker-compose.yaml",
        "compose.yml",
        "compose.yaml",
    }
)


def _allowed_roots() -> list[Path]:
    roots: list[Path] = [_repo_root().resolve()]
    extra = (os.environ.get("WEBABLE_DOCKER_COMPOSE_ALLOWED_ROOTS") or "").strip()
    if extra:
        for part in extra.split(os.pathsep):
            p = Path(part.strip()).expanduser()
            if str(p):
                try:
                    roots.append(p.resolve())
                except OSError:
                    continue
    app_root = Path("/app")
    try:
        if app_root.is_dir():
            roots.append(app_root.resolve())
    except OSError:
        pass
    # de-dupe preserving order
    seen: set[str] = set()
    out: list[Path] = []
    for r in roots:
        key = str(r)
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def validate_compose_file_path() -> tuple[bool, str]:
    raw = (os.environ.get("WEBABLE_DOCKER_COMPOSE_PATH") or "").strip()
    if not raw:
        return False, "WEBABLE_DOCKER_COMPOSE_PATH is not set."
    try:
        path = Path(raw).expanduser().resolve(strict=False)
    except OSError as exc:
        return False, f"Invalid compose path: {exc}"
    if path.name not in COMPOSE_FILENAME_ALLOWLIST:
        return False, "Compose file must be named docker-compose.yml, compose.yml, or similar allowlisted name."
    if ".." in raw.replace("\\", "/"):
        return False, "Path must not contain '..'."

    allowed = _allowed_roots()
    ok_root = False
    for base in allowed:
        try:
            base_r = base.resolve()
            path.relative_to(base_r)
            ok_root = True
            break
        except ValueError:
            continue
    if not ok_root:
        return False, "Compose file path is outside allowed roots (repo, /app, or WEBABLE_DOCKER_COMPOSE_ALLOWED_ROOTS)."

    if not path.is_file():
        return False, "Compose file does not exist or is not a file."

    return True, ""


def docker_available() -> bool:
    return shutil.which("docker") is not None


def compose_service_name() -> str:
    return (os.environ.get("WEBABLE_COMPOSE_SERVICE") or "webable").strip() or "webable"


def run_compose_pull(compose_file: Path, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    args = ["docker", "compose", "-f", str(compose_file), "pull", compose_service_name()]
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)


def run_compose_up_detached(compose_file: Path, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    args = ["docker", "compose", "-f", str(compose_file), "up", "-d", compose_service_name()]
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)


def run_compose_restart(compose_file: Path, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    args = ["docker", "compose", "-f", str(compose_file), "restart", compose_service_name()]
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
