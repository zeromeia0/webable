#!/usr/bin/env bash
# Lightweight project install — core app only (no Ollama / AI images).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> Webable core install (no AI downloads)"

if command -v python3 >/dev/null 2>&1; then
  if [[ ! -d .venv ]]; then
    echo "==> Creating Python virtualenv..."
    python3 -m venv .venv
  fi
  # shellcheck disable=SC1091
  source .venv/bin/activate
  pip install -U pip -q
  pip install -r requirements.txt -q
  echo "==> Python dependencies installed in .venv"
else
  echo "==> python3 not found — skip venv (Docker-only install is fine)"
fi

mkdir -p data
echo ""
echo "Core install complete."
echo "  Start app:  make run     (Docker, no AI)"
echo "  Enable AI:  make ai      (optional Ollama setup)"
echo "  Dev server: make run-local   (uvicorn + .venv)"
