#!/usr/bin/env bash
# Run additive schema migrations only — does NOT delete databases or reseed users.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export WEBABLE_DATA_DIR="${WEBABLE_DATA_DIR:-$ROOT/data}"

echo "Webable safe migrations (additive only; no data wipe)."
echo "Data directory: $WEBABLE_DATA_DIR"
echo ""

if [[ -d "$ROOT/.venv" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT/.venv/bin/activate"
elif [[ -d "$ROOT/venv" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT/venv/bin/activate"
fi

python3 -m app.cli migrate

echo ""
echo "Migrations finished. Your existing records were preserved."
