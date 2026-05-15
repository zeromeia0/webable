# Webable

**Webable** is a local-first personal finance web app — it runs on your own machine via Docker, and your data never leaves it. Track income and expenses, project cash flow, upload bank statements, and optionally chat with a local AI.

> **GitHub Pages** (from `docs/`) only serves a static install page. It does **not** run the Python backend and never sees your financial data.

---

## Features

- Register and log in with session-based auth (data stays on your machine)
- Multiple isolated workspaces, each with its own SQLite database
- Recurring income/expenses, one-off transactions, monthly and long-range projections
- Bank statement PDF uploads, reports, savings and investment calculators, market watch helpers
- Optional local AI chat via Ollama (not required for core budgeting)

---

## Quick start

### 1. Install prerequisites

Pick your OS:

**Linux**

```bash
# Arch
sudo pacman -Syu git docker docker-compose
sudo systemctl enable --now docker

# Debian / Ubuntu
sudo apt update && sudo apt install -y git docker.io docker-compose-plugin
sudo systemctl enable --now docker

# Fedora / RHEL / Rocky
sudo dnf install -y git docker docker-compose-plugin
sudo systemctl enable --now docker
```

> **Optional:** add yourself to the `docker` group so you don't need `sudo` every time:
> ```bash
> sudo usermod -aG docker $USER && newgrp docker
> ```

**Windows (PowerShell)**

```powershell
winget install -e --id Git.Git
winget install -e --id Docker.DockerDesktop
```

Restart PowerShell after Docker Desktop finishes installing, then continue to step 2.

**macOS**

```bash
# Install Homebrew if you don't have it:
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

brew install git
brew install --cask docker
open /Applications/Docker.app   # must be running before any docker command
```

---

### 2. Clone and run

```bash
git clone https://github.com/zeromeia0/webable.git
cd webable
docker compose up -d --build
```

Then open **http://localhost:8080** in your browser.

That's it. Data is stored in `./data` on your machine and persists across restarts and rebuilds.

---

## Stopping, restarting, and updating

| Action | Command |
|--------|---------|
| Stop | `docker compose down` |
| Restart | `docker compose restart` |
| Update to latest | `git pull && docker compose up -d --build` |
| View logs | `docker compose logs -f` |
| Check status | `docker compose ps` |

### Makefile shortcuts (optional)

If you have GNU Make installed (`winget install -e --id GnuWin32.Make` on Windows):

```bash
make up       # docker compose up -d --build
make down     # docker compose down
make logs     # docker compose logs -f
make restart  # docker compose restart
make update   # git pull && docker compose up -d --build
```

---

## Verify it's working

```bash
curl -sS http://127.0.0.1:8080/health
# → {"status":"ok"}
```

---

## Data and backups

- All data lives in **`./data`** on your host machine (mounted into the container at `/app/data`).
- It survives `docker compose down`, restarts, and image rebuilds — the Docker image itself contains no personal data.
- **To back up:** copy the entire `data/` folder somewhere safe.
- **Warning:** deleting `data/` permanently removes all workspaces, uploads, and databases.

---

## Changing the port

If port 8080 is already in use, edit `docker-compose.yml`:

```yaml
ports:
  - "8081:8000"   # change 8080 to any free port on the left side
```

The right side (`8000`) is the port uvicorn listens on inside the container — leave it as-is. Then rebuild:

```bash
docker compose up -d --build
```

---

## Running without Docker (developers)

**macOS / Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn webapp:app --host 127.0.0.1 --port 8000 --reload
```

**Windows (PowerShell):**

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn webapp:app --host 127.0.0.1 --port 8000 --reload
```

Open http://127.0.0.1:8000.

> `WEBABLE_DATA_DIR` controls where data is stored (defaults to `./data`).

---

## Technology stack

- **Python 3.12+** — Docker image pinned to `3.12-slim`
- **FastAPI**, Uvicorn, SQLAlchemy, Jinja2
- **ReportLab / Matplotlib / pypdf** — PDF features
- **SQLite** — one database per workspace, stored in `./data`

---

## Security

Webable is designed for **local or trusted-network use only**.

- Do not expose it to the public internet without a reverse proxy, HTTPS, and strong authentication.
- Do not commit `data/`, `.env`, or any secrets. Keep them in `.gitignore`.
- Never push real bank exports or financial data to a repository.

---

## Enabling the GitHub Pages install page

1. Push this repo to GitHub.
2. Go to **Settings → Pages**.
3. Set source to **Deploy from a branch**, branch `main`, folder `/docs`.
4. Save — after a short build, the page will be live at `https://<user>.github.io/webable/`.

---

## Troubleshooting

| Problem | What to try |
|---------|-------------|
| **Port 8080 already in use** | Change the left side of the port mapping in `docker-compose.yml` (e.g. `"8081:8000"`), then run `docker compose up -d --build`. |
| **Docker daemon not running** | Windows/macOS: open Docker Desktop and wait for the whale icon. Linux: `sudo systemctl start docker`. |
| **Permission denied on Linux** | Add yourself to the docker group: `sudo usermod -aG docker $USER`, then log out and back in. Or prefix commands with `sudo`. |
| **`docker compose` not found** | Windows/macOS: open Docker Desktop — Compose v2 is bundled. Linux: install `docker-compose-plugin`. |
| **File sharing / bind-mount errors** | Docker Desktop → Settings → Resources → File Sharing — make sure the project folder's drive is shared. |
| **WSL 2 not installed (Windows)** | Run `wsl --install` in an admin PowerShell, reboot, then reopen Docker Desktop. |
| **Browser can't reach localhost** | Run `docker compose ps` to confirm the container is running. Check logs with `docker compose logs -f`. Try `curl -sS http://127.0.0.1:8080/health`. |
| **Container exits immediately** | Run `docker compose logs webable` and look for a traceback (often a missing bind-mount or permission error). |

---

## Project layout

```
.
├── app/
│   ├── auth.py
│   ├── db.py
│   ├── main.py
│   ├── models.py
│   ├── services/
│   ├── static/
│   └── templates/
├── data/                   # runtime data (not in git — created on first run)
│   └── .gitkeep
├── docs/
│   └── index.html          # GitHub Pages install page only
├── tests/
├── Dockerfile
├── docker-compose.yml
├── Makefile
├── requirements.txt
├── webapp.py               # ASGI entry point
└── budget.py               # legacy CLI helper (optional)
```

---

## Cleaning up accidentally committed files

If `__pycache__`, `*.pyc`, database files, or other local artifacts were committed by mistake, remove them from git tracking without deleting them from disk:

```bash
git rm -r --cached __pycache__ app/__pycache__ app/services/__pycache__ tests/__pycache__ 2>/dev/null || true
git rm -r --cached data/
git ls-files '*.db' | xargs -r git rm --cached
git add .gitignore
git commit -m "chore: stop tracking local data and cache files"
```