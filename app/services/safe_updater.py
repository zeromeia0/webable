"""
Safe in-place git update for development / self-hosted deployments.

NEVER deletes or overwrites:
  - WEBABLE_DATA_DIR (default ./data) — SQLite, uploads, caches
  - .env or other local config

ONLY runs git commands inside the repository root when WEBABLE_AUTO_UPDATE is enabled.
Docker images without .git cannot pull; use image rebuild instead (see README).
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("webable.updater")


@dataclass
class ApplyResult:
    success: bool
    message: str
    stdout: str = ""
    stderr: str = ""
    old_sha: str | None = None
    new_sha: str | None = None


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _data_root() -> Path:
    return Path(os.environ.get("WEBABLE_DATA_DIR", "data")).expanduser().resolve()


def _run_git(args: list[str], cwd: Path, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    log.info("git %s (cwd=%s)", " ".join(args), cwd)
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def preflight_git_update() -> tuple[bool, str]:
    """
    Validate that an automated git update is allowed and safe to attempt.
    Returns (ok, reason_if_not_ok).
    """
    from . import deployment_mode

    if deployment_mode.get_deployment_mode() != "git":
        return False, "This instance runs in image deployment mode; git pull is disabled."

    if os.environ.get("WEBABLE_AUTO_UPDATE", "").strip().lower() not in ("1", "true", "yes"):
        return False, "WEBABLE_AUTO_UPDATE is not enabled."

    root = _repo_root()
    if not (root / ".git").is_dir():
        return False, "No .git directory — use Docker image rebuild or deploy new files manually."

    data = _data_root()
    try:
        root_res = root.resolve()
        data_res = data.resolve()
        # Refuse if data lives inside the repo tree and we might touch tracked files — extra guard.
        if str(data_res).startswith(str(root_res) + os.sep) and (root_res / "data").exists():
            log.debug("Data directory is under repo root (normal); git pull will not remove ignored data/.")
    except OSError as exc:
        return False, f"Could not resolve paths: {exc}"

    return True, ""


def apply_git_pull_main(remote: str = "origin", branch: str = "main") -> ApplyResult:
    """
    Fast-forward pull only — no hard reset, no clean, no forced branch overwrite.

    Steps:
      1) git fetch
      2) git rev-parse HEAD (old_sha)
      3) git pull --ff-only remote branch
      4) git rev-parse HEAD (new_sha)
    """
    ok, reason = preflight_git_update()
    if not ok:
        return ApplyResult(False, reason)

    root = _repo_root()
    old = _run_git(["rev-parse", "HEAD"], root, timeout=30)
    if old.returncode != 0:
        return ApplyResult(False, "Could not read current commit.", old.stdout, old.stderr)

    old_sha = old.stdout.strip()
    fetch = _run_git(["fetch", remote], root, timeout=240)
    if fetch.returncode != 0:
        return ApplyResult(
            False,
            "git fetch failed; no files were changed.",
            fetch.stdout,
            fetch.stderr,
            old_sha=old_sha,
        )

    pull = _run_git(["pull", "--ff-only", remote, branch], root, timeout=240)
    if pull.returncode != 0:
        return ApplyResult(
            False,
            "git pull --ff-only failed; repository left unchanged. Resolve conflicts manually if needed.",
            pull.stdout,
            pull.stderr,
            old_sha=old_sha,
        )

    new = _run_git(["rev-parse", "HEAD"], root, timeout=30)
    new_sha = new.stdout.strip() if new.returncode == 0 else None

    msg = "Update applied successfully."
    if new_sha == old_sha:
        msg = "Already up to date (fast-forward had nothing to merge)."

    log.info("apply_git_pull_main: %s -> %s", old_sha, new_sha)
    return ApplyResult(True, msg, pull.stdout, pull.stderr, old_sha=old_sha, new_sha=new_sha)


def rollback_last_git_state() -> ApplyResult:
    """
    Optional emergency rollback: `git reset --hard ORIG_HEAD` after a pull.
    Guarded by WEBABLE_ALLOW_GIT_ROLLBACK=1 — dangerous if user had local commits.
    """
    if os.environ.get("WEBABLE_ALLOW_GIT_ROLLBACK", "").strip().lower() not in ("1", "true", "yes"):
        return ApplyResult(False, "Rollback disabled. Set WEBABLE_ALLOW_GIT_ROLLBACK=1 to enable.")

    root = _repo_root()
    if not (root / ".git").is_dir():
        return ApplyResult(False, "No git repository.")

    r = _run_git(["reset", "--hard", "ORIG_HEAD"], root, timeout=120)
    if r.returncode != 0:
        return ApplyResult(False, "git reset --hard ORIG_HEAD failed.", r.stdout, r.stderr)
    return ApplyResult(True, "Rolled back to ORIG_HEAD.", r.stdout, r.stderr)
