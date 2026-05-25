#!/usr/bin/env bash
# Optional AI setup: pull/start Ollama and enable AI env on the Webable service.
# Does not download cloud model weights — sign in after start (see README).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

MODE="${WEBABLE_AI_COMPOSE_MODE:-local}"
if [[ "${1:-}" == "--image" ]]; then
  MODE=image
elif [[ "${1:-}" == "--local" ]]; then
  MODE=local
fi

if [[ "$MODE" == "image" ]]; then
  COMPOSE_FILES=(-f docker-compose.image.yml -f docker-compose.ai.yml)
  echo "==> AI setup (GHCR image compose)"
else
  COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.ai.yml)
  echo "==> AI setup (local build compose)"
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required. Install Docker, then re-run: make ai" >&2
  exit 1
fi

echo "==> Pulling Ollama image..."
docker compose "${COMPOSE_FILES[@]}" pull ollama

echo "==> Starting Ollama sidecar..."
docker compose "${COMPOSE_FILES[@]}" up -d ollama

echo "==> Applying AI environment to Webable (recreate if needed)..."
docker compose "${COMPOSE_FILES[@]}" up -d webable

echo ""
echo "Optional AI stack is running."
echo "One-time Ollama Cloud sign-in (cloud model, no local pull at startup):"
echo "  docker exec -it webable-ollama ollama signin"
echo "  docker exec -it webable-ollama ollama run minimax-m2.5:cloud"
echo ""
echo "Full stack with AI: make ai-run"
