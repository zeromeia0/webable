#!/usr/bin/env bash
# Recommended update flow: backup → pull → migrate → rebuild/restart (Docker).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "=== Step 1: Backup data ==="
bash "$ROOT/scripts/webable-backup.sh"

echo ""
echo "=== Step 2: Pull latest code ==="
git pull

echo ""
echo "=== Step 3: Run additive migrations ==="
bash "$ROOT/scripts/webable-migrate.sh"

echo ""
echo "=== Step 4: Rebuild and restart (Docker) ==="
if command -v docker >/dev/null 2>&1 && [[ -f docker-compose.yml ]]; then
  docker compose up -d --build
  echo "Open http://localhost:8080"
else
  echo "Docker not found. Start manually: uvicorn webapp:app --host 127.0.0.1 --port 8000"
fi

echo ""
echo "Update complete. Do NOT delete the data/ folder or your backup."
