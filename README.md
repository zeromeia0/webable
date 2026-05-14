# Webable

A new web application built in a **separate directory** that preserves your original CLI project files untouched.

## What was preserved

The original scripts and databases were copied into this directory exactly:

- `run.sh`
- `iefp.sh`
- `budget.py`
- `iefp_budget.py`
- `funds.py`
- `financas.db`
- `iefp_bolsas.db`

## New architecture

- FastAPI backend + Jinja2 UI
- SQLAlchemy app database for users/instances/job logs
- Per-user authentication (register/login/logout/session cookie)
- Per-user isolated database instances
- Instance-level operations for:
  - incomes
  - expenses
  - one-off transactions
  - absences
  - month calculations
  - long-range projections
- Job history with status and logs

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn webapp:app --reload
```

Open: <http://127.0.0.1:8000>
