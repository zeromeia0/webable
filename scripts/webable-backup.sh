#!/usr/bin/env bash
# Back up Webable user data (SQLite, uploads, caches) before updating.
# Safe to run multiple times — each run creates a new timestamped folder.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="${WEBABLE_DATA_DIR:-$ROOT/data}"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
DEST="${WEBABLE_BACKUP_DIR:-$ROOT}/webable-data-backup-${STAMP}"

if [[ ! -d "$DATA_DIR" ]]; then
  echo "No data directory at: $DATA_DIR (nothing to back up yet)."
  exit 0
fi

echo "Backing up:"
echo "  From: $DATA_DIR"
echo "  To:   $DEST"
cp -a "$DATA_DIR" "$DEST"
echo "Done. Keep this folder until you have verified the update."
