#!/usr/bin/env bash
# One-step Linux setup: installs Docker if missing, starts Webable (core, no AI)
# and waits until it answers on http://localhost:8080.
#
# From a clone:   make setup
# Without a clone:
#   curl -fsSL https://raw.githubusercontent.com/zeromeia0/webable/main/scripts/webable-linux-setup.sh | bash
#
# Env overrides: WEBABLE_DIR (clone target, default ~/webable), WEBABLE_REPO, WEBABLE_NO_OPEN=1
set -euo pipefail

REPO_URL="${WEBABLE_REPO:-https://github.com/zeromeia0/webable.git}"
INSTALL_DIR="${WEBABLE_DIR:-$HOME/webable}"
APP_URL="http://localhost:8080"

say()  { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }

[[ "$(uname -s)" == "Linux" ]] || die "This script is for Linux. See README.md for Windows/macOS."

SUDO=""
if [[ $EUID -ne 0 ]]; then
  command -v sudo >/dev/null 2>&1 || die "sudo is required to install packages."
  SUDO="sudo"
fi

# --- Detect package manager -------------------------------------------------
PM=""
if   command -v pacman  >/dev/null 2>&1; then PM=pacman
elif command -v apt-get >/dev/null 2>&1; then PM=apt
elif command -v dnf     >/dev/null 2>&1; then PM=dnf
elif command -v zypper  >/dev/null 2>&1; then PM=zypper
fi

pkg_install() {
  case "$PM" in
    pacman) $SUDO pacman -S --needed --noconfirm "$@" ;;
    apt)    $SUDO apt-get install -y "$@" ;;
    dnf)    $SUDO dnf install -y "$@" ;;
    zypper) $SUDO zypper --non-interactive install "$@" ;;
    *)      return 1 ;;
  esac
}

# Try candidates in order; distros name the compose v2 package differently.
pkg_install_any() {
  local p
  for p in "$@"; do
    pkg_install "$p" >/dev/null 2>&1 && return 0
  done
  return 1
}

[[ "$PM" == "apt" ]] && NEED_APT_UPDATE=1 || NEED_APT_UPDATE=0
apt_update_once() {
  if [[ $NEED_APT_UPDATE -eq 1 ]]; then
    $SUDO apt-get update -qq
    NEED_APT_UPDATE=0
  fi
}

# --- Small tools: curl (health check) and make (day-to-day commands) -------
for tool in curl make; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    say "Installing $tool..."
    apt_update_once
    pkg_install "$tool" || warn "Could not install $tool."
  fi
done

# --- git (only needed when we have to clone) -------------------------------
SCRIPT_PATH="${BASH_SOURCE[0]:-}"
REPO_ROOT=""
if [[ -n "$SCRIPT_PATH" && -f "$SCRIPT_PATH" ]]; then
  candidate="$(cd "$(dirname "$SCRIPT_PATH")/.." && pwd)"
  [[ -f "$candidate/docker-compose.yml" ]] && REPO_ROOT="$candidate"
fi

if [[ -z "$REPO_ROOT" ]]; then
  if [[ -f "$INSTALL_DIR/docker-compose.yml" ]]; then
    say "Using existing copy in $INSTALL_DIR"
  else
    if ! command -v git >/dev/null 2>&1; then
      say "Installing git..."
      apt_update_once
      pkg_install git || die "Could not install git. Install it manually and re-run."
    fi
    say "Downloading Webable into $INSTALL_DIR..."
    git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
  fi
  REPO_ROOT="$INSTALL_DIR"
fi
cd "$REPO_ROOT"

# --- Docker engine ---------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  [[ -n "$PM" ]] || die "Unsupported distro: install Docker (https://docs.docker.com/engine/install/) and re-run."
  say "Installing Docker (you may be asked for your password)..."
  apt_update_once
  case "$PM" in
    pacman) pkg_install docker ;;
    apt)    pkg_install docker.io ;;
    dnf)    pkg_install_any docker moby-engine docker-ce ;;
    zypper) pkg_install docker ;;
  esac || die "Docker install failed. See https://docs.docker.com/engine/install/"
fi

if command -v systemctl >/dev/null 2>&1; then
  if ! systemctl is-active --quiet docker; then
    say "Starting the Docker service..."
    $SUDO systemctl enable --now docker
  fi
fi

# Use plain `docker` if the user can reach the daemon, otherwise fall back to sudo
# for this run and add the user to the docker group for next time.
DOCKER="docker"
if ! docker info >/dev/null 2>&1; then
  if [[ $EUID -ne 0 ]] && $SUDO docker info >/dev/null 2>&1; then
    DOCKER="$SUDO docker"
    if ! id -nG "$USER" | tr ' ' '\n' | grep -qx docker; then
      say "Adding $USER to the 'docker' group (takes effect after you log out and back in)..."
      $SUDO usermod -aG docker "$USER" || warn "Could not add $USER to the docker group."
    fi
  else
    die "Docker is installed but not running. Try: sudo systemctl start docker"
  fi
fi

# --- Docker Compose v2 -----------------------------------------------------
if ! $DOCKER compose version >/dev/null 2>&1; then
  say "Installing Docker Compose..."
  apt_update_once
  case "$PM" in
    pacman) pkg_install_any docker-compose ;;
    apt)    pkg_install_any docker-compose-plugin docker-compose-v2 docker-compose ;;
    dnf)    pkg_install_any docker-compose-plugin docker-compose ;;
    zypper) pkg_install_any docker-compose ;;
  esac || true
fi

if $DOCKER compose version >/dev/null 2>&1; then
  COMPOSE="$DOCKER compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE="${DOCKER%docker}docker-compose"
else
  die "Docker Compose not found. See https://docs.docker.com/compose/install/linux/"
fi

# --- Start Webable ---------------------------------------------------------
if command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | grep -q ':8080 '; then
  if ! $DOCKER ps --format '{{.Names}}' 2>/dev/null | grep -qx webable; then
    warn "Port 8080 is already used by another program; Webable may fail to start."
  fi
fi

# Create ./data as the current user so the bind mount isn't root-owned.
mkdir -p data

say "Building and starting Webable (first run takes a few minutes)..."
$COMPOSE -f docker-compose.yml up -d --build

say "Waiting for Webable to come up..."
ready=0
for _ in $(seq 1 60); do
  if curl -fsS "$APP_URL/health" >/dev/null 2>&1; then ready=1; break; fi
  sleep 2
done

echo ""
if [[ $ready -eq 1 ]]; then
  say "Webable is running at $APP_URL"
  if [[ -z "${WEBABLE_NO_OPEN:-}" && -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]] && command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$APP_URL" >/dev/null 2>&1 || true
  fi
else
  warn "Webable didn't answer yet. Check the logs with:  cd $REPO_ROOT && make logs"
fi

cat <<EOF

  Folder:  $REPO_ROOT
  Data:    $REPO_ROOT/data   (stays on this machine)

  Stop:    make down      Start again:  make run
  Logs:    make logs      Update:       make update
EOF

if [[ "$DOCKER" != "docker" ]]; then
  echo ""
  warn "Log out and back in once so 'make' commands work without sudo."
fi
