#!/usr/bin/env bash
# Host-side helper for the in-app "Restart server" button.
#
# Watches the shared data directory for .restart-request (written by the app container), then runs
# `docker compose up -d --build` for this repository and reports progress in .restart-status.json.
# The request file is only a flag — nothing in it is executed.
#
# Install as a systemd service (runs as root so it can talk to Docker):
#   sudo make install-restart-helper
set -u

REPO_DIR="${WEBABLE_REPO_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
DATA_DIR="${WEBABLE_HOST_DATA_DIR:-$REPO_DIR/data}"
COMPOSE_FILE="$REPO_DIR/docker-compose.yml"
POLL_SECONDS=2
HEARTBEAT_SECONDS=10
BUILD_TIMEOUT_SECONDS=1200

REQUEST="$DATA_DIR/.restart-request"
RUNNING="$DATA_DIR/.restart-running"
STATUS="$DATA_DIR/.restart-status.json"
HEARTBEAT="$DATA_DIR/.restart-watcher-heartbeat"
LOG="$DATA_DIR/.restart-last.log"

json_escape() {
  local s=$1
  s=${s//\\/\\\\}
  s=${s//\"/\\\"}
  s=${s//$'\n'/\\n}
  s=${s//$'\r'/}
  s=${s//$'\t'/ }
  printf '%s' "$s"
}

write_status() {
  local state=$1 message=$2 tail=""
  if [[ -f "$LOG" ]]; then
    tail=$(tail -n 15 "$LOG" | tr -d '\000-\010\013\014\016-\037')
  fi
  printf '{"state":"%s","message":"%s","updated_at":"%s","log_tail":"%s"}\n' \
    "$state" "$(json_escape "$message")" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(json_escape "$tail")" > "$STATUS.tmp"
  mv -f "$STATUS.tmp" "$STATUS"
}

rebuild() {
  local commit build_time rc
  commit=$(git -c safe.directory="$REPO_DIR" -C "$REPO_DIR" rev-parse --short HEAD 2>/dev/null || echo "")
  build_time=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  : > "$LOG"
  write_status running "Rebuilding image and restarting containers"
  echo "[$build_time] docker compose up -d --build (commit ${commit:-unknown})" >> "$LOG"

  (
    cd "$REPO_DIR" &&
      WEBABLE_GIT_COMMIT="$commit" WEBABLE_BUILD_TIME="$build_time" \
        timeout "$BUILD_TIMEOUT_SECONDS" docker compose -f "$COMPOSE_FILE" up -d --build
  ) >> "$LOG" 2>&1 &
  local pid=$!
  # Keep the heartbeat fresh while building so the app still sees the helper as online.
  while kill -0 "$pid" 2>/dev/null; do
    touch "$HEARTBEAT"
    sleep "$POLL_SECONDS"
  done
  wait "$pid"
  rc=$?

  if [[ $rc -eq 0 ]]; then
    write_status done "Rebuilt and restarted"
  else
    write_status failed "docker compose exited with code $rc"
  fi
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] finished with exit code $rc" >> "$LOG"
}

if [[ ! -f "$COMPOSE_FILE" ]]; then
  echo "docker-compose.yml not found in $REPO_DIR" >&2
  exit 1
fi
mkdir -p "$DATA_DIR"
echo "Webable restart helper watching $DATA_DIR (repo: $REPO_DIR)"

last_heartbeat=0
while true; do
  now=$(date +%s)
  if (( now - last_heartbeat >= HEARTBEAT_SECONDS )); then
    touch "$HEARTBEAT"
    last_heartbeat=$now
  fi
  if [[ -f "$REQUEST" ]]; then
    mv -f "$REQUEST" "$RUNNING"
    echo "Restart requested: $(head -c 300 "$RUNNING" 2>/dev/null)"
    rebuild
    rm -f "$RUNNING"
    last_heartbeat=0
  fi
  sleep "$POLL_SECONDS"
done
