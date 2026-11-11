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

## Spending report from the terminal (`create_relatorio`)

`create_relatorio` turns a Crédito Agrícola **Extracto Integrado** (PDF) into a **Relatório de Gastos** (PDF). It's the same 5-page report as the existing `Relatorio_Gastos_<Mês>_<Ano>.pdf` files: summary cards, the "Resumo" paragraph, the three charts, the category table, "Fora dos gastos", "Entradas", "Observações" and the list of all outgoing payments.

It runs entirely on your machine. It doesn't need the website, Docker or the internet.

### Run it

From the `webable` folder:

```bash
./create_relatorio ~/Downloads/Extracto_Integrado_Novembro_2026.pdf
```

This creates `Relatorio_Gastos_Novembro_2026.pdf` in the folder you're in, then prints the main totals plus any purchases it couldn't put in a category.

| Option | What it does |
|--------|--------------|
| `-o FILE.pdf` | Saves the report somewhere else, e.g. `-o ~/money/Relatorio_Gastos_Novembro_2026.pdf` |
| `--list` | Doesn't create a PDF. Prints every transaction with its category, so you can check the classification. |

You can run it from any folder (`~/42_Lisboa/personal/webable/create_relatorio extracto.pdf`). For a short command, add an alias to `~/.bashrc`:
`alias create_relatorio=~/42_Lisboa/personal/webable/create_relatorio`

### Requirements

- **Python packages:** `reportlab`, `matplotlib` and `pypdf`. They're already in `.venv`, and the `create_relatorio` wrapper uses `.venv/bin/python` automatically. If `.venv` is missing, run `make install`, or `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`.
- **Optional:** `pdftotext` (package `poppler` on Arch, `poppler-utils` on Debian/Ubuntu). If it isn't installed, the script falls back to `pypdf`, and both give the same result.

### Files

| File | What |
|------|------|
| `create_relatorio` | Small bash wrapper that picks the right Python and runs the script |
| `scripts/create_relatorio.py` | All the logic, in one file, split into 6 numbered sections (search for `SECÇÃO`) |

### How the numbers are calculated

- **Debit or credit** is worked out from the running balance, not from the column position. If `previous balance − amount = new balance`, it's a debit.
- **Gastos reais** are all debits *except* Revolut investments and family help.
- **Investido (Revolut)** is the total of `AFT VISA Revolut` debits minus the `IPS/...-VINICIUS VAZ CA` credits (money you sent back to yourself). Those credits are shown in red and are **not** counted as income.
- **Ajuda familiar** is any `Trf ...` debit to `JESLIN`.
- **Entradas** are grouped into: salaries (`ORDENADOS -CAPGEMINI` + `REAL VIDA`, `ORDENADOS -IEFP`), insurance refunds (`SEGUROS`), Jeslin, friends (other `IPS/...` credits) and "Outras entradas".
- **Saídas líquidas** = gastos reais + net investment + family help. The percentages in "Resumo" are of this total.

### Fixing things (most common first)

All of these are edits to the top of `scripts/create_relatorio.py` (**SECÇÃO 1 — CONFIGURAÇÃO**). You don't have to touch the rest.

| Problem | Fix |
|---------|-----|
| A shop shows up as **"Outros (por identificar)"** | Add a word from its name to the right category in `CATEGORY_RULES`. For example, to make `COMPRA MAESTRO DA L 4446629/98` restaurant spending, add `"MAESTRO"` to the `"Restauração"` list. Rules are checked top to bottom, and the first match wins. Use `--list` to check. |
| A shop is in the **wrong category** | Find which word matched it in `CATEGORY_RULES` (an earlier category wins). Make that word more specific, or move your rule above it. |
| You want a **new category** | Add a new `("Nome da categoria", ["WORD1", "WORD2"])` line to `CATEGORY_RULES`. The tables and charts pick it up automatically. |
| A shop name **looks ugly** in the report | Add a `(regex, "NICE NAME")` line to `DISPLAY_ALIASES`, e.g. `(r"^KIBO.*", "KIBO SUSHI")`. |
| **New job or salary** source | Add a line to `SALARY_SOURCES`: `("ORDENADOS -NEWCOMPANY", "NewCompany", "Salário — NewCompany")`. Copy the text exactly as it appears in the statement. |
| Your **name, family member or investment account** changed | Edit `OWNER_MATCH` / `OWNER_FULL_NAME`, `FAMILY_MATCH` / `FAMILY_FULL_NAME` / `FAMILY_SHORT`, or `INVEST_MATCH`. |
| `ERRO: não encontrei 'EXTRACTO Nº ... Período ...'` | The PDF isn't a Crédito Agrícola Extracto Integrado, or the bank changed the header. Run `pdftotext -layout extracto.pdf - \| head -60` to see the text, then fix the `re.search(r"EXTRACTO N...` line in `parse_statement()` (SECÇÃO 2). |
| `ERRO: nenhum movimento encontrado` | The transaction lines changed format. Each line must look like `DD-MM-YY  DD-MM-YY  DESCRIPTION  AMOUNT  BALANCE`. Compare the `pdftotext -layout` output with the `TX_RE` regex in SECÇÃO 2. |
| `AVISO: saldo não bate na linha: ...` | A line was read wrong, often because a description contains a number formatted like money. Look at that line in `pdftotext -layout` output. The report is still generated, but check that line's category with `--list`. |
| Text or spacing looks different | Colours are in SECÇÃO 1 (`C_TEXT`, `C_BLUE`, …). Fonts, sizes and spacing are in SECÇÃO 6 (`sty = {...}`). Charts are in SECÇÃO 5. |
| `ModuleNotFoundError: reportlab` / `matplotlib` | The wrapper didn't find `.venv`. Run `make install`, or `.venv/bin/pip install -r requirements.txt`. |

### Differences from the older reports

The script reproduces the layout, numbers and text of the August–October 2026 reports. The only intentional differences are:
- Shop names are always cleaned the same way (`COMPRA BOLT` rather than `COMPRA BOLT EU D 26`), as in the October report.
- **Observações** always follows the same template as August and September: restaurants, Bolt, health, cash withdrawals, unidentified purchases, bank fees, minimum and maximum balance. The October observations were written by hand.
- The "Por identificar" note says to add the shop to `CATEGORY_RULES`, instead of "diz-me e eu recategorizo".

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
scripts/          install, backup, migrate and update scripts, create_relatorio.py
create_relatorio  terminal spending report from a bank statement (see above)
docs/             static GitHub Pages install page (no backend, no data)
Windows_Testing/  Windows desktop build without Docker (see its README)
data/             your data, created on first run (not in git)
webapp.py         ASGI entry point
```

Prebuilt Docker images, Watchtower auto-updates, in-app updates and release steps are all in **[DEPLOYMENT.md](DEPLOYMENT.md)**.

---

## Security

Webable is built for **your own machine or a trusted home network**. Don't put it on the public internet without a reverse proxy, HTTPS and strong passwords, and never commit `data/` or real bank exports to a repository.
