# Webable

**Webable** is a local-first personal finance web app. It runs on your own machine in Docker, and your data never leaves it.

- Track recurring and one-off income and expenses, with monthly and long-range projections
- Upload bank statements and other documents, and generate PDF reports
- Savings, investment and net-worth tools, plus a market watch
- Multiple isolated workspaces, each with its own database
- Optional AI finance chat (off by default, not needed for anything else)

---

## Install

### Linux: one command

```bash
curl -fsSL https://raw.githubusercontent.com/zeromeia0/webable/main/scripts/webable-linux-setup.sh | bash
```

This script:
1. Installs Docker if it's missing (Arch, Debian/Ubuntu, Fedora/RHEL, openSUSE). It asks for your `sudo` password only if it needs to install something.
2. Downloads Webable into `~/webable`. To use another folder, run `WEBABLE_DIR=/your/path` before `bash`.
3. Starts the app and opens **http://localhost:8080**.

If you already cloned the repo, run `make setup` inside it instead.

### Windows, macOS, or Linux by hand

**Step 1: install Git and Docker.**

| OS | Commands |
|----|----------|
| Windows (PowerShell) | `winget install -e --id Git.Git`<br>`winget install -e --id Docker.DockerDesktop`<br>Then **restart PowerShell** and open Docker Desktop. |
| macOS ([Homebrew](https://brew.sh)) | `brew install git`<br>`brew install --cask docker`<br>`open /Applications/Docker.app` |
| Debian / Ubuntu | `sudo apt install -y git docker.io docker-compose-plugin` |
| Fedora / RHEL | `sudo dnf install -y git docker docker-compose-plugin` |
| Arch | `sudo pacman -S git docker docker-compose` |

On Linux, start Docker and let your user run it without `sudo`, then **log out and back in**:

```bash
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
```

On Windows and macOS, **Docker Desktop must be running** before any `docker` command will work.

**Step 2: download and start Webable.**

```bash
git clone https://github.com/zeromeia0/webable.git
cd webable
docker compose up -d --build
```

**Step 3: open http://localhost:8080** and create an account.

To check that it's running, `curl http://127.0.0.1:8080/health` should print `{"status":"ok"}`.

---

## Everyday commands

Run these from inside the `webable` folder. If you have `make`, use the shorter versions in the second column.

| To… | Command | With make |
|-----|---------|-----------|
| Start | `docker compose up -d --build` | `make run` |
| Stop | `docker compose down` | `make down` |
| Restart | `docker compose restart` | `make restart` |
| See logs | `docker compose logs -f` | `make logs` |
| See status | `docker compose ps` | `make ps` |
| Back up data | `bash scripts/webable-backup.sh` | `make backup` |
| Update (with backup) | `bash scripts/webable-safe-update.sh` | `make safe-update` |

---

## Updating

```bash
make safe-update      # or: bash scripts/webable-safe-update.sh
```

This backs up `data/`, runs `git pull`, then rebuilds and restarts the app. Database changes apply automatically on startup and only add to your data, never remove it.

On Windows without bash:

```powershell
Copy-Item -Recurse .\data "..\webable-data-backup-$(Get-Date -Format yyyyMMdd-HHmmss)"
git pull
docker compose up -d --build
```

Then open the app and check that your workspaces are still there.

---

## Your data

Everything lives in the **`data/`** folder in the project. It survives restarts, rebuilds and updates, and it is never committed to git.

| What | Where |
|------|-------|
| Users and workspaces | `data/webable_app.db` |
| Each workspace's finances | `data/user_<id>/` |
| Uploaded statements and documents | `data/statements/<workspace_id>/` |

**Back up** by copying `data/` somewhere safe, or run `make backup`. The backup is saved next to the project as `webable-data-backup-YYYYMMDD-HHMMSS/`.

**Restore** a backup:

```bash
docker compose down
mv data data.broken
cp -a webable-data-backup-YYYYMMDD-HHMMSS data
docker compose up -d
```

> ⚠️ These commands **permanently delete your data**: `rm -rf data`, `git clean -fdx`, or replacing `data/` with an empty folder. Deleting a workspace in the app is also permanent, but only affects that workspace.

---

## Optional: AI chat

The AI assistant uses [Ollama](https://ollama.com) with the cloud model `minimax-m2.5:cloud`. It's off by default, so nothing gets downloaded unless you turn it on.

```bash
make ai                                              # 1. start Ollama and enable AI in Webable
docker exec -it webable-ollama ollama signin         # 2. sign in to Ollama (opens a link)
docker exec -it webable-ollama ollama run minimax-m2.5:cloud   # 3. check the model responds
```

To turn it off, run `make ai-down` to stop Ollama, then `make run` to restart Webable without AI. If AI is disabled or not signed in, the chat panel in the app tells you what to do.

---

## Changing the port

If port 8080 is taken, edit `docker-compose.yml` and change **only the left number**:

```yaml
ports:
  - "8081:8000"
```

Then run `docker compose up -d --build` and open http://localhost:8081.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `Cannot connect to the Docker daemon` | Windows/macOS: open Docker Desktop and wait until it says it's running. Linux: `sudo systemctl start docker`. |
| `permission denied` on Linux | Run `sudo usermod -aG docker $USER`, then log out and back in. |
| `docker compose` not found | Linux: install `docker-compose-plugin`. Windows/macOS: it comes with Docker Desktop. |
| Windows asks for WSL 2 | In an admin PowerShell, run `wsl --install`, reboot, then reopen Docker Desktop. |
| Port already in use | See [Changing the port](#changing-the-port). |
| Page doesn't load | Run `docker compose ps` to check the container is up, then `docker compose logs -f` to look for errors. |
| Container stops right away | Run `docker compose logs webable` and look for the traceback at the end. |

---

## For developers

Run without Docker (Python 3.12+):

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn webapp:app --reload      # http://127.0.0.1:8000
```

Or just run `make install` and then `make run-local`.

Run the tests with `python -m unittest discover -s tests`.

**Stack:** FastAPI, Uvicorn, SQLAlchemy, Jinja2, SQLite (one database per workspace), ReportLab, Matplotlib, pypdf.

```
app/              FastAPI app: main.py (routes), models.py, services/, templates/, static/
tests/            unit tests
scripts/          install, backup, migrate and update scripts
docs/             static GitHub Pages install page (no backend, no data)
Windows_Testing/  Windows desktop build without Docker (see its README)
data/             your data, created on first run (not in git)
webapp.py         ASGI entry point
```

Prebuilt Docker images, Watchtower auto-updates, in-app updates and release steps are all in **[DEPLOYMENT.md](DEPLOYMENT.md)**.

---

## Security

Webable is built for **your own machine or a trusted home network**. Don't put it on the public internet without a reverse proxy, HTTPS and strong passwords, and never commit `data/` or real bank exports to a repository.
