import csv
import io
import json
import logging
import os
from datetime import date, datetime
from urllib import request as urlrequest
from urllib.error import URLError
from uuid import uuid4

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.orm import Session

from .auth import SESSION_COOKIE, current_user, hash_password, issue_session, verify_password
from .db import DATA_ROOT, Base, SessionLocal, engine, get_db
from .models import BankStatement, CategoryBudget, DatabaseInstance, FinanceAuditLog, JobRun, MotherInsightEvent, User
from .services import (
    analysis_service,
    bank_statement_service,
    build_info,
    currency_service,
    dashboard_metrics,
    db_safety,
    emergency_fund_service,
    instance_service,
    notes_service,
    wishlist_service,
    investment_pdf,
    market_chart_service,
    market_data_service,
    projection_finance,
    projection_pdf,
    reports_pdf,
    safe_updater,
    savings_pdf,
    spending_report,
    update_orchestration,
    update_service,
)

log = logging.getLogger("webable")


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    import threading

    currency_service.ensure_fresh_rates(ROOT)
    threading.Thread(target=currency_service.maintenance_loop, args=(ROOT,), daemon=True).start()
    threading.Thread(target=market_data_service.maintenance_loop, args=(ROOT, SessionLocal), daemon=True).start()
    db0 = SessionLocal()
    try:
        market_data_service.refresh_if_stale(db0, ROOT)
    except Exception as exc:
        log.warning("initial market refresh failed: %s", exc)
    finally:
        db0.close()
    update_service.refresh_cache_background()
    yield


app = FastAPI(title="Webable", version="1.0.0", lifespan=_lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

Base.metadata.create_all(bind=engine)
ROOT = DATA_ROOT


def ensure_schema_updates():
    """Backward-compatible alias; prefer db_safety.migrate_app_schema."""
    db_safety.migrate_app_schema(engine)


def seed_users():
    db = next(get_db())
    try:
        legacy = db.query(User).filter(User.username == "vvazzs").first()
        if not legacy:
            legacy = User(
                username="vvazzs",
                password_hash=hash_password(os.getenv("WEBABLE_VVAZZS_PASSWORD", "ChangeMe_vvazzs!")),
                enable_iefp_mode=True,
            )
            db.add(legacy)

        tester = db.query(User).filter(User.username == "insanecoderbr06@gmail.com").first()
        if not tester:
            tester = User(
                username="insanecoderbr06@gmail.com",
                password_hash=hash_password(os.getenv("WEBABLE_TEST_PASSWORD", "ChangeMe_insane!")),
                enable_iefp_mode=False,
            )
            db.add(tester)

        db.commit()
    finally:
        db.close()


def slugify(name: str) -> str:
    return "".join(c.lower() if c.isalnum() else "_" for c in name).strip("_") or "db"


def money(value: float) -> str:
    return f"EUR {float(value):,.2f}"


def humanize_delta(dt: datetime | None) -> str:
    if not dt:
        return "Never"
    delta = datetime.utcnow() - dt
    s = int(delta.total_seconds())
    if s < 60:
        return f"{s}s ago"
    if s < 3600:
        return f"{s // 60}m ago"
    if s < 86400:
        return f"{s // 3600}h ago"
    return f"{s // 86400}d ago"


def require_user(request: Request, db: Session) -> User:
    user = current_user(request, db)
    if not user:
        raise HTTPException(status_code=401)
    return user


def require_instance(db: Session, user: User, instance_id: int) -> DatabaseInstance:
    inst = db.query(DatabaseInstance).filter(DatabaseInstance.id == instance_id, DatabaseInstance.owner_id == user.id).first()
    if not inst:
        raise HTTPException(status_code=404)
    return inst


def load_completed_range_projection(db: Session, user: User, instance_id: int, job_id: int) -> tuple[DatabaseInstance, JobRun, list[dict]]:
    inst = require_instance(db, user, instance_id)
    job = db.query(JobRun).filter(JobRun.id == job_id, JobRun.instance_id == inst.id).first()
    if not job or job.job_type != "calculate_range" or job.status != "done":
        raise HTTPException(status_code=404, detail="Projection job not found or not completed.")
    rows = projection_finance.parse_projection_rows(parse_metrics(job.metrics_json))
    if not rows:
        raise HTTPException(status_code=404, detail="No valid projection series for this job.")
    return inst, job, rows


def load_latest_completed_range_projection(db: Session, user: User, instance_id: int) -> tuple[DatabaseInstance, JobRun, list[dict]]:
    inst = require_instance(db, user, instance_id)
    job = (
        db.query(JobRun)
        .filter(
            JobRun.instance_id == inst.id,
            JobRun.job_type == "calculate_range",
            JobRun.status == "done",
        )
        .order_by(JobRun.started_at.desc())
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="No completed long-range projection found for this workspace.")
    rows = projection_finance.parse_projection_rows(parse_metrics(job.metrics_json))
    if not rows:
        raise HTTPException(status_code=404, detail="No valid projection series for this job.")
    return inst, job, rows


def reports_range_label(preset: str | None, start_d: date | None, end_d: date | None) -> str:
    if start_d and end_d:
        return f"{start_d.isoformat()} — {end_d.isoformat()}"
    if preset and str(preset).strip():
        p = str(preset).replace("_", " ").strip()
        return p[:1].upper() + p[1:] if p else "Preset range"
    return "All time"


def pdf_currency_context(display_currency: str | None) -> tuple[str, dict[str, float], str | None]:
    currency_service.ensure_fresh_rates(ROOT)
    st = currency_service.rates_public_dict(ROOT)
    cur = currency_service.normalize_currency(display_currency)
    rates = {k: float(v) for k, v in (st.get("rates") or {}).items()}
    return cur, rates, st.get("updated_at")


def build_monthly_output(metrics: dict, show_iefp: bool) -> dict:
    savings = float(metrics.get("estimated_savings", 0))
    income_items = metrics.get("income_items") or []
    expense_items = metrics.get("expense_items") or []
    recurring_inc = float(metrics.get("extras", 0))
    recurring_exp = float(metrics.get("expenses", 0))
    oneoff_inc = float(metrics.get("oneoff_income_total", 0))
    oneoff_exp = float(metrics.get("oneoff_expense_total", 0))
    iefp_v = float(metrics.get("iefp", 0))
    total_in = float(metrics.get("total_before_expenses", 0))
    month_key = str(metrics.get("month", ""))

    income_lines = [
        f"{i['name']}: {money(i['amount'])}/month · {i.get('recurrence', 'monthly')}"
        for i in income_items
    ] or ["No recurring income added yet."]
    expense_lines = [
        f"{i['name']}: {money(i['amount'])}/month · {i.get('recurrence', 'monthly')}"
        for i in expense_items
    ] or ["No recurring expenses added yet."]

    if show_iefp and iefp_v > 0:
        income_lines.insert(0, f"Legacy IEFP income (this month): {money(iefp_v)}")

    oneoff_rows = []
    for o in metrics.get("oneoff_transactions") or []:
        amt = abs(float(o.get("amount") or 0))
        is_inc = str(o.get("txn_type", "expense")).lower() == "income"
        signed = amt if is_inc else -amt
        oneoff_rows.append(
            {
                "date": str(o.get("date", "")),
                "description": str(o.get("name", "")),
                "category": str(o.get("category", "")),
                "signed_eur": round(signed, 2),
                "txn_type": "income" if is_inc else "expense",
            }
        )

    month_breakdown = {
        "month": month_key,
        "recurring_income": [
            {"name": i["name"], "amount_eur": round(float(i["amount"]), 2), "recurrence": i.get("recurrence", "monthly")}
            for i in income_items
        ],
        "recurring_expense": [
            {"name": i["name"], "amount_eur": round(float(i["amount"]), 2), "recurrence": i.get("recurrence", "monthly")}
            for i in expense_items
        ],
        "oneoff_rows": oneoff_rows,
    }

    oneoff_net = float(metrics.get("oneoff_net", oneoff_inc - oneoff_exp))

    return {
        "cards": [
            {
                "label": "Estimated net savings",
                "value": money(savings),
                "value_eur": round(savings, 2),
                "tone": "positive" if savings >= 0 else "negative",
            },
            {
                "label": "Total inflows (month)",
                "value": money(total_in),
                "value_eur": round(total_in, 2),
                "tone": "info",
            },
            {
                "label": "Recurring expenses",
                "value": money(recurring_exp),
                "value_eur": round(recurring_exp, 2),
                "tone": "negative",
            },
            {
                "label": "One-time income (month)",
                "value": money(oneoff_inc),
                "value_eur": round(oneoff_inc, 2),
                "tone": "positive",
            },
            {
                "label": "One-time expenses (month)",
                "value": money(oneoff_exp),
                "value_eur": round(oneoff_exp, 2),
                "tone": "negative",
            },
            {
                "label": "One-time net (income − expenses)",
                "value": money(oneoff_net),
                "value_eur": round(oneoff_net, 2),
                "tone": "positive" if oneoff_net >= 0 else "negative",
            },
        ],
        "sections": [
            {"title": "Recurring income", "items": income_lines},
            {"title": "Recurring expenses", "items": expense_lines},
            {
                "title": "One-time transactions (" + month_key + ")",
                "items": [
                    f"{r['date']} · {r['description']} · {r['category']} · "
                    + (money(r["signed_eur"]) if r["signed_eur"] >= 0 else "(" + money(abs(r["signed_eur"])) + ")")
                    for r in oneoff_rows
                ]
                or ["No one-time transactions in this month."],
            },
            {
                "title": "Net result",
                "items": [
                    ("Positive month" if savings >= 0 else "Negative month") + f" — net savings {money(savings)}",
                    f"Recurring income: {money(recurring_inc)} · One-time income: {money(oneoff_inc)}",
                    f"Recurring expenses: {money(recurring_exp)} · One-time expenses: {money(oneoff_exp)}",
                ],
            },
        ],
        "bars": [],
        "month_breakdown": month_breakdown,
        "recommendation": "Great month. Keep building savings." if savings >= 0 else "Review recurring and one-time spending to improve your monthly balance.",
    }


def build_projection_output(rows: list[dict]) -> dict:
    if not rows:
        return {"cards": [], "sections": [], "bars": [], "recommendation": "Run a projection to see long-term trends."}
    savings = [float(r.get("estimated_savings", 0)) for r in rows]
    months = [r.get("month", "-") for r in rows]
    acc = float(rows[-1].get("accumulated", 0))
    best = max(range(len(savings)), key=lambda i: savings[i])
    worst = min(range(len(savings)), key=lambda i: savings[i])
    mx = max([abs(v) for v in savings], default=1) or 1
    bars = [
        {
            "label": months[i],
            "value": money(savings[i]),
            "value_eur": round(float(savings[i]), 2),
            "pct": max(8, int((abs(savings[i]) / mx) * 100)),
            "tone": "positive" if savings[i] >= 0 else "negative",
        }
        for i in range(len(rows))
    ]

    return {
        "cards": [
            {"label": "Projected Accumulated Savings", "value": money(acc), "value_eur": round(acc, 2), "tone": "positive" if acc >= 0 else "negative"},
            {
                "label": "Best Month",
                "value": f"{months[best]} ({money(savings[best])})",
                "value_eur": round(float(savings[best]), 2),
                "value_note": str(months[best]),
                "tone": "positive",
            },
            {
                "label": "Worst Month",
                "value": f"{months[worst]} ({money(savings[worst])})",
                "value_eur": round(float(savings[worst]), 2),
                "value_note": str(months[worst]),
                "tone": "negative",
            },
        ],
        "sections": [
            {"title": "Projection Highlights", "items": [f"Months analyzed: {len(rows)}", f"Positive months: {len([v for v in savings if v >= 0])}", f"Negative months: {len([v for v in savings if v < 0])}"]},
        ],
        "bars": bars,
        "recommendation": "Your long-term trend is positive." if acc >= 0 else "Your long-term trend is negative. Lower recurring expenses.",
    }


def parse_metrics(raw: str):
    try:
        return json.loads(raw or "{}")
    except Exception:
        return {}


def human_job_view(job: JobRun, show_iefp: bool) -> dict:
    status = "Success" if job.status == "done" else "Needs attention"
    badge_class = "bg-emerald-500/20 text-emerald-300 border-emerald-500/40" if job.status == "done" else "bg-amber-500/20 text-amber-300 border-amber-500/40"
    metrics = parse_metrics(job.metrics_json)
    details = {"cards": [], "sections": [], "bars": [], "recommendation": "Everything looks good."}
    projection_series: list[dict] | None = None

    if isinstance(metrics, dict) and "month" in metrics and "estimated_savings" in metrics:
        details = build_monthly_output(metrics, show_iefp)
    elif isinstance(metrics, list):
        rows = [r for r in metrics if isinstance(r, dict)]
        details = build_projection_output(rows)
        if rows and all("month" in r and "accumulated" in r for r in rows):
            projection_series = []
            for r in rows:
                if not isinstance(r, dict):
                    continue
                projection_series.append(
                    {
                        "month": r.get("month"),
                        "accumulated": float(r.get("accumulated", 0) or 0),
                        "estimated_savings": float(r.get("estimated_savings", 0) or 0),
                        "total_before_expenses": float(r.get("total_before_expenses", 0) or 0),
                        "expenses": float(r.get("expenses", 0) or 0),
                    }
                )
    elif isinstance(metrics, dict) and "entry" in metrics:
        amount = float(metrics.get("amount", 0))
        details = {
            "cards": [{"label": "Transaction Amount", "value": money(amount), "tone": "positive" if amount >= 0 else "negative"}],
            "sections": [{"title": "Transaction Details", "items": [f"Name: {metrics.get('entry', '-')}", f"Amount: {money(amount)}", f"Date: {metrics.get('date', 'Today')}"]}],
            "bars": [],
            "recommendation": "Keep your entries categorized for clearer monthly analysis.",
        }

    return {
        "id": job.id,
        "job_type": job.job_type,
        "icon": "✅" if job.status == "done" else "⚠️",
        "badge": status,
        "badge_class": badge_class,
        "title": job.friendly_message,
        "subtitle": f"{job.job_type.replace('_', ' ').title()} - {humanize_delta(job.started_at)}",
        "duration": f"{job.duration_ms} ms" if job.duration_ms else None,
        "technical_logs": job.technical_logs,
        "projection_series": projection_series,
        **details,
    }


def build_mother_output(
    intelligence: dict,
    jobs: list[JobRun],
    metadata: dict,
    instances: list[DatabaseInstance] | None = None,
    month_totals: dict | None = None,
) -> dict:
    savings = []
    for job in jobs:
        m = parse_metrics(job.metrics_json)
        if isinstance(m, dict) and "estimated_savings" in m:
            savings.append(float(m["estimated_savings"]))
    avg = (sum(savings) / len(savings)) if savings else 0.0
    income_entries: list[dict] = []
    expense_entries: list[dict] = []
    for ins in instances or []:
        items = instance_service.list_finance_items(ins.finance_db_path)
        for row in items["incomes"]:
            if row.get("ended"):
                continue
            income_entries.append(
                {
                    "name": str(row["name"]),
                    "amount_eur": round(float(row["amount"]), 2),
                    "workspace": ins.name if len(instances or []) > 1 else None,
                }
            )
        for row in items["expenses"]:
            if row.get("ended"):
                continue
            expense_entries.append(
                {
                    "name": str(row["name"]),
                    "amount_eur": round(float(row["amount"]), 2),
                    "workspace": ins.name if len(instances or []) > 1 else None,
                }
            )
    income_entries.sort(key=lambda x: x["amount_eur"], reverse=True)
    expense_entries.sort(key=lambda x: x["amount_eur"], reverse=True)
    recurring_income_total = round(sum(e["amount_eur"] for e in income_entries), 2)
    recurring_expense_total = round(sum(e["amount_eur"] for e in expense_entries), 2)

    mt = month_totals or {}
    month_income = float(mt.get("income_total") or recurring_income_total)
    month_expenses = float(mt.get("expense_total") or recurring_expense_total)
    fixed_total = float(mt.get("fixed_expenses_total") or recurring_expense_total)
    current_balance = float(mt.get("current_month_balance") or dashboard_metrics.current_month_balance(month_income, month_expenses))

    expense_entries_enriched = [
        dashboard_metrics.enrich_expense_entry(row, recurring_expense_total, month_income) for row in expense_entries
    ]
    fixed_summary = dashboard_metrics.fixed_expenses_summary(fixed_total, month_income)
    if fixed_summary.get("pct_of_income"):
        fixed_summary["line"] = f"Fixed expenses: {money(fixed_summary['amount_eur'])} — {fixed_summary['pct_of_income']}% of income"
    else:
        fixed_summary["line"] = f"Fixed expenses: {money(fixed_summary['amount_eur'])} — income unavailable"
    expense_income_pct = dashboard_metrics.format_pct_of_total(recurring_expense_total, month_income)
    if expense_income_pct:
        expenses_summary_line = f"Total expenses: {money(recurring_expense_total)} — {expense_income_pct}% of income"
    else:
        expenses_summary_line = f"Total expenses: {money(recurring_expense_total)} — income unavailable"

    return {
        "headline": "Your financial activity is healthy and consistent." if avg >= 0 else "Your financial balance needs attention.",
        "cards": [
            {
                "label": "Average Monthly Balance",
                "value": money(avg),
                "value_eur": round(avg, 2),
                "tone": "purple",
            },
            {
                "label": "Current Month Balance",
                "value": money(current_balance),
                "value_eur": round(current_balance, 2),
                "tone": "positive" if current_balance >= 0 else "negative",
            },
            {"label": "Income Entries", "value": str(len(income_entries)), "tone": "info"},
            {"label": "Expense Entries", "value": str(len(expense_entries)), "tone": "negative"},
        ],
        "income_entries": income_entries,
        "expense_entries": expense_entries_enriched,
        "income_entries_total_eur": recurring_income_total,
        "expense_entries_total_eur": recurring_expense_total,
        "fixed_expenses_summary": fixed_summary,
        "expenses_summary_line": expenses_summary_line,
        "month_income_total_eur": round(month_income, 2),
        "month_expense_total_eur": round(month_expenses, 2),
        "sections": [
            {"title": "Insights", "items": [f"Execution success rate: {intelligence['success_rate']}%", f"Tracked financial items: {intelligence['total_data_points']}"]},
            {"title": "Recommendations", "items": ["Track expenses every week.", "Run monthly projections often.", "Use AI assistant for planning advice."]},
        ],
    }


def collect_user_financial_context(db: Session, user: User, instance_id: int | None = None) -> dict:
    instances_q = db.query(DatabaseInstance).filter(DatabaseInstance.owner_id == user.id)
    if instance_id is not None:
        instances_q = instances_q.filter(DatabaseInstance.id == instance_id)
    instances = instances_q.order_by(DatabaseInstance.created_at.desc()).all()

    current_month = datetime.utcnow().strftime("%Y-%m")
    workspaces = []
    trend = []
    for ins in instances:
        items = instance_service.list_finance_items(ins.finance_db_path)
        month = instance_service.month_summary(
            ins.finance_db_path,
            ins.logic_db_path,
            current_month,
            include_iefp=bool(user.enable_iefp_mode),
        )
        projection = instance_service.long_range(
            ins.finance_db_path,
            ins.logic_db_path,
            current_month,
            6,
            include_iefp=bool(user.enable_iefp_mode),
        )
        trend.extend(projection)
        workspaces.append(
            {
                "workspace": ins.name,
                "totals": {
                    "income": round(sum(i["amount"] for i in items["incomes"]), 2),
                    "expenses": round(sum(i["amount"] for i in items["expenses"]), 2),
                    "one_time": round(sum(i["amount"] for i in items["oneoffs"]), 2),
                    "monthly_savings_estimate": month.get("estimated_savings", 0),
                },
                "incomes": [{"name": i["name"], "amount": i["amount"]} for i in items["incomes"][:20]],
                "expenses": [{"name": i["name"], "amount": i["amount"]} for i in items["expenses"][:20]],
                "one_time_transactions": [{"date": t["date"], "name": t["name"], "amount": t["amount"], "category": t.get("category", "Other"), "txn_type": t.get("txn_type", "expense")} for t in items["oneoffs"][:20]],
                "current_month": month,
                "projection_6m": projection,
            }
        )

    return {
        "user": user.username,
        "current_month": current_month,
        "workspaces": workspaces,
        "trend_points": trend[:24],
    }


def dashboard_intelligence(instances: list[DatabaseInstance], jobs: list[JobRun], metadata: dict) -> dict:
    total_runs = len(jobs)
    successful = len([j for j in jobs if j.status == "done"])
    last_update = jobs[0].started_at if jobs else None
    total_data_points = sum(v.get("incomes", 0) + v.get("expenses", 0) + v.get("oneoffs", 0) for v in metadata.values())
    return {
        "total_instances": len(instances),
        "success_rate": round((successful / total_runs) * 100, 1) if total_runs else 0,
        "last_update": humanize_delta(last_update),
        "total_data_points": total_data_points,
    }


def build_dashboard_chart_data(db: Session, user: User, instances: list[DatabaseInstance]) -> dict:
    current_month = datetime.utcnow().strftime("%Y-%m")
    income_total = 0.0
    expense_total = 0.0
    savings_total = 0.0
    by_workspace_labels = []
    by_workspace_income = []
    by_workspace_expenses = []
    monthly_labels = []
    monthly_savings = []

    for ins in instances:
        items = instance_service.list_finance_items(ins.finance_db_path)
        income = sum(i["amount"] for i in items["incomes"])
        expenses = sum(i["amount"] for i in items["expenses"])
        month = instance_service.month_summary(
            ins.finance_db_path,
            ins.logic_db_path,
            current_month,
            include_iefp=bool(user.enable_iefp_mode),
        )
        income_total += income
        expense_total += expenses
        savings_total += month.get("estimated_savings", 0)
        by_workspace_labels.append(ins.name)
        by_workspace_income.append(round(income, 2))
        by_workspace_expenses.append(round(expenses, 2))

    if instances:
        primary = instances[0]
        range_6 = instance_service.long_range(
            primary.finance_db_path,
            primary.logic_db_path,
            current_month,
            6,
            include_iefp=bool(user.enable_iefp_mode),
        )
        monthly_labels = [row["month"] for row in range_6]
        monthly_savings = [row["estimated_savings"] for row in range_6]

    growth = 0.0
    if len(monthly_savings) >= 2 and monthly_savings[0] != 0:
        growth = round(((monthly_savings[-1] - monthly_savings[0]) / abs(monthly_savings[0])) * 100, 1)

    return {
        "income_total": round(income_total, 2),
        "expense_total": round(expense_total, 2),
        "savings_total": round(savings_total, 2),
        "current_month_savings": round(savings_total, 2),
        "growth_percent": growth,
        "workspace_labels": by_workspace_labels,
        "workspace_income": by_workspace_income,
        "workspace_expenses": by_workspace_expenses,
        "monthly_labels": monthly_labels,
        "monthly_savings": monthly_savings,
    }


def build_ai_context(user: User, instance: DatabaseInstance, finance_items: dict, latest_month: dict, latest_range: list[dict]) -> dict:
    total_income = round(sum(item.get("amount", 0) for item in finance_items.get("incomes", [])), 2)
    total_expenses = round(sum(item.get("amount", 0) for item in finance_items.get("expenses", [])), 2)
    total_oneoffs = round(sum(item.get("amount", 0) for item in finance_items.get("oneoffs", [])), 2)
    return {
        "user": user.username,
        "workspace": instance.name,
        "totals": {
            "total_income": total_income,
            "total_expenses": total_expenses,
            "total_one_time_transactions": total_oneoffs,
            "current_month_estimated_savings": latest_month.get("estimated_savings", 0),
        },
        "incomes": [{"name": i.get("name"), "amount": i.get("amount")} for i in finance_items.get("incomes", [])],
        "expenses": [{"name": i.get("name"), "amount": i.get("amount")} for i in finance_items.get("expenses", [])],
        "one_time_transactions": [{"date": t.get("date"), "name": t.get("name"), "amount": t.get("amount"), "category": t.get("category", "Other"), "txn_type": t.get("txn_type", "expense")} for t in finance_items.get("oneoffs", [])],
        "monthly_result": {
            "month": latest_month.get("month"),
            "income_total": latest_month.get("extras", 0),
            "expense_total": latest_month.get("expenses", 0),
            "one_time_total": latest_month.get("one_off", 0),
            "savings_estimate": latest_month.get("estimated_savings", 0),
        },
        "projection": latest_range[:12],
    }


def ask_ollama(question: str, context: dict) -> str:
    context_block = json.dumps(context, ensure_ascii=False, indent=2)[:14000]
    system_prompt = (
        "You are a helpful personal finance assistant inside a budgeting web app.\n\n"
        "Your job is to explain the user's financial situation in simple, practical language.\n"
        "Use only the financial data provided in the context.\n"
        "Do not invent numbers.\n"
        "Do not mention databases, JSON, backend, SQL, code, or internal systems.\n"
        "If something is missing, say the app does not have enough information.\n\n"
        "Always answer with:\n"
        "- a short direct summary\n"
        "- clear bullet points\n"
        "- useful observations\n"
        "- practical next steps when relevant\n\n"
        "Keep the tone friendly, simple, and easy to understand."
    )
    payload = {
        "model": "qwen2.5-coder:3b",
        "stream": False,
        "prompt": f"{system_prompt}\n\nFinancial context:\n{context_block}\n\nUser question:\n{question}",
    }
    req = urlrequest.Request(
        "http://127.0.0.1:11434/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=90) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body.get("response", "I could not generate a response.").strip()
    except URLError:
        return "I couldn't connect to the local AI assistant. Make sure Ollama is running and the qwen2.5-coder:3b model is installed."


def render_ai_answer(answer: str) -> str:
    cleaned = (answer or "").strip()
    if not cleaned:
        return "- I could not generate a useful answer this time."
    if cleaned.startswith("{") and cleaned.endswith("}"):
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict) and "answer" in parsed:
                cleaned = str(parsed["answer"]).strip()
        except Exception:
            pass
    return cleaned


def _append_finance_audit(db: Session, user_id: int, instance_id: int, job_type: str, result: object) -> None:
    if not isinstance(result, dict):
        return
    entity, action, eid = "unknown", "unknown", None
    if job_type == "add_oneoff" and result.get("id") is not None:
        entity, action, eid = "oneoff", "created", int(result["id"])
    elif job_type == "delete_oneoff":
        entity, action = "oneoff", "deleted"
    elif job_type == "add_income" and result.get("id") is not None:
        entity, action, eid = "income", "created", int(result["id"])
    elif job_type == "add_expense" and result.get("id") is not None:
        entity, action, eid = "expense", "created", int(result["id"])
    elif job_type == "delete_income":
        entity, action = "income", "deleted"
    elif job_type == "delete_expense":
        entity, action = "expense", "deleted"
    else:
        return
    db.add(
        FinanceAuditLog(
            instance_id=instance_id,
            user_id=user_id,
            entity_type=entity,
            entity_id=eid,
            action=action,
            details=json.dumps(result, default=str)[:4000],
        )
    )


def run_job(db: Session, user: User, inst: DatabaseInstance, job_type: str, callback):
    labels = {
        "create_instance": "Database created successfully",
        "add_income": "Income entry saved",
        "add_expense": "Expense entry saved",
        "add_oneoff": "One-time transaction saved",
        "add_absence": "Absence registered",
        "calculate_month": "Monthly projection completed",
        "calculate_range": "Long-range projection completed",
        "delete_income": "Income deleted successfully",
        "delete_expense": "Expense deleted successfully",
        "delete_oneoff": "Transaction deleted successfully",
        "ai_chat": "AI assistant response ready",
    }
    job = JobRun(instance_id=inst.id, job_type=job_type, status="running", logs="Execution started.", friendly_message="Processing", technical_logs="", metrics_json="{}")
    db.add(job)
    db.commit()
    db.refresh(job)
    started = datetime.utcnow()
    try:
        result = callback()
        job.status = "done"
        job.friendly_message = labels.get(job_type, "Processing completed")
        job.logs = job.friendly_message
        job.technical_logs = json.dumps(result, indent=2, ensure_ascii=False, default=str) if isinstance(result, (dict, list)) else str(result)
        job.metrics_json = json.dumps(result, default=str)
        inst.last_sync_status = job.friendly_message
        inst.health_status = "healthy"
        try:
            _append_finance_audit(db, user.id, inst.id, job_type, result)
        except Exception:
            log.exception("audit log append failed for %s", job_type)
    except Exception as exc:
        job.status = "failed"
        job.friendly_message = "Execution failed"
        job.logs = job.friendly_message
        job.technical_logs = f"{type(exc).__name__}: {exc}"
        inst.last_sync_status = "Execution failed"
        inst.health_status = "warning"
    job.finished_at = datetime.utcnow()
    job.duration_ms = int((job.finished_at - started).total_seconds() * 1000)
    inst.last_activity_at = job.finished_at
    db.add(job)
    db.add(inst)
    db.add(MotherInsightEvent(owner_id=user.id, instance_id=inst.id, event_type=job_type, severity="success" if job.status == "done" else "warning", title=job.friendly_message, details=f"{inst.name}: {job_type}"))
    db.commit()
    return job


db_safety.run_safe_startup_migrations(engine)
seed_users()


@app.get("/api/currency/rates")
def api_currency_rates():
    currency_service.ensure_fresh_rates(ROOT)
    return JSONResponse(currency_service.rates_public_dict(ROOT))


@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user:
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={"request": request, "show_back_to_dashboard": False},
    )


@app.post("/register")
def register(username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == username.strip()).first():
        return RedirectResponse("/?err=user_exists", status_code=302)
    user = User(username=username.strip(), password_hash=hash_password(password), enable_iefp_mode=False)
    db.add(user)
    db.commit()
    db.refresh(user)
    resp = RedirectResponse("/dashboard", status_code=302)
    resp.set_cookie(SESSION_COOKIE, issue_session(user), httponly=True, samesite="lax")
    return resp


@app.post("/login")
def login(username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username.strip()).first()
    if not user or not verify_password(password, user.password_hash):
        return RedirectResponse("/?err=invalid_login", status_code=302)
    resp = RedirectResponse("/dashboard", status_code=302)
    resp.set_cookie(SESSION_COOKIE, issue_session(user), httponly=True, samesite="lax")
    return resp


@app.post("/logout")
def logout():
    resp = RedirectResponse("/", status_code=302)
    resp.delete_cookie(SESSION_COOKIE)
    return resp


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    instances = db.query(DatabaseInstance).filter(DatabaseInstance.owner_id == user.id).order_by(DatabaseInstance.created_at.desc()).all()
    metadata = {ins.id: instance_service.list_metadata(ins.finance_db_path, ins.logic_db_path) for ins in instances}
    jobs = db.query(JobRun).join(DatabaseInstance).filter(DatabaseInstance.owner_id == user.id).order_by(JobRun.started_at.desc()).limit(20).all()
    intelligence = dashboard_intelligence(instances, jobs, metadata)
    jobs_view = [human_job_view(job, user.enable_iefp_mode) for job in jobs]
    now_m = datetime.utcnow().strftime("%Y-%m")
    month_rows = []
    for ins in instances:
        month_rows.append(
            instance_service.month_summary(
                ins.finance_db_path,
                ins.logic_db_path,
                now_m,
                include_iefp=bool(user.enable_iefp_mode),
            )
        )
    month_totals = dashboard_metrics.aggregate_current_month_totals(month_rows) if month_rows else {}
    mother_output = build_mother_output(intelligence, jobs, metadata, instances, month_totals=month_totals)
    chart_data = build_dashboard_chart_data(db, user, instances)
    insights = db.query(MotherInsightEvent).filter(MotherInsightEvent.owner_id == user.id).order_by(MotherInsightEvent.created_at.desc()).limit(10).all()
    primary = instances[0] if instances else None
    latest_statement = None
    budget_alerts = []
    if primary:
        latest_statement = (
            db.query(BankStatement)
            .filter(BankStatement.instance_id == primary.id)
            .order_by(BankStatement.created_at.desc())
            .first()
        )
        budget_alerts = _budget_alerts(db, primary, now_m)
    return templates.TemplateResponse(request=request, name="dashboard.html", context={
        "request": request,
        "user": user,
        "instances": instances,
        "primary_instance": primary,
        "workspace_for_nav": primary,
        "nav_active": "overview",
        "metadata": metadata,
        "jobs_view": jobs_view,
        "intelligence": intelligence,
        "chart_data": chart_data,
        "mother_output": mother_output,
        "insights": insights,
        "humanize_delta": humanize_delta,
        "show_back_to_dashboard": False,
        "current_month": now_m,
        "latest_bank_statement": latest_statement,
        "budget_alerts": budget_alerts,
        "oneoff_categories": list(instance_service.ONEOFF_CATEGORIES),
    })


@app.post("/instances/create")
def create_instance(request: Request, name: str = Form(...), db: Session = Depends(get_db)):
    user = require_user(request, db)
    clean_name = name.strip()
    tmp = int(datetime.utcnow().timestamp())
    finance_path, logic_path = instance_service.instance_paths(ROOT, user.id, tmp, f"{slugify(clean_name)}_{uuid4().hex[:8]}")
    instance_service.init_finance_db(finance_path)
    instance_service.init_logic_db(logic_path)
    inst = DatabaseInstance(owner_id=user.id, name=clean_name, mode="general", finance_db_path=finance_path, logic_db_path=logic_path, last_sync_status="Database created successfully", last_activity_at=datetime.utcnow())
    db.add(inst)
    db.commit()
    db.refresh(inst)
    db.add(MotherInsightEvent(owner_id=user.id, instance_id=inst.id, event_type="create_instance", severity="success", title="Database created successfully", details=f"Workspace '{inst.name}' is ready."))
    db.commit()
    return RedirectResponse("/dashboard", status_code=302)


@app.post("/instances/{instance_id}/delete")
def delete_instance(instance_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id)
    inst_name = inst.name
    for st in db.query(BankStatement).filter(BankStatement.instance_id == inst.id).all():
        fp = ROOT / st.storage_rel_path
        try:
            if fp.is_file():
                fp.unlink()
        except OSError:
            log.warning("could not remove statement file %s", fp)
    for p in [inst.finance_db_path, inst.logic_db_path]:
        if p and os.path.exists(p):
            os.remove(p)
    db.delete(inst)
    db.commit()
    db.add(MotherInsightEvent(owner_id=user.id, instance_id=None, event_type="delete_instance", severity="info", title="Database removed successfully", details=f"Workspace '{inst_name}' was deleted."))
    db.commit()
    return RedirectResponse("/dashboard", status_code=302)


def _category_spend_month(finance_db: str, month_prefix: str) -> dict[str, float]:
    items = instance_service.list_finance_items(finance_db)
    out: dict[str, float] = {}
    mp = month_prefix[:7]
    for o in items["oneoffs"]:
        if str(o.get("txn_type", "")).lower() == "income":
            continue
        if not str(o.get("date", "")).startswith(mp):
            continue
        c = str(o.get("category") or "Other")
        out[c] = out.get(c, 0.0) + abs(float(o.get("amount", 0)))
    return out


def _budget_alerts(db: Session, inst: DatabaseInstance, month_prefix: str) -> list[dict]:
    spent = _category_spend_month(inst.finance_db_path, month_prefix)
    rows = db.query(CategoryBudget).filter(CategoryBudget.instance_id == inst.id).all()
    alerts: list[dict] = []
    for b in rows:
        s = spent.get(b.category, 0.0)
        lim = float(b.monthly_limit_eur)
        if lim <= 0:
            continue
        pct = (s / lim * 100.0) if lim else 0.0
        tone = "ok"
        if s > lim + 0.01:
            tone = "over"
        elif pct >= 80.0:
            tone = "warn"
        alerts.append(
            {
                "category": b.category,
                "limit": round(lim, 2),
                "spent": round(s, 2),
                "pct": round(pct, 1),
                "tone": tone,
                "budget_id": b.id,
            }
        )
    return alerts


def resolve_report_date_range(
    preset: str | None,
    start_date: str | None,
    end_date: str | None,
) -> tuple[date | None, date | None]:
    if start_date and end_date:
        try:
            s = datetime.strptime(start_date.strip()[:10], "%Y-%m-%d").date()
            e = datetime.strptime(end_date.strip()[:10], "%Y-%m-%d").date()
            if s > e:
                s, e = e, s
            return s, e
        except ValueError:
            pass
    if preset and str(preset).lower() not in ("", "custom", "none"):
        return spending_report.preset_range(str(preset))
    return None, None


def build_reports_payload(inst: DatabaseInstance) -> dict:
    items = instance_service.list_finance_items(inst.finance_db_path)
    oneoffs = items["oneoffs"]
    recurring_income = sum(float(i["amount"]) for i in items["incomes"])
    recurring_expense = sum(float(i["amount"]) for i in items["expenses"])
    bounds = spending_report.transaction_date_bounds(oneoffs)
    return {
        "instance_id": inst.id,
        "instance_name": inst.name,
        "recurring_income_monthly": recurring_income,
        "recurring_expense_monthly": recurring_expense,
        "date_bounds": {"min": bounds[0].isoformat() if bounds[0] else None, "max": bounds[1].isoformat() if bounds[1] else None},
    }


@app.get("/instances/{instance_id}/reports", response_class=HTMLResponse)
def reports_page(instance_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id)
    instances = db.query(DatabaseInstance).filter(DatabaseInstance.owner_id == user.id).order_by(DatabaseInstance.created_at.desc()).all()
    base = build_reports_payload(inst)
    statements = bank_statement_service.list_for_instance(db, inst.id)
    return templates.TemplateResponse(
        request=request,
        name="reports.html",
        context={
            "request": request,
            "user": user,
            "instance": inst,
            "instances": instances,
            "workspace_for_nav": inst,
            "nav_active": "reports",
            "report_bootstrap": base,
            "bank_statements": statements,
            "show_back_to_dashboard": True,
        },
    )


@app.get("/instances/{instance_id}/reports/data")
def reports_data(
    instance_id: int,
    request: Request,
    preset: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id)
    items = instance_service.list_finance_items(inst.finance_db_path)
    oneoffs = items["oneoffs"]
    rin = sum(float(i["amount"]) for i in items["incomes"])
    rex = sum(float(i["amount"]) for i in items["expenses"])
    start_d, end_d = resolve_report_date_range(preset, start_date, end_date)
    report = spending_report.build_spending_report(oneoffs, rin, rex, start_d, end_d)
    return JSONResponse(report)


@app.post("/instances/{instance_id}/reports/pdf")
def reports_pdf_export(
    instance_id: int,
    request: Request,
    preset: str | None = Form(None),
    start_date: str | None = Form(None),
    end_date: str | None = Form(None),
    display_currency: str | None = Form(None),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id)
    items = instance_service.list_finance_items(inst.finance_db_path)
    oneoffs = items["oneoffs"]
    rin = sum(float(i["amount"]) for i in items["incomes"])
    rex = sum(float(i["amount"]) for i in items["expenses"])
    start_d, end_d = resolve_report_date_range(preset, start_date, end_date)
    report = spending_report.build_spending_report(oneoffs, rin, rex, start_d, end_d)
    if report.get("range") and report["range"].get("start") and report["range"].get("end"):
        label = reports_range_label(None, date.fromisoformat(report["range"]["start"]), date.fromisoformat(report["range"]["end"]))
    else:
        label = reports_range_label(preset, start_d, end_d)
    cur, rates, fx_at = pdf_currency_context(display_currency)
    try:
        pdf_bytes = reports_pdf.build_reports_pdf(
            workspace_name=inst.name,
            range_label=label,
            report=report,
            display_currency=cur,
            fx_rates=rates,
            fx_updated_at=fx_at,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="PDF export needs optional packages: pip install reportlab matplotlib pypdf",
        ) from exc
    fname = f"webable-spending-report-{instance_id}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@app.get("/instances/{instance_id}/investment-calculator", response_class=HTMLResponse)
def investment_calculator_page(instance_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id)
    instances = db.query(DatabaseInstance).filter(DatabaseInstance.owner_id == user.id).order_by(DatabaseInstance.created_at.desc()).all()
    latest_range = (
        db.query(JobRun)
        .filter(
            JobRun.instance_id == inst.id,
            JobRun.job_type == "calculate_range",
            JobRun.status == "done",
        )
        .order_by(JobRun.started_at.desc())
        .first()
    )
    return templates.TemplateResponse(
        request=request,
        name="investment_calculator.html",
        context={
            "request": request,
            "user": user,
            "instance": inst,
            "instances": instances,
            "workspace_for_nav": inst,
            "nav_active": "calculator",
            "latest_projection_job_id": latest_range.id if latest_range else None,
            "show_back_to_dashboard": True,
        },
    )


@app.post("/instances/{instance_id}/investment-calculator/simulate")
async def investment_calculator_simulate(instance_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    require_instance(db, user, instance_id)
    body = await request.json()
    initial = float(body.get("initial_balance", 0) or 0)
    monthly = float(body.get("monthly_contribution", 0) or 0)
    annual = float(body.get("annual_rate_pct", 0) or 0)
    years = float(body.get("years", 1) or 1)
    n = int(body.get("compounding_per_year", 12) or 12)
    timing = str(body.get("contribution_timing", "beginning") or "beginning")
    n = max(1, min(365, n))
    years = max(0.08, min(80.0, years))
    annual = max(0.0, min(50.0, annual))
    result = projection_finance.run_investment_calculator(
        initial_balance=initial,
        monthly_contribution=monthly,
        annual_rate_pct=annual,
        years=years,
        compounding_per_year=n,
        contribution_timing=timing,
    )
    return JSONResponse(result)


@app.post("/instances/{instance_id}/investment-calculator/pdf")
async def investment_calculator_pdf_export(instance_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id)
    body = await request.json()
    initial = float(body.get("initial_balance", 0) or 0)
    monthly = float(body.get("monthly_contribution", 0) or 0)
    annual = float(body.get("annual_rate_pct", 0) or 0)
    years = float(body.get("years", 1) or 1)
    n = int(body.get("compounding_per_year", 12) or 12)
    timing = str(body.get("contribution_timing", "beginning") or "beginning")
    n = max(1, min(365, n))
    years = max(0.08, min(80.0, years))
    annual = max(0.0, min(50.0, annual))
    calc_in = {
        "initial_balance": initial,
        "monthly_contribution": monthly,
        "annual_rate_pct": annual,
        "years": years,
        "compounding_per_year": n,
        "contribution_timing": timing,
    }
    calc_result = projection_finance.run_investment_calculator(
        initial_balance=initial,
        monthly_contribution=monthly,
        annual_rate_pct=annual,
        years=years,
        compounding_per_year=n,
        contribution_timing=timing,
    )
    projection_result = None
    projection_label = None
    if bool(body.get("include_projection")):
        _inst2, _job2, rows = load_latest_completed_range_projection(db, user, instance_id)
        invest_pct = max(0.0, min(100.0, float(body.get("invest_pct", 15) or 15)))
        horizon_years = max(0.08, min(60.0, float(body.get("horizon_years", 5) or 5)))
        proj_rate = max(0.0, min(50.0, float(body.get("projection_annual_rate_pct", annual) or 0)))
        projection_result = projection_finance.run_monthly_simulation(rows, invest_pct, proj_rate, horizon_years)
        projection_label = (
            f"Latest long-range projection in this workspace · {invest_pct:g}% of monthly savings · "
            f"{horizon_years:g} yr horizon @ {proj_rate:g}% APR"
        )
    cur, rates, fx_at = pdf_currency_context(body.get("display_currency"))
    try:
        pdf_bytes = investment_pdf.build_investment_calculator_pdf(
            workspace_name=inst.name,
            calculator_inputs=calc_in,
            calculator_result=calc_result,
            projection_result=projection_result,
            projection_label=projection_label,
            display_currency=cur,
            fx_rates=rates,
            fx_updated_at=fx_at,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="PDF export needs optional packages: pip install reportlab matplotlib pypdf",
        ) from exc
    fname = f"webable-investment-calculator-{instance_id}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@app.get("/instances/{instance_id}", response_class=HTMLResponse)
def instance_view(instance_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id)
    jobs = db.query(JobRun).filter(JobRun.instance_id == inst.id).order_by(JobRun.started_at.desc()).limit(20).all()
    jobs_view = [human_job_view(job, user.enable_iefp_mode) for job in jobs]
    latest_output = jobs_view[0] if jobs_view else {
        "icon": "🕒", "badge": "Waiting", "badge_class": "bg-slate-600/30 text-slate-200 border-slate-500/40", "title": "Waiting for execution", "subtitle": "Run an action to see financial output.", "cards": [], "sections": [{"title": "Next steps", "items": ["Add income, expense, or transactions.", "Run a monthly calculation or a multi-month database calculation."]}], "bars": [], "recommendation": "Start by adding your monthly income and expenses.", "duration": None, "technical_logs": "", "job_type": None, "projection_series": None,
    }
    state_summary = {"ready": "Database created successfully" if not jobs else inst.last_sync_status, "updated": humanize_delta(inst.last_activity_at), "health": inst.health_status}
    finance_items = instance_service.list_finance_items(inst.finance_db_path)
    ai_job = next((j for j in jobs if j.job_type == "ai_chat"), None)
    ai_answer = render_ai_answer(ai_job.technical_logs if ai_job else "")
    msg = request.query_params.get("msg", "")
    instances = db.query(DatabaseInstance).filter(DatabaseInstance.owner_id == user.id).order_by(DatabaseInstance.created_at.desc()).all()
    now_m = datetime.utcnow().strftime("%Y-%m")
    budgets = db.query(CategoryBudget).filter(CategoryBudget.instance_id == inst.id).all()
    budget_alerts = _budget_alerts(db, inst, now_m)
    return templates.TemplateResponse(request=request, name="instance.html", context={
        "request": request,
        "user": user,
        "instance": inst,
        "instances": instances,
        "workspace_for_nav": inst,
        "nav_active": None,
        "state_summary": state_summary,
        "latest_output": latest_output,
        "finance_items": finance_items,
        "ai_answer": ai_answer,
        "msg": msg,
        "show_iefp": bool(user.enable_iefp_mode),
        "oneoff_categories": list(instance_service.ONEOFF_CATEGORIES),
        "show_back_to_dashboard": True,
        "category_budgets": budgets,
        "budget_alerts": budget_alerts,
        "current_month": now_m,
    })


@app.get("/instances/{instance_id}/investment-simulation")
def investment_simulation(
    instance_id: int,
    request: Request,
    job_id: int | None = None,
    invest_pct: float = 15.0,
    annual_rate: float = 5.0,
    horizon_years: float = 5.0,
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if job_id is not None:
        _inst, _job, rows = load_completed_range_projection(db, user, instance_id, int(job_id))
    else:
        _inst, _job, rows = load_latest_completed_range_projection(db, user, instance_id)
    invest_pct = max(0.0, min(100.0, float(invest_pct)))
    annual_rate = max(0.0, min(50.0, float(annual_rate)))
    horizon_years = max(0.08, min(60.0, float(horizon_years)))
    sim = projection_finance.run_monthly_simulation(rows, invest_pct, annual_rate, horizon_years)
    chart = {
        "months": [r["month"] for r in sim["rows"]],
        "accumulated_wealth": [r["accumulated_wealth"] for r in sim["rows"]],
        "investment_balance": [r["investment_balance"] for r in sim["rows"]],
        "cumulative_contributed": [r["cumulative_contributed"] for r in sim["rows"]],
        "compounded_profit": [r["compounded_profit"] for r in sim["rows"]],
    }
    n_proj = len(rows)
    projection_tooltip: list[dict] = []
    for k in range(len(sim["rows"])):
        if k < n_proj:
            pr = rows[k]
            income = float(pr.get("total_before_expenses", 0) or 0)
            exp = float(pr.get("expenses", 0) or 0)
            sav = float(pr.get("estimated_savings", 0) or 0)
            projection_tooltip.append(
                {
                    "month": pr.get("month"),
                    "projected_income": income,
                    "projected_expenses": exp,
                    "projected_savings": sav,
                    "net_result": sav,
                }
            )
        else:
            projection_tooltip.append(
                {
                    "month": sim["rows"][k]["month"],
                    "projected_income": None,
                    "projected_expenses": None,
                    "projected_savings": float(sim["meta"].get("extended_monthly_savings_base", 0) or 0),
                    "net_result": None,
                    "note": "Beyond stored projection window; contribution uses extended savings base.",
                }
            )
    return JSONResponse({"summary": sim["summary"], "meta": sim["meta"], "chart": chart, "projection_tooltip": projection_tooltip})


@app.post("/instances/{instance_id}/projection-report")
def projection_report_pdf(
    instance_id: int,
    request: Request,
    job_id: int | None = Form(None),
    invest_pct: float = Form(15.0),
    annual_rate: float = Form(5.0),
    horizon_years: float = Form(5.0),
    display_currency: str | None = Form(None),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if job_id is not None:
        inst, job, rows = load_completed_range_projection(db, user, instance_id, int(job_id))
    else:
        inst, job, rows = load_latest_completed_range_projection(db, user, instance_id)
    invest_pct = max(0.0, min(100.0, float(invest_pct)))
    annual_rate = max(0.0, min(50.0, float(annual_rate)))
    horizon_years = max(0.08, min(60.0, float(horizon_years)))
    sim = projection_finance.run_monthly_simulation(rows, invest_pct, annual_rate, horizon_years)
    details = build_projection_output(rows)
    cur, rates, fx_at = pdf_currency_context(display_currency)
    try:
        pdf_bytes = projection_pdf.build_projection_report_pdf(
            workspace_name=inst.name,
            job_id=job.id,
            job_started=job.started_at,
            projection_rows=rows,
            output_details=details,
            sim=sim,
            display_currency=cur,
            fx_rates=rates,
            fx_updated_at=fx_at,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="PDF export needs optional packages: pip install reportlab matplotlib pypdf",
        ) from exc
    stamp = (job.started_at or datetime.utcnow()).strftime("%Y%m%d-%H%M")
    fname = f"webable-projection-{instance_id}-{stamp}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@app.post("/instances/{instance_id}/results-report")
def results_summary_pdf(
    instance_id: int,
    request: Request,
    job_id: int | None = Form(None),
    display_currency: str | None = Form(None),
    db: Session = Depends(get_db),
):
    """Export only the Results summary (no investment charts)."""
    from app.services import projection_pdf

    user = require_user(request, db)
    inst = require_instance(db, user, instance_id)
    if job_id is not None:
        job = db.query(JobRun).filter(JobRun.id == int(job_id), JobRun.instance_id == inst.id).first()
    else:
        job = db.query(JobRun).filter(JobRun.instance_id == inst.id).order_by(JobRun.started_at.desc()).first()
    if not job or job.status != "done":
        raise HTTPException(status_code=404, detail="No completed result to export.")
    output_view = human_job_view(job, user.enable_iefp_mode)
    details = {
        "cards": output_view.get("cards") or [],
        "sections": output_view.get("sections") or [],
        "bars": output_view.get("bars") or [],
        "recommendation": output_view.get("recommendation") or "",
    }
    cur, rates, fx_at = pdf_currency_context(display_currency)
    try:
        pdf_bytes = projection_pdf.build_results_summary_pdf(
            workspace_name=inst.name,
            result_title=str(output_view.get("title", "Results")),
            result_subtitle=str(output_view.get("subtitle", "")),
            output_details=details,
            display_currency=cur,
            fx_rates=rates,
            fx_updated_at=fx_at,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="PDF export needs optional packages: pip install reportlab matplotlib pypdf",
        ) from exc
    stamp = (job.started_at or datetime.utcnow()).strftime("%Y%m%d-%H%M")
    fname = f"webable-results-{instance_id}-{stamp}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@app.post("/ai/global")
def ai_global(request: Request, question: str = Form(...), instance_id: int | None = Form(None), db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return JSONResponse({"error": "auth_required"}, status_code=401)
    context = collect_user_financial_context(db, user, instance_id=instance_id)
    answer = render_ai_answer(ask_ollama(question, context))
    return JSONResponse({"answer": answer})


@app.post("/instances/{instance_id}/income")
def add_income(
    instance_id: int,
    request: Request,
    nome: str = Form(...),
    valor: float = Form(...),
    recurrence: str = Form("monthly"),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id)
    run_job(db, user, inst, "add_income", lambda: instance_service.add_income(inst.finance_db_path, nome, valor, recurrence=recurrence))
    return RedirectResponse(f"/instances/{instance_id}#workspace-data", status_code=302)


@app.post("/instances/{instance_id}/expense")
def add_expense(
    instance_id: int,
    request: Request,
    nome: str = Form(...),
    valor: float = Form(...),
    recurrence: str = Form("monthly"),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id)
    run_job(db, user, inst, "add_expense", lambda: instance_service.add_expense(inst.finance_db_path, nome, valor, recurrence=recurrence))
    return RedirectResponse(f"/instances/{instance_id}#workspace-data", status_code=302)


@app.post("/instances/{instance_id}/quick-oneoff")
def quick_oneoff(
    instance_id: int,
    request: Request,
    amount: float = Form(...),
    description: str = Form(...),
    txn_type: str = Form(...),
    txn_date: str = Form(""),
    category: str | None = Form(None),
    next_url: str = Form("/dashboard"),
    db: Session = Depends(get_db),
):
    """Quick-add one-time transaction from the global + button."""
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id)
    errs = dashboard_metrics.validate_quick_oneoff(amount, description, txn_type)
    safe_next = next_url if next_url.startswith("/") and not next_url.startswith("//") else "/dashboard"
    if errs:
        sep = "&" if "?" in safe_next else "?"
        return RedirectResponse(f"{safe_next}{sep}quick_err=1", status_code=302)
    tt = "income" if str(txn_type).lower() == "income" else "expense"
    date_s = (txn_date or "").strip() or datetime.utcnow().strftime("%Y-%m-%d")
    cat = category
    if tt == "expense" and (cat or "").strip() not in instance_service.ONEOFF_CATEGORIES:
        cat = "Other"

    def _add():
        return instance_service.add_oneoff(
            inst.finance_db_path,
            date_s,
            description.strip(),
            float(amount),
            txn_type=tt,
            category=cat,
        )

    run_job(db, user, inst, "add_oneoff", _add)
    return RedirectResponse(safe_next, status_code=302)


@app.post("/instances/{instance_id}/oneoff")
def add_oneoff(
    instance_id: int,
    request: Request,
    data: str = Form(...),
    nome: str = Form(...),
    valor: float = Form(...),
    txn_type: str = Form("expense"),
    category: str | None = Form(None),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id)
    tt = "income" if str(txn_type).lower() == "income" else "expense"
    if tt == "expense" and (category or "").strip() not in instance_service.ONEOFF_CATEGORIES:
        return RedirectResponse(f"/instances/{instance_id}?msg=oneoff_category_required", status_code=302)

    def _add():
        return instance_service.add_oneoff(inst.finance_db_path, data, nome, valor, txn_type=tt, category=category)

    run_job(db, user, inst, "add_oneoff", _add)
    return RedirectResponse(f"/instances/{instance_id}#workspace-data", status_code=302)


@app.post("/instances/{instance_id}/income/{item_id}/delete")
def delete_income(instance_id: int, item_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id)
    deleted = instance_service.delete_income(inst.finance_db_path, item_id)
    if not deleted:
        return RedirectResponse(f"/instances/{instance_id}?msg=income_not_found", status_code=302)
    run_job(db, user, inst, "delete_income", lambda: {"deleted": {"name": deleted[0], "amount": deleted[1]}})
    return RedirectResponse(f"/instances/{instance_id}?msg=income_deleted", status_code=302)


@app.post("/instances/{instance_id}/expense/{item_id}/delete")
def delete_expense(instance_id: int, item_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id)
    deleted = instance_service.delete_expense(inst.finance_db_path, item_id)
    if not deleted:
        return RedirectResponse(f"/instances/{instance_id}?msg=expense_not_found", status_code=302)
    run_job(db, user, inst, "delete_expense", lambda: {"deleted": {"name": deleted[0], "amount": deleted[1]}})
    return RedirectResponse(f"/instances/{instance_id}?msg=expense_deleted", status_code=302)


@app.post("/instances/{instance_id}/oneoff/{item_id}/delete")
def delete_oneoff(instance_id: int, item_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id)
    run_job(db, user, inst, "delete_oneoff", lambda: {"deleted": instance_service.delete_oneoff(inst.finance_db_path, item_id)})
    return RedirectResponse(f"/instances/{instance_id}?msg=transaction_deleted", status_code=302)


@app.post("/instances/{instance_id}/absence")
def add_absence(instance_id: int, request: Request, data: str = Form(...), modulo: str = Form(...), horas: float = Form(...), observacao: str = Form(""), db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user.enable_iefp_mode:
        raise HTTPException(status_code=403)
    inst = require_instance(db, user, instance_id)
    run_job(db, user, inst, "add_absence", lambda: instance_service.add_absence(inst.logic_db_path, data, modulo, horas, observacao))
    return RedirectResponse(f"/instances/{instance_id}", status_code=302)


@app.post("/instances/{instance_id}/calculate-month")
def calculate_month(instance_id: int, request: Request, month: str = Form(...), db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id)
    run_job(db, user, inst, "calculate_month", lambda: instance_service.month_summary(inst.finance_db_path, inst.logic_db_path, month, include_iefp=bool(user.enable_iefp_mode)))
    return RedirectResponse(f"/instances/{instance_id}#projection-results", status_code=302)


@app.post("/instances/{instance_id}/calculate-range")
def calculate_range(instance_id: int, request: Request, start_month: str = Form(...), months: int = Form(...), db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id)
    run_job(db, user, inst, "calculate_range", lambda: instance_service.long_range(inst.finance_db_path, inst.logic_db_path, start_month, months, include_iefp=bool(user.enable_iefp_mode)))
    return RedirectResponse(f"/instances/{instance_id}#projection-results", status_code=302)


@app.post("/instances/{instance_id}/ai-chat")
def ai_chat(instance_id: int, request: Request, question: str = Form(...), db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id)

    def _call_ai():
        finance_items = instance_service.list_finance_items(inst.finance_db_path)
        now_month = datetime.utcnow().strftime("%Y-%m")
        latest_month = instance_service.month_summary(inst.finance_db_path, inst.logic_db_path, now_month, include_iefp=bool(user.enable_iefp_mode))
        latest_range = instance_service.long_range(inst.finance_db_path, inst.logic_db_path, now_month, 12, include_iefp=bool(user.enable_iefp_mode))
        context = build_ai_context(user, inst, finance_items, latest_month, latest_range)
        answer = ask_ollama(question, context)
        return {"question": question, "answer": answer}

    run_job(db, user, inst, "ai_chat", _call_ai)
    return RedirectResponse(f"/instances/{instance_id}", status_code=302)


@app.get("/api/build-info")
def api_build_info():
    """Public build identity (version, commit) for post-image-update UX and ops probes."""
    return JSONResponse(build_info.build_info_dict())


@app.get("/api/update/status")
def api_update_status(refresh: bool = False):
    """GitHub comparison + orchestration progress + deployment capabilities."""
    st = update_service.get_cached_status(force_refresh=refresh)
    out = st.as_dict()
    out["orchestration"] = update_orchestration.orchestration_public_dict()
    out["capabilities"] = build_info.live_capabilities_dict()
    return JSONResponse(out)


@app.post("/api/update/start")
async def api_update_start(request: Request, db: Session = Depends(get_db)):
    """Begin one-click update (git or compose) when supported. Requires sign-in."""
    user = current_user(request, db)
    if not user:
        return JSONResponse(
            {"success": False, "message": "Sign in to run updates on this server.", "auth_required": True},
            status_code=401,
        )
    sr = update_orchestration.start_update_thread(user_present=True)
    if not sr.accepted:
        code = 429 if "wait" in (sr.message or "").lower() else 400
        return JSONResponse({"success": False, "message": sr.message}, status_code=code)
    return JSONResponse({"success": True, "run_id": sr.run_id, "message": sr.message, "async_started": True})


@app.post("/api/update/got-it")
async def api_update_got_it(request: Request, db: Session = Depends(get_db)):
    """
    Acknowledge release notes, or start the same async update job as POST /api/update/start
    when WEBABLE_AUTO_UPDATE is enabled in git mode (backward compatible entry point).
    """
    user = current_user(request, db)
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}

    force_ack = bool(body.get("force_acknowledge"))
    if force_ack:
        remote = (body.get("remote_sha") or "").strip() or (update_service.get_cached_status().remote_sha or "")
        return JSONResponse({"success": True, "applied": False, "message": "Acknowledged.", "remote_sha": remote})

    st = update_service.get_cached_status()
    remote = (body.get("remote_sha") or st.remote_sha or "").strip()

    caps = build_info.live_capabilities_dict()
    pre_ok, pre_msg = safe_updater.preflight_git_update()

    if not user and not force_ack and st.update_available and caps.get("update_action_supported"):
        return JSONResponse(
            {
                "success": False,
                "applied": False,
                "auth_required": True,
                "message": "Sign in to install updates on this server.",
                "remote_sha": remote,
            },
            status_code=401,
        )

    if user and not force_ack and st.update_available and caps.get("update_action_supported"):
        ok, msg, rid = update_orchestration.try_start_update(user_present=True)
        if ok:
            return JSONResponse(
                {
                    "success": True,
                    "applied": False,
                    "async_started": True,
                    "run_id": rid,
                    "message": msg,
                    "remote_sha": remote,
                }
            )
        log.warning("Update start failed: %s", msg)
        return JSONResponse(
            {
                "success": False,
                "applied": False,
                "message": msg,
                "remote_sha": remote,
            },
            status_code=400,
        )

    if st.auto_update_enabled and not pre_ok and caps.get("deployment_mode") == "git":
        log.info("Update acknowledgement without apply: %s", pre_msg)
    return JSONResponse({"success": True, "applied": False, "message": "Acknowledged.", "remote_sha": remote})


@app.get("/health")
def health():
    return JSONResponse({"status": "ok"})


@app.get("/health/live")
def health_live():
    return JSONResponse({"status": "ok", "service": "webable"})


@app.get("/health/ready")
def health_ready(db: Session = Depends(get_db)):
    try:
        db.scalar(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    store_ok = False
    try:
        d = ROOT / "statements"
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".write_probe"
        probe.write_text("ok")
        probe.unlink(missing_ok=True)
        store_ok = True
    except OSError:
        store_ok = False
    mdb = SessionLocal()
    mq_ok = True
    try:
        market_data_service.refresh_if_stale(mdb, ROOT)
    except Exception:
        mq_ok = False
    finally:
        mdb.close()
    status = "ready" if db_ok and store_ok else "degraded"
    return JSONResponse(
        {"status": status, "database": db_ok, "statement_storage": store_ok, "market_data": mq_ok},
        status_code=200 if db_ok else 503,
    )


@app.get("/api/market")
def api_market(db: Session = Depends(get_db)):
    try:
        market_data_service.refresh_if_stale(db, ROOT)
    except Exception as exc:
        log.warning("market refresh on read failed: %s", exc)
    return JSONResponse(market_data_service.public_dict(db))


@app.get("/api/market/history")
def api_market_history(range: str = "1m", db: Session = Depends(get_db)):
    """Bundled historical series for SP500/BTC/ETH (EUR). Cached server-side."""
    try:
        r = str(range or "1m").strip().lower()
        bundle = market_chart_service.get_bundle(db, ROOT, r)
        return JSONResponse(bundle)
    except Exception as exc:
        log.warning("market history bundle failed: %s", exc)
        return JSONResponse({"error": "unavailable", "range": str(range or "")}, status_code=503)


def _user_month_totals(user: User, instances: list[DatabaseInstance], month: str) -> dict:
    rows = [
        instance_service.month_summary(
            ins.finance_db_path,
            ins.logic_db_path,
            month,
            include_iefp=bool(user.enable_iefp_mode),
        )
        for ins in instances
    ]
    return dashboard_metrics.aggregate_current_month_totals(rows) if rows else {}


@app.get("/wishlist", response_class=HTMLResponse)
def wishlist_page(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    instances = db.query(DatabaseInstance).filter(DatabaseInstance.owner_id == user.id).order_by(DatabaseInstance.created_at.desc()).all()
    primary = instances[0] if instances else None
    now_m = datetime.utcnow().strftime("%Y-%m")
    mt = _user_month_totals(user, instances, now_m)
    safe_default = dashboard_metrics.safe_to_spend_amount(mt.get("current_month_savings", 0), dashboard_metrics.SAFE_TO_SPEND_DEFAULT_PCT)
    items = wishlist_service.list_items(db, user.id)
    items_view = []
    for it in items:
        aff = dashboard_metrics.wishlist_affordability(it.price_eur, safe_default)
        items_view.append({"item": it, "affordability": aff})
    return templates.TemplateResponse(
        request=request,
        name="wishlist.html",
        context={
            "request": request,
            "user": user,
            "workspace_for_nav": primary,
            "nav_active": "wishlist",
            "show_back_to_dashboard": True,
            "items_view": items_view,
            "safe_to_spend_default": safe_default,
            "month_totals": mt,
        },
    )


@app.post("/wishlist/add")
def wishlist_add(
    request: Request,
    name: str = Form(...),
    price_eur: float = Form(...),
    priority: str = Form("medium"),
    deadline: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not name.strip():
        return RedirectResponse("/wishlist?err=name", status_code=302)
    wishlist_service.add_item(db, user.id, name, price_eur, priority=priority, deadline=deadline or None)
    return RedirectResponse("/wishlist", status_code=302)


@app.post("/wishlist/{item_id}/delete")
def wishlist_delete(item_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    wishlist_service.delete_item(db, user.id, item_id)
    return RedirectResponse("/wishlist", status_code=302)


@app.get("/api/notes")
def api_notes_list(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return JSONResponse({"error": "auth_required"}, status_code=401)
    notes = notes_service.list_notes(db, user.id)
    return JSONResponse(
        {
            "notes": [
                {"id": n.id, "body": n.body, "created_at": n.created_at.isoformat() if n.created_at else ""}
                for n in notes
            ]
        }
    )


@app.post("/api/notes")
async def api_notes_create(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    try:
        body = await request.json()
    except Exception:
        body = {}
    text = (body.get("body") if isinstance(body, dict) else "") or ""
    if not str(text).strip():
        return JSONResponse({"success": False, "message": "Note text is required."}, status_code=400)
    note = notes_service.add_note(db, user.id, str(text))
    return JSONResponse(
        {
            "success": True,
            "note": {
                "id": note.id,
                "body": note.body,
                "created_at": note.created_at.isoformat() if note.created_at else "",
            },
        }
    )


@app.delete("/api/notes/{note_id}")
def api_notes_delete(note_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    ok = notes_service.delete_note(db, user.id, note_id)
    if not ok:
        return JSONResponse({"success": False}, status_code=404)
    return JSONResponse({"success": True})


@app.get("/notes")
def notes_page_redirect():
    """Notes open from the floating N button; no separate page."""
    return RedirectResponse("/dashboard", status_code=302)


@app.post("/notes/add")
def notes_add(request: Request, body: str = Form(...), db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not body.strip():
        return RedirectResponse("/notes?err=empty", status_code=302)
    notes_service.add_note(db, user.id, body)
    return RedirectResponse("/notes", status_code=302)


@app.post("/notes/{note_id}/delete")
def notes_delete(note_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    notes_service.delete_note(db, user.id, note_id)
    return RedirectResponse("/notes", status_code=302)


@app.get("/learn", response_class=HTMLResponse)
def learn_finance(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    primary = db.query(DatabaseInstance).filter(DatabaseInstance.owner_id == user.id).order_by(DatabaseInstance.created_at.desc()).first()
    return templates.TemplateResponse(
        request=request,
        name="learn_finance.html",
        context={
            "request": request,
            "user": user,
            "workspace_for_nav": primary,
            "nav_active": "learn",
            "show_back_to_dashboard": True,
        },
    )


@app.get("/instances/{instance_id}/market-watch", response_class=HTMLResponse)
def market_watch_page(instance_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id)
    instances = db.query(DatabaseInstance).filter(DatabaseInstance.owner_id == user.id).order_by(DatabaseInstance.created_at.desc()).all()
    try:
        market_data_service.refresh_if_stale(db, ROOT)
    except Exception as exc:
        log.warning("market_watch page refresh: %s", exc)
    return templates.TemplateResponse(
        request=request,
        name="market_watch.html",
        context={
            "request": request,
            "user": user,
            "instance": inst,
            "instances": instances,
            "workspace_for_nav": inst,
            "nav_active": "market",
            "show_back_to_dashboard": True,
            "market_payload": market_data_service.public_dict(db),
        },
    )


def _projection_rows_for_analysis(db: Session, inst: DatabaseInstance) -> list[dict]:
    job = (
        db.query(JobRun)
        .filter(
            JobRun.instance_id == inst.id,
            JobRun.job_type == "calculate_range",
            JobRun.status == "done",
        )
        .order_by(JobRun.started_at.desc())
        .first()
    )
    if not job:
        return []
    return projection_finance.parse_projection_rows(parse_metrics(job.metrics_json))


def _projection_summary_for_analysis(db: Session, inst: DatabaseInstance) -> dict:
    rows = _projection_rows_for_analysis(db, inst)
    if not rows:
        return {"available": False}
    last = rows[-1]
    return {
        "available": True,
        "saved_months": len(rows),
        "final_accumulated_eur": float(last.get("accumulated", 0) or 0),
        "last_month": str(last.get("month", "")),
    }


@app.get("/instances/{instance_id}/analysis-data")
def analysis_data(instance_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id)
    now_m = datetime.utcnow().strftime("%Y-%m")
    stmt_count = db.query(BankStatement).filter(BankStatement.instance_id == inst.id).count()
    latest_stmt = (
        db.query(BankStatement)
        .filter(BankStatement.instance_id == inst.id)
        .order_by(BankStatement.created_at.desc())
        .first()
    )
    latest_m = latest_stmt.statement_month if latest_stmt else None
    proj_rows = _projection_rows_for_analysis(db, inst)
    data = analysis_service.build_workspace_analytics(
        inst.finance_db_path,
        inst.logic_db_path,
        include_iefp=bool(user.enable_iefp_mode),
        current_month=now_m,
        statement_count=stmt_count,
        latest_statement_month=latest_m,
        projection_summary=_projection_summary_for_analysis(db, inst),
        projection_rows=proj_rows,
    )
    return JSONResponse(data)


@app.get("/instances/{instance_id}/analysis", response_class=HTMLResponse)
def analysis_page(instance_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id)
    instances = db.query(DatabaseInstance).filter(DatabaseInstance.owner_id == user.id).order_by(DatabaseInstance.created_at.desc()).all()
    now_m = datetime.utcnow().strftime("%Y-%m")
    stmt_count = db.query(BankStatement).filter(BankStatement.instance_id == inst.id).count()
    latest_stmt = (
        db.query(BankStatement)
        .filter(BankStatement.instance_id == inst.id)
        .order_by(BankStatement.created_at.desc())
        .first()
    )
    latest_m = latest_stmt.statement_month if latest_stmt else None
    proj_rows = _projection_rows_for_analysis(db, inst)
    analysis_data_payload = analysis_service.build_workspace_analytics(
        inst.finance_db_path,
        inst.logic_db_path,
        include_iefp=bool(user.enable_iefp_mode),
        current_month=now_m,
        statement_count=stmt_count,
        latest_statement_month=latest_m,
        projection_summary=_projection_summary_for_analysis(db, inst),
        projection_rows=proj_rows,
    )
    return templates.TemplateResponse(
        request=request,
        name="analysis.html",
        context={
            "request": request,
            "user": user,
            "instance": inst,
            "instances": instances,
            "workspace_for_nav": inst,
            "nav_active": "analysis",
            "show_back_to_dashboard": True,
            "analysis_data": analysis_data_payload,
        },
    )


@app.get("/instances/{instance_id}/savings-calculator", response_class=HTMLResponse)
def savings_calculator_page(instance_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id)
    instances = db.query(DatabaseInstance).filter(DatabaseInstance.owner_id == user.id).order_by(DatabaseInstance.created_at.desc()).all()
    return templates.TemplateResponse(
        request=request,
        name="savings_calculator.html",
        context={
            "request": request,
            "user": user,
            "instance": inst,
            "instances": instances,
            "workspace_for_nav": inst,
            "nav_active": "savings",
            "show_back_to_dashboard": True,
        },
    )


@app.get("/instances/{instance_id}/api/savings/saved-expenses-summary")
def api_savings_saved_expenses_summary(
    instance_id: int,
    request: Request,
    month: str | None = None,
    db: Session = Depends(get_db),
):
    from .services import savings_expenses_service

    user = require_user(request, db)
    inst = require_instance(db, user, instance_id)
    try:
        summary = savings_expenses_service.summarize_saved_expenses(inst.finance_db_path, month)
        return JSONResponse(summary)
    except Exception as exc:
        log.warning("saved expenses summary failed: %s", exc)
        return JSONResponse(
            {"error": "Could not load saved expenses.", "has_data": False, "categories": {}, "monthly_total": 0},
            status_code=500,
        )


@app.post("/instances/{instance_id}/savings-calculator/calculate")
async def savings_calculator_calculate(instance_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    require_instance(db, user, instance_id)
    body = await request.json()
    result = emergency_fund_service.compute(body or {})
    return JSONResponse(result)


@app.post("/instances/{instance_id}/savings-calculator/pdf")
async def savings_calculator_pdf(instance_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id)
    body = await request.json()
    result = emergency_fund_service.compute(body or {})
    cur, rates, fx_at = pdf_currency_context(body.get("display_currency"))
    try:
        pdf_bytes = savings_pdf.build_savings_calculator_pdf(
            workspace_name=inst.name,
            inputs=body or {},
            result=result,
            display_currency=cur,
            fx_rates=rates,
            fx_updated_at=fx_at,
        )
    except ImportError as exc:
        log.exception("savings pdf import error")
        raise HTTPException(status_code=503, detail="PDF export unavailable") from exc
    except Exception as exc:
        log.exception("savings pdf failed")
        raise HTTPException(status_code=500, detail="PDF generation failed") from exc
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="webable-emergency-fund-{instance_id}.pdf"'},
    )


@app.post("/instances/{instance_id}/bank-statements/upload")
async def bank_statement_upload(
    instance_id: int,
    request: Request,
    db: Session = Depends(get_db),
    file: UploadFile = File(...),
    statement_month: str = Form(...),
    bank_name: str | None = Form(None),
):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id)
    if not file.filename or not str(file.filename).lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF uploads are allowed.")
    content = await file.read()
    row, err = bank_statement_service.save_statement(
        db,
        ROOT,
        inst,
        user.id,
        content=content,
        original_filename=file.filename,
        statement_month=statement_month,
        bank_name=bank_name,
    )
    if err or not row:
        log.warning("bank statement upload rejected: %s", err)
        raise HTTPException(status_code=400, detail=err or "Upload failed")
    return JSONResponse({"id": row.id, "statement_month": row.statement_month, "filename": row.original_filename})


@app.get("/instances/{instance_id}/bank-statements/{statement_id}/file")
def bank_statement_download(instance_id: int, statement_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    require_instance(db, user, instance_id)
    row = bank_statement_service.get_owned(db, user.id, statement_id)
    if not row or row.instance_id != instance_id:
        raise HTTPException(status_code=404)
    path = ROOT / row.storage_rel_path
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File missing")
    return FileResponse(path, filename=row.original_filename, media_type="application/pdf")


@app.delete("/instances/{instance_id}/bank-statements/{statement_id}")
def bank_statement_delete(instance_id: int, statement_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    require_instance(db, user, instance_id)
    row = bank_statement_service.get_owned(db, user.id, statement_id)
    if not row or row.instance_id != instance_id:
        raise HTTPException(status_code=404)
    bank_statement_service.delete_statement(db, ROOT, row)
    return JSONResponse({"deleted": True})


@app.get("/instances/{instance_id}/bank-statements")
def bank_statements_list(instance_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id)
    rows = bank_statement_service.list_for_instance(db, inst.id)
    return JSONResponse(
        {
            "items": [
                {
                    "id": r.id,
                    "statement_month": r.statement_month,
                    "bank_name": r.bank_name,
                    "filename": r.original_filename,
                    "uploaded_at": r.created_at.isoformat() + "Z" if r.created_at else None,
                    "file_size": r.file_size,
                }
                for r in rows
            ]
        }
    )


@app.get("/instances/{instance_id}/export/transactions.csv")
def export_transactions_csv(instance_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id)
    items = instance_service.list_finance_items(inst.finance_db_path)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["type", "id", "date", "name", "amount", "category", "txn_type"])
    for i in items["incomes"]:
        w.writerow(["recurring_income", i["id"], "", i["name"], i["amount"], "", "income"])
    for i in items["expenses"]:
        w.writerow(["recurring_expense", i["id"], "", i["name"], i["amount"], "", "expense"])
    for t in items["oneoffs"]:
        w.writerow(["oneoff", t["id"], t["date"], t["name"], t["amount"], t["category"], t["txn_type"]])
    data = buf.getvalue().encode("utf-8")
    return Response(
        content=data,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="webable-transactions-{instance_id}.csv"'},
    )


@app.get("/instances/{instance_id}/export/transactions.json")
def export_transactions_json(instance_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id)
    items = instance_service.list_finance_items(inst.finance_db_path)
    payload = {
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "workspace": inst.name,
        "workspace_id": inst.id,
        "data": items,
    }
    return JSONResponse(payload)


@app.get("/instances/{instance_id}/transactions/search")
def transactions_search(
    instance_id: int,
    request: Request,
    db: Session = Depends(get_db),
    q: str | None = None,
    category: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    amt_min: float | None = None,
    amt_max: float | None = None,
    txn_type: str | None = None,
    sort: str = "newest",
    limit: int = 50,
    offset: int = 0,
):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id)
    return JSONResponse(
        instance_service.search_oneoffs(
            inst.finance_db_path,
            q=q,
            category=category,
            date_from=date_from,
            date_to=date_to,
            amt_min=amt_min,
            amt_max=amt_max,
            txn_type=txn_type,
            sort=sort,
            limit=limit,
            offset=offset,
        )
    )


@app.post("/instances/{instance_id}/budgets")
def budget_upsert(
    instance_id: int,
    request: Request,
    db: Session = Depends(get_db),
    category: str = Form(...),
    monthly_limit_eur: float = Form(...),
):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id)
    cat = (category or "").strip()
    if cat not in instance_service.ONEOFF_CATEGORIES:
        raise HTTPException(status_code=400, detail="Invalid category")
    lim = max(0.0, float(monthly_limit_eur))
    row = db.query(CategoryBudget).filter(CategoryBudget.instance_id == inst.id, CategoryBudget.category == cat).first()
    if row:
        row.monthly_limit_eur = lim
    else:
        db.add(CategoryBudget(instance_id=inst.id, category=cat, monthly_limit_eur=lim))
    db.commit()
    return RedirectResponse(f"/instances/{instance_id}", status_code=302)


@app.post("/instances/{instance_id}/budgets/{budget_id}/delete")
def budget_delete(instance_id: int, budget_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id)
    row = db.query(CategoryBudget).filter(CategoryBudget.id == budget_id, CategoryBudget.instance_id == inst.id).first()
    if row:
        db.delete(row)
        db.commit()
    return RedirectResponse(f"/instances/{instance_id}", status_code=302)
