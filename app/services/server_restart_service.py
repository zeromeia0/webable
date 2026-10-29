"""
"Restart server" button: rebuild and restart the Docker deployment from the UI.

The app container cannot (and should not) drive Docker itself, so this works through files in the
shared data directory:

- the app writes ``.restart-request`` when someone clicks the button;
- ``scripts/webable-restart-watcher.sh`` runs on the host (systemd, see
  ``make install-restart-helper``), picks the request up, runs ``docker compose up -d --build`` and
  reports progress in ``.restart-status.json``;
- the watcher touches ``.restart-watcher-heartbeat`` so the UI can tell whether it is installed.

The request file is only a flag: the watcher never executes anything from it.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from app.db import DATA_ROOT

REQUEST_FILE = ".restart-request"
STATUS_FILE = ".restart-status.json"
HEARTBEAT_FILE = ".restart-watcher-heartbeat"
HEARTBEAT_MAX_AGE_S = 45
REQUEST_STALE_S = 15 * 60

# Changes every time the server process starts, so the page can tell the restart finished.
BOOT_ID = uuid4().hex
BOOTED_AT = datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _root(root: Path | None) -> Path:
    return (root or DATA_ROOT).resolve()


def _age_s(path: Path) -> float | None:
    try:
        return max(0.0, time.time() - path.stat().st_mtime)
    except OSError:
        return None


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_status(r: Path, state: str, message: str) -> None:
    tmp = r / (STATUS_FILE + ".tmp")
    tmp.write_text(
        json.dumps({"state": state, "message": message, "updated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z"}),
        encoding="utf-8",
    )
    os.replace(tmp, r / STATUS_FILE)


def watcher_online(root: Path | None = None) -> bool:
    age = _age_s(_root(root) / HEARTBEAT_FILE)
    return age is not None and age <= HEARTBEAT_MAX_AGE_S


def request_pending(root: Path | None = None) -> bool:
    age = _age_s(_root(root) / REQUEST_FILE)
    return age is not None and age <= REQUEST_STALE_S


def request_restart(username: str, root: Path | None = None) -> dict:
    """Queue a rebuild. Returns the public status; ``queued`` is False if one was already pending."""
    r = _root(root)
    queued = False
    if not request_pending(r):
        payload = {"requested_at": datetime.utcnow().isoformat(timespec="seconds") + "Z", "by": username[:120]}
        tmp = r / (REQUEST_FILE + ".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, r / REQUEST_FILE)
        _write_status(r, "queued", f"Requested by {payload['by']}")
        queued = True
    return {**status(r), "queued": queued}


def status(root: Path | None = None) -> dict:
    r = _root(root)
    st = _read_json(r / STATUS_FILE)
    return {
        "boot_id": BOOT_ID,
        "booted_at": BOOTED_AT,
        "watcher_online": watcher_online(r),
        "pending": request_pending(r),
        "state": st.get("state") or "idle",
        "message": str(st.get("message") or "")[:500],
        "updated_at": st.get("updated_at"),
        "log_tail": str(st.get("log_tail") or "")[-2000:],
    }
