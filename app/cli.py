"""Webable CLI — safe backup and additive migrations (no destructive reset)."""

from __future__ import annotations

import argparse
import sys

from app.db import DATA_ROOT, engine
from app.services import db_safety


def cmd_backup(_args: argparse.Namespace) -> int:
    dest = db_safety.backup_data_directory()
    print(f"Backup created at: {dest}")
    return 0


def cmd_migrate(_args: argparse.Namespace) -> int:
    db_safety.run_safe_startup_migrations(engine)
    info = db_safety.verify_data_dir_preserved()
    print(f"Data root: {info['data_root']}")
    print(f"SQLite files found: {info['sqlite_files']}")
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    info = db_safety.verify_data_dir_preserved()
    print(f"Data root: {info['data_root']}")
    print(f"SQLite files: {info['sqlite_files']}")
    for p in info.get("paths") or []:
        print(f"  - {p}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Webable data safety tools (backup / additive migrate).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_backup = sub.add_parser("backup", help="Copy data/ to a timestamped backup folder")
    p_backup.set_defaults(func=cmd_backup)

    p_migrate = sub.add_parser(
        "migrate",
        help="Run additive schema migrations (preserves all existing rows)",
    )
    p_migrate.set_defaults(func=cmd_migrate)

    p_status = sub.add_parser("status", help="List data directory and SQLite files")
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
