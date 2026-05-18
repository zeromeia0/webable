"""
Safe database maintenance for Webable.

- Never deletes or overwrites existing user SQLite files.
- App schema changes use ALTER TABLE only (no DROP / recreate).
- Workspace finance DBs use additive column migrations in instance_service.
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from typing import TYPE_CHECKING

from app.db import DATA_ROOT

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine
from app.services import instance_service

log = logging.getLogger(__name__)

DESTRUCTIVE_WARNING = (
    "WARNING: This will permanently delete user data. "
    "Back up the data/ folder first (see README: Updating the App Without Losing Data)."
)


def data_root() -> Path:
    return DATA_ROOT


def list_user_sqlite_files(root: Path | None = None) -> list[Path]:
    """All workspace finance/logic DB files and the main app DB."""
    root = (root or DATA_ROOT).resolve()
    found: list[Path] = []
    app_db = root / "webable_app.db"
    if app_db.is_file():
        found.append(app_db)
    for pattern in ("**/*_financas.db", "**/*_logic.db"):
        found.extend(sorted(root.glob(pattern)))
    return found


def next_backup_destination(parent: Path, date_str: str | None = None) -> Path:
    """
    Next backup folder: webable-data-backup-YYYYMMDD-### (### zero-padded, sequential per day).
    """
    parent = parent.resolve()
    day = date_str or datetime.utcnow().strftime("%Y%m%d")
    prefix = f"webable-data-backup-{day}-"
    max_seq = 0
    for entry in parent.iterdir():
        if not entry.is_dir() or not entry.name.startswith(prefix):
            continue
        suffix = entry.name[len(prefix) :]
        if len(suffix) == 3 and suffix.isdigit():
            max_seq = max(max_seq, int(suffix))
    return parent / f"{prefix}{max_seq + 1:03d}"


def backup_data_directory(
    root: Path | None = None,
    dest: Path | None = None,
) -> Path:
    """
    Copy the entire data directory to a dated sequential backup folder.
    Idempotent: creates a new folder each call; never modifies the source.
    """
    root = (root or DATA_ROOT).resolve()
    if not root.is_dir():
        root.mkdir(parents=True, exist_ok=True)
    if dest is None:
        dest = next_backup_destination(root.parent)
    dest = dest.resolve()
    if dest == root or str(root).startswith(str(dest) + os.sep):
        raise ValueError("Backup destination must not be inside the live data directory.")
    if dest.exists():
        raise FileExistsError(f"Backup path already exists: {dest}")
    shutil.copytree(root, dest, symlinks=False)
    log.info("Backed up %s -> %s", root, dest)
    return dest


def migrate_app_schema(engine: "Engine") -> None:
    """Additive migrations for webable_app.db — ALTER TABLE only, never DROP."""
    from sqlalchemy import text

    with engine.begin() as conn:
        user_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(users)")).fetchall()}
        if "enable_iefp_mode" not in user_cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN enable_iefp_mode BOOLEAN NOT NULL DEFAULT 0"))

        existing = {row[1] for row in conn.execute(text("PRAGMA table_info(database_instances)")).fetchall()}
        if "health_status" not in existing:
            conn.execute(text("ALTER TABLE database_instances ADD COLUMN health_status TEXT NOT NULL DEFAULT 'healthy'"))
        if "last_sync_status" not in existing:
            conn.execute(
                text(
                    "ALTER TABLE database_instances ADD COLUMN last_sync_status TEXT NOT NULL DEFAULT 'Waiting for execution'"
                )
            )
        if "last_activity_at" not in existing:
            conn.execute(text("ALTER TABLE database_instances ADD COLUMN last_activity_at DATETIME"))

        job_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(job_runs)")).fetchall()}
        if "friendly_message" not in job_cols:
            conn.execute(text("ALTER TABLE job_runs ADD COLUMN friendly_message TEXT NOT NULL DEFAULT ''"))
        if "technical_logs" not in job_cols:
            conn.execute(text("ALTER TABLE job_runs ADD COLUMN technical_logs TEXT NOT NULL DEFAULT ''"))
        if "metrics_json" not in job_cols:
            conn.execute(text("ALTER TABLE job_runs ADD COLUMN metrics_json TEXT NOT NULL DEFAULT '{}'"))
        if "duration_ms" not in job_cols:
            conn.execute(text("ALTER TABLE job_runs ADD COLUMN duration_ms INTEGER"))


def migrate_workspace_sqlite(path: str | Path) -> None:
    """Apply additive migrations to a single workspace finance or logic file."""
    p = Path(path)
    if not p.is_file():
        return
    name = p.name.lower()
    conn = sqlite3.connect(str(p))
    try:
        if name.endswith("_financas.db"):
            instance_service._ensure_oneoff_schema(conn)
            instance_service._ensure_recurring_recurrence(conn)
        # logic DB: schema created at init; no destructive changes yet
        conn.commit()
    finally:
        conn.close()


def migrate_all_workspace_files(root: Path | None = None) -> int:
    """Migrate every workspace SQLite file under data/. Returns count migrated."""
    root = (root or DATA_ROOT).resolve()
    n = 0
    for p in list_user_sqlite_files(root):
        if p.name == "webable_app.db":
            continue
        migrate_workspace_sqlite(p)
        n += 1
    return n


def run_safe_startup_migrations(engine: "Engine") -> None:
    """Called on app startup: additive app schema + all workspace files."""
    migrate_app_schema(engine)
    count = migrate_all_workspace_files()
    log.info("Workspace SQLite additive migrations applied to %s file(s).", count)


def verify_data_dir_preserved(root: Path | None = None) -> dict:
    """Return summary of data files (for health/diagnostics)."""
    root = (root or DATA_ROOT).resolve()
    files = list_user_sqlite_files(root)
    return {
        "data_root": str(root),
        "sqlite_files": len(files),
        "paths": [str(p.relative_to(root)) if p.is_relative_to(root) else str(p) for p in files[:50]],
    }
