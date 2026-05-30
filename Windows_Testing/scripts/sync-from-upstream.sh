#!/usr/bin/env bash
# Refresh Windows_Testing app source from parent repo (../). Does not touch build/, dist/, or venv.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UPSTREAM="$(cd "$ROOT/.." && pwd)"

if [[ ! -f "$UPSTREAM/webapp.py" ]]; then
  echo "Upstream webable repo not found at $UPSTREAM" >&2
  exit 1
fi

echo "Syncing from $UPSTREAM -> $ROOT"
rsync -a --delete \
  --exclude='.git' \
  --exclude='.venv' \
  --exclude='.venv-win' \
  --exclude='data' \
  --exclude='Windows_Testing' \
  --exclude='dist' \
  --exclude='build' \
  --exclude='__pycache__' \
  "$UPSTREAM/app" \
  "$UPSTREAM/webapp.py" \
  "$UPSTREAM/requirements.txt" \
  "$UPSTREAM/VERSION" \
  "$UPSTREAM/update.md" \
  "$ROOT/"

echo "Done. Windows-only files (windows/, build/, installer/, windows_launcher.py) were preserved."
