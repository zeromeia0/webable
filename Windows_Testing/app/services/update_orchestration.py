"""
Update job orchestration: locking, progress phases, git vs compose paths.

HTTP handlers return quickly; work runs in a background thread.
Terminal phases (completed/failed) persist until a new update is started.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from . import build_info, deployment_mode, safe_compose, safe_updater, update_service

log = logging.getLogger("webable.orchestration")

Phase = Literal[
    "idle",
    "checking",
    "pulling",
    "rebuilding",
    "restarting",
    "waiting_for_health",
    "reconnecting",
    "completed",
    "failed",
]

_LOCK = threading.RLock()
_STATE: dict[str, Any] = {
    "phase": "idle",
    "message": "",
    "error": None,
    "started_at": None,
    "finished_at": None,
    "run_id": None,
    "restart_required": False,
    "build_id_before": None,
    "build_id_after": None,
}

_LAST_START_MONO: float = 0.0
_MIN_INTERVAL_SEC = float(os.environ.get("WEBABLE_UPDATE_MIN_INTERVAL_SEC", "60"))
_TERMINAL_TTL_SEC = float(os.environ.get("WEBABLE_ORCHESTRATION_TERMINAL_TTL_SEC", "300"))
_HEALTH_URL = (os.environ.get("WEBABLE_INTERNAL_HEALTH_URL") or "http://127.0.0.1:8000/health").strip()
_HEALTH_TIMEOUT = float(os.environ.get("WEBABLE_UPDATE_HEALTH_TIMEOUT_SEC", "120"))


def _maybe_expire_terminal_state() -> None:
    """Clear completed/failed jobs from memory after TTL so the UI stops reopening the modal."""
    with _LOCK:
        if _STATE["phase"] not in ("completed", "failed"):
            return
        fin = _STATE.get("finished_at")
        if not fin:
            return
        if time.time() - float(fin) > _TERMINAL_TTL_SEC:
            _STATE["phase"] = "idle"
            _STATE["message"] = ""
            _STATE["error"] = None
            _STATE["run_id"] = None
            _STATE["started_at"] = None
            _STATE["finished_at"] = None
            _STATE["restart_required"] = False
            _STATE["build_id_before"] = None
            _STATE["build_id_after"] = None


def _now_mono() -> float:
    return time.monotonic()


def orchestration_public_dict() -> dict[str, Any]:
    _maybe_expire_terminal_state()
    with _LOCK:
        return {
            "phase": _STATE["phase"],
            "message": _STATE["message"],
            "error": _STATE["error"],
            "started_at": _STATE["started_at"],
            "finished_at": _STATE["finished_at"],
            "run_id": _STATE["run_id"],
            "restart_required": _STATE["restart_required"],
            "build_id_before": _STATE["build_id_before"],
            "build_id_after": _STATE["build_id_after"],
        }


def update_in_progress() -> bool:
    _maybe_expire_terminal_state()
    with _LOCK:
        return _STATE["phase"] in (
            "checking",
            "pulling",
            "rebuilding",
            "restarting",
            "waiting_for_health",
            "reconnecting",
        )


def _set_phase(phase: Phase, message: str = "", *, error: str | None = None) -> None:
    with _LOCK:
        _STATE["phase"] = phase
        _STATE["message"] = message
        if error is not None:
            _STATE["error"] = error


def _health_probe_once() -> bool:
    try:
        req = urllib.request.Request(_HEALTH_URL, method="GET", headers={"User-Agent": "Webable-UpdateOrchestrator/1"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            return 200 <= int(getattr(resp, "status", resp.getcode())) < 500
    except (urllib.error.URLError, OSError, TimeoutError, ValueError):
        return False


def _wait_for_health() -> None:
    _set_phase("waiting_for_health", "Waiting for the app to respond on /health …")
    deadline = _now_mono() + _HEALTH_TIMEOUT
    while _now_mono() < deadline:
        if _health_probe_once():
            return
        time.sleep(1.5)
    raise RuntimeError("Health check did not succeed within the configured timeout.")


def _maybe_compose_restart_after_git(compose_path: Path) -> bool:
    if os.environ.get("WEBABLE_GIT_UPDATE_USE_COMPOSE_RESTART", "").strip().lower() not in ("1", "true", "yes"):
        return False
    ok, _ = safe_compose.validate_compose_file_path()
    if not ok:
        return False
    _set_phase("restarting", "Restarting service via docker compose …")
    r = safe_compose.run_compose_restart(compose_path)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "docker compose restart failed")[:2000])
    return True


def _run_git_job(run_id: str) -> None:
    compose_ok, _ = safe_compose.validate_compose_file_path()
    compose_path: Path | None = None
    if compose_ok:
        raw = (os.environ.get("WEBABLE_DOCKER_COMPOSE_PATH") or "").strip()
        compose_path = Path(raw).expanduser().resolve()

    try:
        with _LOCK:
            if _STATE["run_id"] != run_id:
                return
        _set_phase("checking", "Checking for updates …")
        update_service.invalidate_update_cache()
        st = update_service.check_for_update(force_refresh=True)
        if not st.update_available:
            _set_phase("completed", "Already up to date.")
            build_info.clear_build_identity_cache()
            with _LOCK:
                _STATE["build_id_after"] = build_info.get_static_identity()["build_id"]
                _STATE["finished_at"] = time.time()
            return

        _set_phase("pulling", "Downloading changes with git …")
        with _LOCK:
            _STATE["build_id_before"] = build_info.get_static_identity()["build_id"]

        res = safe_updater.apply_git_pull_main()
        if not res.success:
            raise RuntimeError(res.message or "git update failed")

        update_service.invalidate_update_cache()
        build_info.clear_build_identity_cache()

        restarted = False
        if compose_path and compose_ok:
            try:
                restarted = _maybe_compose_restart_after_git(compose_path)
            except Exception as exc:
                log.warning("compose restart after git: %s", exc)

        if restarted:
            _wait_for_health()
            _set_phase("completed", "Update completed successfully.")
            with _LOCK:
                _STATE["restart_required"] = False
        else:
            _set_phase(
                "completed",
                "Git update finished. Reload the page. If nothing changed, restart the app process or set "
                "WEBABLE_GIT_UPDATE_USE_COMPOSE_RESTART=1 with WEBABLE_DOCKER_COMPOSE_PATH.",
            )
            with _LOCK:
                _STATE["restart_required"] = True

        build_info.clear_build_identity_cache()
        with _LOCK:
            _STATE["build_id_after"] = build_info.get_static_identity()["build_id"]
            _STATE["finished_at"] = time.time()
    except Exception as exc:
        log.exception("git update job failed")
        _set_phase("failed", "", error=str(exc))
        with _LOCK:
            _STATE["finished_at"] = time.time()


def _run_image_job(run_id: str) -> None:
    try:
        with _LOCK:
            if _STATE["run_id"] != run_id:
                return
        ok, msg = safe_compose.validate_compose_file_path()
        if not ok:
            raise RuntimeError(msg)
        if not safe_compose.docker_available():
            raise RuntimeError("docker CLI not found in PATH.")

        raw = (os.environ.get("WEBABLE_DOCKER_COMPOSE_PATH") or "").strip()
        compose_path = Path(raw).expanduser().resolve()

        _set_phase("checking", "Preparing image update …")
        with _LOCK:
            _STATE["build_id_before"] = build_info.get_static_identity()["build_id"]

        _set_phase("pulling", "Pulling container image …")
        pr = safe_compose.run_compose_pull(compose_path)
        if pr.returncode != 0:
            raise RuntimeError((pr.stderr or pr.stdout or "docker compose pull failed")[:2000])

        _set_phase("restarting", "Recreating containers (docker compose up -d) …")
        up = safe_compose.run_compose_up_detached(compose_path)
        if up.returncode != 0:
            raise RuntimeError((up.stderr or up.stdout or "docker compose up failed")[:2000])

        _set_phase(
            "completed",
            "Compose rollout started. This connection may drop — reload the app when it is healthy again.",
        )
        build_info.clear_build_identity_cache()
        with _LOCK:
            _STATE["restart_required"] = True
            _STATE["finished_at"] = time.time()
    except Exception as exc:
        log.exception("image update job failed")
        _set_phase("failed", "", error=str(exc))
        with _LOCK:
            _STATE["finished_at"] = time.time()


def try_start_update(*, user_present: bool) -> tuple[bool, str, str | None]:
    """Returns (accepted, message, run_id)."""
    global _LAST_START_MONO
    if not user_present:
        return False, "Authentication required.", None

    if not deployment_mode.update_action_supported():
        return False, "One-click update is not available for this deployment.", None

    now = _now_mono()
    with _LOCK:
        if _STATE["phase"] not in ("idle", "completed", "failed"):
            return False, "Another update is already running.", None
        if now - _LAST_START_MONO < _MIN_INTERVAL_SEC:
            return False, "Please wait before starting another update.", None
        _LAST_START_MONO = now
        run_id = f"u-{int(time.time())}"
        _STATE["run_id"] = run_id
        _STATE["started_at"] = time.time()
        _STATE["finished_at"] = None
        _STATE["error"] = None
        _STATE["restart_required"] = False
        _STATE["build_id_before"] = None
        _STATE["build_id_after"] = None
        _STATE["phase"] = "checking"
        _STATE["message"] = "Starting update …"
        mode = deployment_mode.get_deployment_mode()

    def _runner() -> None:
        if mode == "git":
            _run_git_job(run_id)
        else:
            _run_image_job(run_id)

    threading.Thread(target=_runner, name="webable-update-orchestrator", daemon=True).start()
    return True, "Update started.", run_id


@dataclass
class StartResult:
    accepted: bool
    message: str
    run_id: str | None = None


def start_update_thread(*, user_present: bool) -> StartResult:
    ok, msg, rid = try_start_update(user_present=user_present)
    return StartResult(ok, msg, rid)
