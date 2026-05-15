# Webable

**TL;DR:** Webable is a **local-first** personal finance web app (FastAPI + Jinja2). Run it on your own machine with Docker; keep databases and uploaded bank PDFs in `./data`. This repository can publish a **GitHub Pages** site under `docs/` that explains installation only — it does **not** host the Python backend.

## Core functionality

- Register / log in with session cookies (data stays on your machine).
- Multiple isolated workspaces (per-workspace SQLite finance + logic databases).
- Recurring income and expenses, one-off transactions, monthly and long-range projections.
- Bank statement PDF uploads, reports, savings and investment calculators, market watch helpers.
- Optional local AI chat via Ollama (not required for core budgeting).

## Visual directory tree

```text
.
├── app/
│   ├── auth.py
│   ├── db.py
│   ├── main.py
│   ├── models.py
│   ├── services/
│   ├── static/
│   └── templates/
├── data/
│   └── .gitkeep          # placeholder; real data is created at runtime (not in git)
├── docs/
│   └── index.html        # GitHub Pages landing / install instructions only
├── tests/
├── Dockerfile
├── docker-compose.yml
├── Makefile
├── requirements.txt
├── webapp.py             # ASGI entry: imports FastAPI app from app.main
├── budget.py             # legacy CLI helper (optional)
├── iefp_budget.py
├── funds.py
└── …
```

## Prerequisites and setup

- **Git**
- **Docker** and **Docker Compose** (Compose v2: `docker compose …`)

### Downloading prequesities and running the program

**Linux (Terminal):**

```bash
# Arch Linux
sudo pacman -Syu git docker docker-compose
sudo systemctl enable --now docker
docker compose up -d --build

# Debian / Ubuntu
sudo apt update && sudo apt install -y git docker.io docker-compose-plugin
sudo systemctl enable --now docker
docker compose up -d --build

# Fedora / RHEL / Rocky
sudo dnf install -y git docker docker-compose-plugin
sudo systemctl enable --now docker
docker compose up -d --build

# (Optional)Add your user to the docker group (avoids needing sudo every time)
sudo usermod -aG docker $USER && newgrp docker
```

> **Windows (PowerShell):** paste this to install prerequisites and start the app:
> ```powershell
> winget install -e --id Git.Git
> winget install -e --id Docker.DockerDesktop
> # After Docker Desktop finishes installing, restart PowerShell, then:
> git clone https://github.com/zeromeia0/webable.git
> cd webable
> docker compose up -d --build
> ```
>

Restart PowerShell after Docker Desktop finishes installing before running any `docker` commands.

**macOS (Terminal):**

```bash
brew install --cask docker
brew install git
open /Applications/Docker.app
```

> If you don't have Homebrew: `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"`

> Docker Desktop must be running (whale icon in the menu bar) before any `docker` command will work.


### Run with Docker (recommended)

From the repository root:

```bash
docker compose up -d --build
```

Open **http://localhost:8080** in your browser.

The container runs **uvicorn** on port **8000** inside the network namespace; Compose maps **host 8080 → container 8000**. Data is stored under **`./data` on the host**, mounted at `/app/data` in the container (`WEBABLE_DATA_DIR=/app/data`).


### Optional Makefile shortcuts

```bash
make up       # docker compose up -d --build
make down     # docker compose down
make logs     # docker compose logs -f
make restart  # docker compose restart
make update   # git pull && docker compose up -d --build
```
> The `make` shortcuts require GNU Make (`winget install -e --id GnuWin32.Make`), otherwise use the raw `docker compose` commands directly.

### Run without Docker (developers)

**macOS / Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export WEBABLE_DATA_DIR="${PWD}/data"   # optional; defaults to ./data
uvicorn webapp:app --host 127.0.0.1 --port 8000 --reload
```

**Windows (PowerShell):**

```powershell
git clone https://github.com/zeromeia0/webable.git
cd webable
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
$env:WEBABLE_DATA_DIR = "$PWD\data"
uvicorn webapp:app --host 127.0.0.1 --port 8000 --reload
```

Then open http://127.0.0.1:8000.

## Technology stack

- Python 3.12+ (Docker image pinned to 3.12-slim; local 3.14 also works with the same dependencies).
- FastAPI, Uvicorn, SQLAlchemy, Jinja2, python-multipart, dateutil, ReportLab / Matplotlib / pypdf for PDF features.

## Local-first privacy

- Financial data and uploaded PDFs live under **`data/`** on your computer (or the path you set with `WEBABLE_DATA_DIR`).
- **GitHub Pages** (from `docs/`) only serves a static install page. It does **not** run the FastAPI app and never sees your balances or uploads.

## Changing the host port

In `docker-compose.yml`, the mapping is `HOST_PORT:CONTAINER_PORT`:

```yaml
ports:
  - "8080:8000"
```

- **Left** (`8080`): port on your machine.
- **Right** (`8000`): port the app listens on **inside** the container (uvicorn).

If **8080 is already in use**, change only the left side, for example `"8081:8000"`, then open http://localhost:8081.

## Stop, restart, update, logs

| Action   | Command |
|----------|---------|
| Stop     | `docker compose down` |
| Restart  | `docker compose restart` |
| Update   | `git pull` then `docker compose up -d --build` |
| Logs     | `docker compose logs -f` |
| Status   | `docker compose ps` |

## Health check

Lightweight liveness endpoint (no auth):

```http
GET /health
```

Response: `{"status":"ok"}`.

## Data persistence

- `./data` is mounted into the container, so SQLite files, `statements/`, and currency/market JSON caches survive **restarts**, **`docker compose down`**, and **rebuilds**.
- The Docker **image** does not include your personal databases; first run creates an empty app database if none exists.
- **Backup:** copy the whole `data/` folder somewhere safe.
- **Warning:** deleting `data/` removes all local app data (workspaces, uploads, app DB).

## Security notes

- Intended for **local** or trusted-network use.
- Do **not** expose the container to the public internet without strong authentication, HTTPS, a reverse proxy, and a security review.
- Do **not** commit `data/`, `.env`, or secrets. Use `.gitignore` and never push real financial exports.

## Enabling GitHub Pages (install page only)

1. Push this repository to GitHub.
2. Repository **Settings → Pages**.
3. **Build and deployment**: Source = **Deploy from a branch**.
4. Branch = **`main`** (or your default), folder = **`/docs`**.
5. Save. After a short build, the site URL will look like `https://<user>.github.io/webable/`.

## Troubleshooting

| Problem | What to try |
|---------|----------------|
| **Port 8080 already in use** | Change host port in `docker-compose.yml` to e.g. `"8081:8000"`, then `docker compose up -d --build`. |
| **Docker daemon not running** | **Windows/macOS:** launch Docker Desktop and wait for it to finish starting. **Linux:** `sudo systemctl start docker`. |
| **Permission denied on Linux** | Add your user to the `docker` group (`sudo usermod -aG docker $USER`), log out/in, or use `sudo docker compose …` temporarily. |
| **`docker compose` not found** | **Windows/macOS:** open Docker Desktop — Compose v2 is bundled. **Linux:** install the `docker-compose-plugin` package. |
| **File sharing / bind-mount errors (Windows or macOS)** | In Docker Desktop → Settings → Resources → File Sharing, make sure the drive or folder containing the project is shared. |
| **WSL 2 not installed (Windows)** | Run `wsl --install` in an admin PowerShell, reboot, then reopen Docker Desktop. |
| **Browser cannot open localhost** | Run `docker compose ps` — container should be "running". Check logs: `docker compose logs -f`. Try `curl -sS http://127.0.0.1:8080/health`. |
| **Container exits immediately** | `docker compose logs webable` for tracebacks (e.g. missing bind mount permissions). |

## Repository hygiene (removing accidentally tracked junk)

If `__pycache__`, `*.pyc`, `data/*.db`, or other local files were committed by mistake, **keep files on disk** but stop tracking them:

```bash
git rm -r --cached __pycache__ app/__pycache__ app/services/__pycache__ tests/__pycache__ 2>/dev/null || true
git rm -r --cached data/
git rm --cached financas.db iefp_bolsas.db 2>/dev/null || true
git ls-files '*.db' | xargs -r git rm --cached
git add .gitignore .dockerignore data/.gitkeep Dockerfile docker-compose.yml docs/index.html Makefile README.md app/db.py app/main.py
git status
git commit -m "chore: dockerize, ignore local data, add Pages landing"
```

Adjust paths to match what `git ls-files` still shows. **Do not** run destructive commands like `rm -rf data/` unless you intend to wipe local data.

## Startup details (for operators)

- **ASGI app:** `webapp:app` (`webapp.py` imports `app` from `app.main`).
- **Server command:** `uvicorn webapp:app --host 0.0.0.0 --port 8000` (Dockerfile / Compose).
- **Internal container port:** **8000** (Compose maps `8080:8000` by default).
- **Data directory:** `WEBABLE_DATA_DIR` (default relative `data/` resolved to an absolute path); main app DB is `webable_app.db` inside that directory.

## Verification checklist

After changes, you can confirm:

- [ ] `Dockerfile`, `docker-compose.yml`, `.gitignore`, `.dockerignore`, `docs/index.html` exist.
- [ ] `docker compose config` prints valid YAML.
- [ ] `docker compose up -d --build` starts; `curl -sS http://127.0.0.1:8080/health` returns `{"status":"ok"}`.
- [ ] Browser: http://localhost:8080 loads the app.
- [ ] `./data` on the host gains files after use; survives `docker compose restart`.
- [ ] GitHub Pages: enable from `/docs` as above.