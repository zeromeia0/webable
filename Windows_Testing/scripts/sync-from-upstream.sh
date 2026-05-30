#!/usr/bin/env bash
# Refresh app/ and root stubs from parent repo (../). Preserves build/, windows_launcher.py, specs.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UPSTREAM="$(cd "$ROOT/.." && pwd)"
[[ -f "$UPSTREAM/webapp.py" ]] || { echo "Missing upstream at $UPSTREAM"; exit 1; }
rsync -a --delete \
  --exclude='__pycache__' \
  "$UPSTREAM/app" \
  "$UPSTREAM/webapp.py" \
  "$UPSTREAM/VERSION" \
  "$UPSTREAM/update.md" \
  "$UPSTREAM/requirements.txt" \
  "$ROOT/"
echo "Synced app source from $UPSTREAM"
