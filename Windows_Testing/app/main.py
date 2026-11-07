import csv
import io
import json
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path
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
from .models import BankStatement, CategoryBudget, DatabaseInstance, FinanceAuditLog, JobRun, MonthlySnapshot, MotherInsightEvent, Notification, User, WorkspaceInvite, WorkspaceMember
from .services import (
    ai_service,
    analysis_service,
    bank_statement_service,
    build_info,
    category_breakdown_service,
    currency_service,
    dashboard_metrics,
    db_safety,
    document_service,
    emergency_fund_service,
    eom_summary_service,
    eom_summary_pdf,
    expense_panel,
    export_naming,
    financial_timeline_service,
    instance_service,
    monthly_snapshot_service,
    net_worth_service,
    notes_service,
    notification_service,
    numeric_input,
    wishlist_service,
    investment_pdf,
    market_chart_service,
    market_data_service,
    projection_finance,
    projection_pdf,
    reports_pdf,
    safe_updater,
    savings_pdf,
    server_restart_service,
    shared_workspace_service,
    spending_report,
    tax_service,
    update_orchestration,
    update_service,
    workspace_export_service,
    workspace_service,
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
_APP_DIR = Path(__file__).resolve().parent
_STATIC_DIR = _APP_DIR / "static"
_TEMPLATE_DIR = _APP_DIR / "templates"
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))
# The "Restart server" button rebuilds the Docker deployment; the frozen Windows desktop app has no Docker.
templates.env.globals["restart_button_available"] = not getattr(sys, "frozen", False)

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


def money(value: float, currency: str = "EUR") -> str:
    return f"{currency or 'EUR'} {float(value):,.2f}"


def ws_currency(inst: DatabaseInstance | None) -> str:
    return currency_service.workspace_currency(getattr(inst, "currency", None) if inst else None)


def download_response(content: bytes, media_type: str, filename: str) -> Response:
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": export_naming.content_disposition(filename)},
    )


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


def require_instance(db: Session, user: User, instance_id: int, action: str = "read") -> DatabaseInstance:
    inst, _member = workspace_service.require_workspace(db, user, instance_id, action)
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


def pdf_currency_context(
    display_currency: str | None, base_currency: str = "EUR"
) -> tuple[str, dict[str, float], str | None]:
    """
    EUR workspaces keep the optional display conversion. Other workspaces are always rendered in
    their own currency with an identity rate (amounts are never converted across currencies).
    """
    base = currency_service.workspace_currency(base_currency)
    if base != "EUR":
        return base, {base: 1.0}, currency_service.NO_CONVERSION_MARKER
    currency_service.ensure_fresh_rates(ROOT)
    st = currency_service.rates_public_dict(ROOT)
    cur = currency_service.normalize_currency(display_currency)
    rates = {k: float(v) for k, v in (st.get("rates") or {}).items()}
    return cur, rates, st.get("updated_at")


def build_monthly_output(metrics: dict, show_iefp: bool, currency: str = "EUR") -> dict:
    def money(v):
        return globals()["money"](v, currency)

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
    taxes = metrics.get("taxes") or {}
    tax_total = float(metrics.get("taxes_total", 0) or 0)
    tax_cards = []
    tax_sections = []
    if taxes.get("lines"):
        income_after = float(metrics.get("income_after_tax", total_in - tax_total))
        savings_pre = float(metrics.get("estimated_savings_pre_tax", savings + tax_total))
        tax_cards = [
            {"label": "Income before tax", "value": money(total_in), "value_eur": round(total_in, 2), "tone": "info"},
            {
                "label": f"Taxes ({taxes.get('effective_rate_pct', 0):g}% effective)",
                "value": money(tax_total),
                "value_eur": round(tax_total, 2),
                "tone": "negative",
            },
            {"label": "Income after tax", "value": money(income_after), "value_eur": round(income_after, 2), "tone": "positive"},
            {
                "label": "Net savings before tax",
                "value": money(savings_pre),
                "value_eur": round(savings_pre, 2),
                "tone": "positive" if savings_pre >= 0 else "negative",
            },
        ]
        tax_sections = [
            {
                "title": "Taxes",
                "items": [
                    f"{l['name']} ("
                    + " + ".join(
                        ([f"{l['rate_pct']:g}%"] if l["rate_pct"] else []) + ([f"{money(l['fixed_monthly'])} fixed"] if l["fixed_monthly"] else [])
                    )
                    + f"): {money(l['amount'])} on {', '.join(l.get('incomes') or [])} ({money(l['base'])})"
                    for l in taxes["lines"]
                ]
                + [f"Total: {money(tax_total)} — income {money(total_in)} before tax → {money(income_after)} after tax"],
            }
        ]

    return {
        "cards": [
            {
                "label": "Estimated net savings" + (" (after tax)" if tax_cards else ""),
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
        ]
        + tax_cards,
        "sections": tax_sections
        + [
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
                    ("Positive month" if savings >= 0 else "Negative month")
                    + f" — net savings {money(savings)}"
                    + (f" after {money(tax_total)} tax" if tax_cards else ""),
                    f"Recurring income: {money(recurring_inc)} · One-time income: {money(oneoff_inc)}",
                    f"Recurring expenses: {money(recurring_exp)} · One-time expenses: {money(oneoff_exp)}",
                ],
            },
        ],
        "bars": [],
        "month_breakdown": month_breakdown,
        "recommendation": "Great month. Keep building savings." if savings >= 0 else "Review recurring and one-time spending to improve your monthly balance.",
    }


def build_projection_output(rows: list[dict], currency: str = "EUR") -> dict:
    def money(v):
        return globals()["money"](v, currency)

    if not rows:
        return {"cards": [], "sections": [], "bars": [], "recommendation": "Run a projection to see long-term trends."}
    savings = [float(r.get("estimated_savings", 0)) for r in rows]
    months = [r.get("month", "-") for r in rows]
    acc = float(rows[-1].get("accumulated", 0))
    best = max(range(len(savings)), key=lambda i: savings[i])
    worst = min(range(len(savings)), key=lambda i: savings[i])
    total_tax = round(sum(float(r.get("taxes_total", 0) or 0) for r in rows), 2)
    gross_in = round(sum(float(r.get("income_pre_tax", r.get("total_before_expenses", 0)) or 0) for r in rows), 2)
    acc_pre = round(acc + total_tax, 2)
    tax_cards = []
    tax_items = []
    if total_tax > 0:
        tax_cards = [
            {"label": "Accumulated savings before tax", "value": money(acc_pre), "value_eur": acc_pre, "tone": "positive" if acc_pre >= 0 else "negative"},
            {"label": "Total taxes over the period", "value": money(total_tax), "value_eur": total_tax, "tone": "negative"},
            {
                "label": "Income before → after tax",
                "value": f"{money(gross_in)} → {money(gross_in - total_tax)}",
                "tone": "info",
            },
        ]
        tax_items = [
            f"Income before tax: {money(gross_in)}",
            f"Taxes: {money(total_tax)} ({(total_tax / gross_in * 100 if gross_in else 0):.1f}% of income)",
            f"Income after tax: {money(gross_in - total_tax)}",
            f"Accumulated savings: {money(acc_pre)} before tax → {money(acc)} after tax",
        ]
    mx = max([abs(v) for v in savings], default=1) or 1
    running = 0.0
    bars = []
    for i in range(len(rows)):
        running += float(savings[i])
        bars.append(
            {
                "label": months[i],
                "value": money(savings[i]),
                "value_eur": round(float(savings[i]), 2),
                "accumulated": money(running),
                "accumulated_eur": round(running, 2),
                "pct": max(8, int((abs(savings[i]) / mx) * 100)),
                "tone": "positive" if savings[i] >= 0 else "negative",
            }
        )

    return {
        "cards": [
            {
                "label": "Projected Accumulated Savings" + (" (after tax)" if tax_cards else ""),
                "value": money(acc),
                "value_eur": round(acc, 2),
                "tone": "positive" if acc >= 0 else "negative",
            },
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
        ]
        + tax_cards,
        "sections": [
            {"title": "Projection Highlights", "items": [f"Months analyzed: {len(rows)}", f"Positive months: {len([v for v in savings if v >= 0])}", f"Negative months: {len([v for v in savings if v < 0])}"]},
        ]
        + ([{"title": "Taxes", "items": tax_items}] if tax_items else []),
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
    cur = ws_currency(job.instance)

    def money(v):
        return globals()["money"](v, cur)

    details = {"cards": [], "sections": [], "bars": [], "recommendation": "Everything looks good."}
    projection_series: list[dict] | None = None

    if isinstance(metrics, dict) and "month" in metrics and "estimated_savings" in metrics:
        details = build_monthly_output(metrics, show_iefp, cur)
    elif isinstance(metrics, list):
        rows = [r for r in metrics if isinstance(r, dict)]
        details = build_projection_output(rows, cur)
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
    """Insights for the workspaces passed in (the dashboard passes only the active one)."""
    cur = ws_currency((instances or [None])[0])

    def money(v):
        return globals()["money"](v, cur)

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

    panel = expense_panel.build_expense_panel_payload(instances or [], month_totals=mt, currency=cur)
    expense_entries_enriched = panel["entries"]
    expenses_summary_line = panel["summary"]
    fixed_summary = dashboard_metrics.fixed_expenses_summary(fixed_total, month_income)
    if fixed_summary.get("pct_of_income"):
        fixed_summary["line"] = f"Fixed expenses: {money(fixed_summary['amount_eur'])} — {fixed_summary['pct_of_income']}% of income"
    else:
        fixed_summary["line"] = f"Fixed expenses: {money(fixed_summary['amount_eur'])} — income unavailable"

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


def build_dashboard_chart_data(db: Session, user: User, instances: list[DatabaseInstance], active: DatabaseInstance | None = None) -> dict:
    current_month = datetime.utcnow().strftime("%Y-%m")
    income_total = 0.0
    expense_total = 0.0
    savings_total = 0.0
    available_total = 0.0
    savings_reserved = 0.0
    by_workspace_labels = []
    by_workspace_income = []
    by_workspace_expenses = []
    monthly_labels = []
    monthly_savings = []

    scope = [active] if active else instances
    for ins in scope:
        if not ins:
            continue
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
        available_total += month.get("available_balance", 0)
        savings_reserved += month.get("savings_total", 0)
        by_workspace_labels.append(ins.name)
        by_workspace_income.append(round(income, 2))
        by_workspace_expenses.append(round(expenses, 2))

    chart_instance = active or (instances[0] if instances else None)
    if chart_instance:
        range_6 = instance_service.long_range(
            chart_instance.finance_db_path,
            chart_instance.logic_db_path,
            current_month,
            6,
            include_iefp=bool(user.enable_iefp_mode),
        )
        monthly_labels = [row["month"] for row in range_6]
        monthly_savings = [row.get("available_balance", row["estimated_savings"]) for row in range_6]

    growth = 0.0
    if len(monthly_savings) >= 2 and monthly_savings[0] != 0:
        growth = round(((monthly_savings[-1] - monthly_savings[0]) / abs(monthly_savings[0])) * 100, 1)

    return {
        "income_total": round(income_total, 2),
        "expense_total": round(expense_total, 2),
        "savings_total": round(savings_total, 2),
        "available_balance": round(available_total, 2),
        "savings_reserved_total": round(savings_reserved, 2),
        "current_month_savings": round(available_total, 2),
        "growth_percent": growth,
        "workspace_labels": by_workspace_labels,
        "workspace_income": by_workspace_income,
        "workspace_expenses": by_workspace_expenses,
        "monthly_labels": monthly_labels,
        "monthly_savings": monthly_savings,
    }


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
    elif job_type in ("update_income", "update_expense", "update_oneoff", "update_savings"):
        entity = job_type.split("_", 1)[1]
        action = "moved" if result.get("moved_from_id") is not None else "updated"
        raw_id = result.get("moved_from_id", result.get("id"))
        eid = int(raw_id) if raw_id is not None else None
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
        "add_savings": "Savings deposit recorded",
        "add_oneoff": "One-time transaction saved",
        "add_absence": "Absence registered",
        "calculate_month": "Monthly projection completed",
        "calculate_range": "Long-range projection completed",
        "delete_income": "Income deleted successfully",
        "delete_expense": "Expense deleted successfully",
        "delete_oneoff": "Transaction deleted successfully",
        "delete_savings": "Savings deposit removed",
        "update_savings": "Savings deposit updated",
        "update_income": "Income entry updated",
        "update_expense": "Expense entry updated",
        "update_oneoff": "One-time transaction updated",
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
    instances = workspace_service.list_user_workspaces(db, user)
    if len(instances) == 1:
        resp.set_cookie(workspace_service.ACTIVE_WORKSPACE_COOKIE, str(instances[0].id), httponly=True, samesite="lax")
    return resp


@app.post("/login")
def login(username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username.strip()).first()
    if not user or not verify_password(password, user.password_hash):
        return RedirectResponse("/?err=invalid_login", status_code=302)
    resp = RedirectResponse("/dashboard", status_code=302)
    resp.set_cookie(SESSION_COOKIE, issue_session(user), httponly=True, samesite="lax")
    instances = workspace_service.list_user_workspaces(db, user)
    if user.active_workspace_id:
        resp.set_cookie(workspace_service.ACTIVE_WORKSPACE_COOKIE, str(user.active_workspace_id), httponly=True, samesite="lax")
    elif len(instances) == 1:
        resp.set_cookie(workspace_service.ACTIVE_WORKSPACE_COOKIE, str(instances[0].id), httponly=True, samesite="lax")
    return resp


@app.post("/logout")
def logout():
    resp = RedirectResponse("/", status_code=302)
    resp.delete_cookie(SESSION_COOKIE)
    resp.delete_cookie(workspace_service.ACTIVE_WORKSPACE_COOKIE)
    return resp


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    instances, active = workspace_service.resolve_active_workspace(db, user, request)
    metadata = {ins.id: instance_service.list_metadata(ins.finance_db_path, ins.logic_db_path) for ins in instances}
    member_ids = [ins.id for ins in instances]  # shared workspaces stay off the dashboard
    jobs = (
        db.query(JobRun)
        .filter(JobRun.instance_id.in_(member_ids) if member_ids else JobRun.instance_id == -1)
        .order_by(JobRun.started_at.desc())
        .limit(20)
        .all()
    )
    intelligence = dashboard_intelligence(instances, jobs, metadata)
    jobs_view = [human_job_view(job, user.enable_iefp_mode) for job in jobs]
    now_m = datetime.utcnow().strftime("%Y-%m")
    month_rows = []
    chart_scope = [active] if active else instances
    for ins in chart_scope:
        if ins:
            month_rows.append(
                instance_service.month_summary(
                    ins.finance_db_path,
                    ins.logic_db_path,
                    now_m,
                    include_iefp=bool(user.enable_iefp_mode),
                )
            )
    month_totals = dashboard_metrics.aggregate_current_month_totals(month_rows) if month_rows else {}
    primary = active or (instances[0] if instances else None)
    # Workspaces can use different currencies, so insights never aggregate across them.
    mother_output = build_mother_output(intelligence, jobs, metadata, [primary] if primary else [], month_totals=month_totals)
    breakdown_range = request.query_params.get("breakdown_range") or category_breakdown_service.DEFAULT_RANGE
    category_breakdown = (
        category_breakdown_service.build_category_breakdown(primary.finance_db_path, breakdown_range) if primary else None
    )
    if primary:
        eom_summary_service.ensure_eom_snapshots(db, primary, user, max_months=6)
    chart_data = build_dashboard_chart_data(db, user, instances, active=active)
    insights = db.query(MotherInsightEvent).filter(MotherInsightEvent.owner_id == user.id).order_by(MotherInsightEvent.created_at.desc()).limit(10).all()
    latest_statement = None
    if primary:
        latest_statement = (
            db.query(BankStatement)
            .filter(BankStatement.instance_id == primary.id)
            .order_by(BankStatement.created_at.desc())
            .first()
        )
    roles = workspace_service.membership_map(db, user)
    nw = net_worth_service.summary(primary.finance_db_path) if primary else None
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "request": request,
            "user": user,
            "instances": instances,
            "active_workspace": active,
            "workspace_roles": roles,
            "primary_instance": primary,
            "workspace_for_nav": primary,
            "nav_active": "overview",
            "jobs_view": jobs_view,
            "intelligence": intelligence,
            "chart_data": chart_data,
            "mother_output": mother_output,
            "insights": insights,
            "humanize_delta": humanize_delta,
            "show_back_to_dashboard": False,
            "current_month": now_m,
            "latest_bank_statement": latest_statement,
            "oneoff_categories": list(instance_service.ONEOFF_CATEGORIES),
            "category_breakdown": category_breakdown,
            "currency_options": currency_service.currency_options(),
            "workspace_currency": ws_currency(primary),
            "savings_reserved": nw["totals"]["emergency_fund"] if nw else 0.0,
            "savings_reserved_months": nw["emergency"]["months_covered"] if nw else None,
            "savings_reserved_can_edit": bool(primary) and workspace_service.role_allows(roles.get(primary.id), "edit"),
        },
    )


@app.get("/instances/{instance_id}/category-breakdown")
def category_breakdown_data(instance_id: int, request: Request, range: str | None = None, db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id)
    data = category_breakdown_service.build_category_breakdown(inst.finance_db_path, range)
    data["currency"] = ws_currency(inst)
    data["workspace"] = inst.name
    return JSONResponse(data)


@app.post("/instances/create")
def create_instance(
    request: Request,
    name: str = Form(...),
    currency: str = Form("EUR"),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    clean_name = name.strip()[:120]
    if not clean_name:
        return RedirectResponse("/dashboard?err=workspace_name", status_code=302)
    code = (currency or "EUR").upper().strip()
    if code not in currency_service.SUPPORTED:
        return RedirectResponse("/dashboard?err=workspace_currency", status_code=302)
    tmp = int(datetime.utcnow().timestamp())
    finance_path, logic_path = instance_service.instance_paths(ROOT, user.id, tmp, f"{slugify(clean_name)}_{uuid4().hex[:8]}")
    instance_service.init_finance_db(finance_path)
    instance_service.init_logic_db(logic_path)
    inst = DatabaseInstance(owner_id=user.id, name=clean_name, mode="general", currency=code, finance_db_path=finance_path, logic_db_path=logic_path, last_sync_status="Database created successfully", last_activity_at=datetime.utcnow())
    db.add(inst)
    db.commit()
    db.refresh(inst)
    workspace_service.add_owner_member(db, inst.id, user.id)
    user.active_workspace_id = inst.id
    db.add(user)
    db.commit()
    db.add(MotherInsightEvent(owner_id=user.id, instance_id=inst.id, event_type="create_instance", severity="success", title="Database created successfully", details=f"Workspace '{inst.name}' is ready."))
    db.commit()
    resp = RedirectResponse("/dashboard", status_code=302)
    resp.set_cookie(workspace_service.ACTIVE_WORKSPACE_COOKIE, str(inst.id), httponly=True, samesite="lax")
    return resp


@app.post("/instances/{instance_id}/delete")
def delete_instance(instance_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id, action="delete_workspace")
    inst_name = inst.name
    for st in db.query(BankStatement).filter(BankStatement.instance_id == inst.id).all():
        fp = ROOT / st.storage_rel_path
        try:
            if fp.is_file():
                fp.unlink()
        except OSError:
            log.warning("could not remove statement file %s", fp)
    document_service.delete_instance_files(db, ROOT, inst.id)
    invite_ids = [i.id for i in db.query(WorkspaceInvite.id).filter(WorkspaceInvite.workspace_id == inst.id).all()]
    if invite_ids:
        db.query(Notification).filter(Notification.invite_id.in_(invite_ids)).update(
            {Notification.invite_id: None}, synchronize_session=False
        )
    db.query(Notification).filter(Notification.workspace_id == inst.id).update(
        {Notification.workspace_id: None}, synchronize_session=False
    )
    for u in db.query(User).filter(User.active_workspace_id == inst.id).all():
        u.active_workspace_id = None
        db.add(u)
    db.query(WorkspaceMember).filter(WorkspaceMember.workspace_id == inst.id).delete()
    db.query(WorkspaceInvite).filter(WorkspaceInvite.workspace_id == inst.id).delete()
    # Shared copies outlive their source; members linked to this workspace stop contributing.
    db.query(WorkspaceMember).filter(WorkspaceMember.linked_workspace_id == inst.id).update(
        {WorkspaceMember.linked_workspace_id: None}, synchronize_session=False
    )
    db.query(DatabaseInstance).filter(DatabaseInstance.source_workspace_id == inst.id).update(
        {DatabaseInstance.source_workspace_id: None}, synchronize_session=False
    )
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
    bounds = spending_report.report_date_bounds(oneoffs, items["incomes"] + items["expenses"])
    return {
        "instance_id": inst.id,
        "instance_name": inst.name,
        "recurring_income_monthly": recurring_income,
        "recurring_expense_monthly": recurring_expense,
        "date_bounds": {"min": bounds[0].isoformat() if bounds[0] else None, "max": bounds[1].isoformat() if bounds[1] else None},
    }


def build_workspace_spending_report(inst: DatabaseInstance, start_d: date | None, end_d: date | None) -> dict:
    """Spending report with recurring entries counted per active month (used by the page and the PDF)."""
    items = instance_service.list_finance_items(inst.finance_db_path)
    return spending_report.build_spending_report(
        items["oneoffs"],
        0.0,
        0.0,
        start_d,
        end_d,
        recurring_incomes=items["incomes"],
        recurring_expenses=items["expenses"],
    )


@app.get("/instances/{instance_id}/reports", response_class=HTMLResponse)
def reports_page(instance_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id)
    instances = workspace_service.list_user_workspaces(db, user)
    base = build_reports_payload(inst)
    statements = bank_statement_service.list_for_instance(db, inst.id)
    doc_categories = [
        {"category": c, "documents": document_service.list_documents(db, c.id)}
        for c in document_service.list_categories(db, inst.id)
    ]
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
            "doc_categories": doc_categories,
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
    start_d, end_d = resolve_report_date_range(preset, start_date, end_date)
    return JSONResponse(build_workspace_spending_report(inst, start_d, end_d))


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
    start_d, end_d = resolve_report_date_range(preset, start_date, end_date)
    report = build_workspace_spending_report(inst, start_d, end_d)
    if report.get("range") and report["range"].get("start") and report["range"].get("end"):
        label = reports_range_label(None, date.fromisoformat(report["range"]["start"]), date.fromisoformat(report["range"]["end"]))
    else:
        label = reports_range_label(preset, start_d, end_d)
    cur, rates, fx_at = pdf_currency_context(display_currency, ws_currency(inst))
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
    rng = report.get("range") or {}
    fname = export_naming.workspace_filename(
        inst, "Spending-Report", "pdf", start=rng.get("start") or start_d, end=rng.get("end") or end_d
    )
    return download_response(pdf_bytes, "application/pdf", fname)


@app.get("/instances/{instance_id}/investment-calculator", response_class=HTMLResponse)
def investment_calculator_page(instance_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id)
    instances = workspace_service.list_user_workspaces(db, user)
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
            "balances": net_worth_service.get_balances(inst.finance_db_path),
            "show_back_to_dashboard": True,
        },
    )


def _calculator_inputs(body: dict) -> dict:
    """Validated long-term projection inputs (shared by the live chart and the PDF export)."""

    def num(key: str, default: float) -> float:
        try:
            v = float(body.get(key, default))
        except (TypeError, ValueError):
            return default
        return v if v == v else default

    raw_n = str(body.get("compounding_per_year", "0") or "0").strip().lower()
    n = 0 if raw_n in ("0", "effective", "") else max(1, min(365, int(float(raw_n))))
    return {
        "initial_balance": max(0.0, num("initial_balance", 0.0)),
        "monthly_contribution": max(0.0, num("monthly_contribution", 0.0)),
        "annual_rate_pct": projection_finance.clamp_annual_rate(num("annual_rate_pct", 0.0)),
        "years": max(1 / 12, min(80.0, num("years", 1.0))),
        "compounding_per_year": n,
        "contribution_timing": projection_finance.normalize_timing(str(body.get("contribution_timing") or "end"), "end"),
    }


@app.post("/instances/{instance_id}/investment-calculator/simulate")
async def investment_calculator_simulate(instance_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id)
    body = await request.json()
    result = projection_finance.run_investment_calculator(**_calculator_inputs(body or {}))
    s = result.get("summary") or {}
    tax = tax_service.apply_investment_tax(float(s.get("compound_growth", 0) or 0), tax_service.investment_tax_rate(inst.finance_db_path))
    tax["final_after_tax"] = round(float(s.get("final_balance", 0) or 0) - tax["tax"], 2)
    result["tax"] = tax
    return JSONResponse(result)


@app.post("/instances/{instance_id}/investment-calculator/pdf")
async def investment_calculator_pdf_export(instance_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id)
    body = await request.json()
    calc_in = _calculator_inputs(body or {})
    annual = calc_in["annual_rate_pct"]
    calc_result = projection_finance.run_investment_calculator(**calc_in)
    pdf_inputs = dict(calc_in)
    if not pdf_inputs["compounding_per_year"]:
        pdf_inputs["compounding_per_year"] = "Effective annual rate"
    projection_result = None
    projection_label = None
    if bool(body.get("include_projection")):
        _inst2, _job2, rows = load_latest_completed_range_projection(db, user, instance_id)
        invest_pct = max(0.0, min(100.0, float(body.get("invest_pct", 15) or 15)))
        horizon_years = max(0.08, min(60.0, float(body.get("horizon_years", 5) or 5)))
        proj_rate = projection_finance.clamp_annual_rate(body.get("projection_annual_rate_pct", annual) or 0)
        projection_result = projection_finance.run_monthly_simulation(
            rows, invest_pct, proj_rate, horizon_years,
            initial_amount=max(0.0, float(body.get("projection_initial_amount") or 0)),
            contribution_timing=str(body.get("projection_contribution_timing") or "beginning"),
        )
        projection_label = (
            f"Latest long-range projection in this workspace · {invest_pct:g}% of monthly savings · "
            f"{horizon_years:g} yr horizon @ {proj_rate:g}% APR"
        )
    cur, rates, fx_at = pdf_currency_context(body.get("display_currency"), ws_currency(inst))
    try:
        pdf_bytes = investment_pdf.build_investment_calculator_pdf(
            workspace_name=inst.name,
            calculator_inputs=pdf_inputs,
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
    fname = export_naming.workspace_filename(inst, "Investment-Projection", "pdf")
    return download_response(pdf_bytes, "application/pdf", fname)


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
    ai_answer = ai_service.render_ai_answer(ai_job.technical_logs if ai_job else "")
    msg = request.query_params.get("msg", "")
    instances = workspace_service.list_user_workspaces(db, user)
    now_m = datetime.utcnow().strftime("%Y-%m")
    budgets = db.query(CategoryBudget).filter(CategoryBudget.instance_id == inst.id).all()
    budget_alerts = _budget_alerts(db, inst, now_m)
    membership = workspace_service.get_membership(db, user.id, inst.id)
    workspace_role = membership.role if membership else "viewer"
    roles = workspace_service.membership_map(db, user)
    move_targets = [
        w for w in workspace_service.list_user_workspaces(db, user, include_shared=True)
        if w.id != inst.id and ws_currency(w) == ws_currency(inst) and workspace_service.role_allows(roles.get(w.id), "create")
    ]
    return templates.TemplateResponse(request=request, name="instance.html", context={
        "request": request,
        "user": user,
        "instance": inst,
        "balances": net_worth_service.get_balances(inst.finance_db_path),
        "tax_rules": tax_service.list_rules(inst.finance_db_path),
        "tax_assignments": tax_service.assignments(inst.finance_db_path),
        "instances": instances,
        "workspace_for_nav": inst,
        "workspace_role": workspace_role,
        "can_write": workspace_service.role_allows(workspace_role, "write"),
        "move_targets": move_targets,
        "workspace_currency": ws_currency(inst),
        "err": request.query_params.get("err", ""),
        "nav_active": None,
        "state_summary": state_summary,
        "latest_output": latest_output,
        "jobs_view": jobs_view,
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
    initial_amount: float = 0.0,
    contribution_timing: str = "beginning",
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if job_id is not None:
        _inst, _job, rows = load_completed_range_projection(db, user, instance_id, int(job_id))
    else:
        _inst, _job, rows = load_latest_completed_range_projection(db, user, instance_id)
    invest_pct = max(0.0, min(100.0, float(invest_pct)))
    annual_rate = projection_finance.clamp_annual_rate(annual_rate)
    horizon_years = max(0.08, min(60.0, float(horizon_years)))
    sim = projection_finance.run_monthly_simulation(
        rows, invest_pct, annual_rate, horizon_years,
        initial_amount=max(0.0, float(initial_amount)), contribution_timing=contribution_timing,
    )
    chart = {
        "months": [r["month"] for r in sim["rows"]],
        "month_index": [r["month_index"] for r in sim["rows"]],
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
    inv_tax = None
    if sim["summary"]:
        inv_tax = tax_service.apply_investment_tax(
            float(sim["summary"].get("final_compounded_profit", 0) or 0), tax_service.investment_tax_rate(_inst.finance_db_path)
        )
        inv_tax["final_after_tax"] = round(float(sim["summary"].get("final_investment_balance", 0) or 0) - inv_tax["tax"], 2)
    return JSONResponse(
        {"summary": sim["summary"], "meta": sim["meta"], "chart": chart, "projection_tooltip": projection_tooltip, "tax": inv_tax}
    )


@app.post("/instances/{instance_id}/projection-report")
def projection_report_pdf(
    instance_id: int,
    request: Request,
    job_id: int | None = Form(None),
    invest_pct: float = Form(15.0),
    annual_rate: float = Form(5.0),
    horizon_years: float = Form(5.0),
    initial_amount: float = Form(0.0),
    contribution_timing: str = Form("beginning"),
    display_currency: str | None = Form(None),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if job_id is not None:
        inst, job, rows = load_completed_range_projection(db, user, instance_id, int(job_id))
    else:
        inst, job, rows = load_latest_completed_range_projection(db, user, instance_id)
    invest_pct = max(0.0, min(100.0, float(invest_pct)))
    annual_rate = projection_finance.clamp_annual_rate(annual_rate)
    horizon_years = max(0.08, min(60.0, float(horizon_years)))
    sim = projection_finance.run_monthly_simulation(
        rows, invest_pct, annual_rate, horizon_years,
        initial_amount=max(0.0, float(initial_amount)), contribution_timing=contribution_timing,
    )
    details = build_projection_output(rows, ws_currency(inst))
    cur, rates, fx_at = pdf_currency_context(display_currency, ws_currency(inst))
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
    fname = export_naming.workspace_filename(
        inst, "Long-Term-Projection", "pdf", start=rows[0].get("month"), end=rows[-1].get("month")
    )
    return download_response(pdf_bytes, "application/pdf", fname)


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
    cur, rates, fx_at = pdf_currency_context(display_currency, ws_currency(inst))
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
    metrics = parse_metrics(job.metrics_json)
    period: dict = {"on": job.started_at or datetime.utcnow()}
    if isinstance(metrics, dict) and metrics.get("month"):
        period = {"month": str(metrics["month"])}
    elif isinstance(metrics, list) and metrics and isinstance(metrics[0], dict) and metrics[0].get("month"):
        period = {"start": metrics[0].get("month"), "end": metrics[-1].get("month")}
    fname = export_naming.workspace_filename(inst, "Results-Summary", "pdf", **period)
    return download_response(pdf_bytes, "application/pdf", fname)


@app.get("/api/ai/status")
def api_ai_status():
    """Whether optional AI (Ollama) is configured and reachable on this deployment."""
    return JSONResponse(ai_service.ai_status(probe=True))


@app.get("/api/ai/ollama/signin-link")
def api_ai_ollama_signin_link(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return JSONResponse({"error": "auth_required"}, status_code=401)
    out = ai_service.fetch_ollama_signin_link()
    out["instructions"] = ai_service.manual_signin_instructions()
    if out.get("reason") == ai_service.REASON_DISABLED:
        return JSONResponse(out, status_code=503)
    if out.get("signin_url") or out.get("signed_in"):
        return JSONResponse(out)
    return JSONResponse(
        {"error": out.get("error", "Could not generate Ollama signin link."), "instructions": out["instructions"]},
        status_code=503,
    )


@app.post("/ai/global")
def ai_global(request: Request, question: str = Form(...), instance_id: int | None = Form(None), db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return JSONResponse({"error": "auth_required"}, status_code=401)
    context = ai_service.summarize_user_context(db, user, instance_id=instance_id)
    result = ai_service.ask_ollama(question, context)
    if result.ok:
        return JSONResponse({"answer": ai_service.render_ai_answer(result.answer or "")})
    body = result.to_error_json()
    if result.signin_url:
        body["signin_url"] = result.signin_url
    return JSONResponse(body, status_code=503)


def _entry_redirect(instance_id: int, msg: str | None = None, err: str | None = None) -> RedirectResponse:
    qs = []
    if msg:
        qs.append(f"msg={msg}")
    if err:
        qs.append(f"err={err}")
    q = ("?" + "&".join(qs)) if qs else ""
    return RedirectResponse(f"/instances/{instance_id}{q}#workspace-data", status_code=302)


def _err_code(exc: ValueError) -> str:
    text_ = str(exc).lower()
    if "category" in text_:
        return "invalid_category"
    if "end date" in text_:
        return "invalid_date_range"
    if "date" in text_:
        return "invalid_date"
    if "name" in text_:
        return "invalid_name"
    return "invalid_amount"


@app.post("/instances/{instance_id}/income")
def add_income(
    instance_id: int,
    request: Request,
    nome: str = Form(...),
    valor: str = Form(...),
    recurrence: str = Form("monthly"),
    start_date: str = Form(""),
    end_date: str = Form(""),
    tax_ids: list[str] = Form(default=[]),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id, action="create")
    try:
        amount = numeric_input.parse_positive_decimal(valor)
        instance_service.validate_date_window(start_date, end_date)
    except ValueError as exc:
        return _entry_redirect(instance_id, err=_err_code(exc))

    def _add():
        res = instance_service.add_income(
            inst.finance_db_path, nome.strip(), amount, recurrence=recurrence, start_date=start_date, end_date=end_date
        )
        res["tax_ids"] = tax_service.set_income_taxes(inst.finance_db_path, "recurring", res["id"], tax_ids)
        return res

    run_job(db, user, inst, "add_income", _add)
    return _entry_redirect(instance_id)


@app.post("/instances/{instance_id}/expense")
def add_expense(
    instance_id: int,
    request: Request,
    nome: str = Form(...),
    valor: str = Form(...),
    recurrence: str = Form("monthly"),
    category: str = Form("Other"),
    start_date: str = Form(""),
    end_date: str = Form(""),
    expense_type: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id, action="create")
    try:
        amount = numeric_input.parse_positive_decimal(valor)
        instance_service.validate_date_window(start_date, end_date)
    except ValueError as exc:
        return _entry_redirect(instance_id, err=_err_code(exc))
    run_job(
        db,
        user,
        inst,
        "add_expense",
        lambda: instance_service.add_expense(
            inst.finance_db_path, nome.strip(), amount, recurrence=recurrence, category=category,
            start_date=start_date, end_date=end_date, expense_type=expense_type,
        ),
    )
    return _entry_redirect(instance_id)


@app.post("/instances/{instance_id}/savings-deposit")
def add_savings_deposit(
    instance_id: int,
    request: Request,
    data: str = Form(...),
    valor: str = Form(...),
    nome: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id, action="create")
    try:
        amount = numeric_input.parse_positive_decimal(valor)
        day = instance_service.parse_iso_date(data, required=True)
    except ValueError as exc:
        return _entry_redirect(instance_id, err=_err_code(exc))
    run_job(
        db,
        user,
        inst,
        "add_savings",
        lambda: instance_service.add_savings_deposit(inst.finance_db_path, day, amount, nome=nome),
    )
    return _entry_redirect(instance_id)


@app.post("/instances/{instance_id}/quick-oneoff")
def quick_oneoff(
    instance_id: int,
    request: Request,
    amount: str = Form(...),
    description: str = Form(...),
    txn_type: str = Form(...),
    txn_date: str = Form(""),
    category: str | None = Form(None),
    next_url: str = Form("/dashboard"),
    db: Session = Depends(get_db),
):
    """Quick-add one-time transaction from the global + button."""
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id, action="create")
    try:
        parsed_amount = numeric_input.parse_positive_decimal(amount)
    except ValueError:
        parsed_amount = None
    errs = dashboard_metrics.validate_quick_oneoff(parsed_amount, description, txn_type)
    safe_next = next_url if next_url.startswith("/") and not next_url.startswith("//") else "/dashboard"
    try:
        date_s = instance_service.parse_iso_date(txn_date) or datetime.utcnow().strftime("%Y-%m-%d")
    except ValueError:
        errs = errs or ["date"]
        date_s = ""
    if errs:
        sep = "&" if "?" in safe_next else "?"
        return RedirectResponse(f"{safe_next}{sep}quick_err=1", status_code=302)
    tt = "income" if str(txn_type).lower() == "income" else "expense"
    cat = category
    if tt == "expense" and (cat or "").strip() not in instance_service.ONEOFF_CATEGORIES:
        cat = "Other"

    def _add():
        return instance_service.add_oneoff(
            inst.finance_db_path,
            date_s,
            description.strip(),
            parsed_amount,
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
    valor: str = Form(...),
    txn_type: str = Form("expense"),
    category: str | None = Form(None),
    expense_type: str = Form(""),
    tax_ids: list[str] = Form(default=[]),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id, action="create")
    try:
        parsed_valor = numeric_input.parse_positive_decimal(valor)
        day = instance_service.parse_iso_date(data, required=True)
    except ValueError as exc:
        return _entry_redirect(instance_id, err=_err_code(exc))
    tt = "income" if str(txn_type).lower() == "income" else "expense"
    if tt == "expense" and (category or "").strip() not in instance_service.ONEOFF_CATEGORIES:
        return RedirectResponse(f"/instances/{instance_id}?msg=oneoff_category_required", status_code=302)

    def _add():
        res = instance_service.add_oneoff(
            inst.finance_db_path, day, nome.strip(), parsed_valor, txn_type=tt, category=category, expense_type=expense_type
        )
        if tt == "income":
            res["tax_ids"] = tax_service.set_income_taxes(inst.finance_db_path, "oneoff", res["id"], tax_ids)
        return res

    run_job(db, user, inst, "add_oneoff", _add)
    return _entry_redirect(instance_id)


def _resolve_move_target(db: Session, user: User, inst: DatabaseInstance, target_workspace_id: str | None) -> DatabaseInstance | None:
    """Optional 'associated workspace' change; only to a workspace the user can write to, same currency."""
    raw = (target_workspace_id or "").strip()
    if not raw:
        return None
    try:
        tid = int(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid target workspace.") from None
    if tid == inst.id:
        return None
    target = require_instance(db, user, tid, action="create")
    if ws_currency(target) != ws_currency(inst):
        raise HTTPException(
            status_code=400,
            detail=f"Entries can only move between workspaces with the same currency ({ws_currency(inst)} → {ws_currency(target)}).",
        )
    return target


def _finish_edit(
    db: Session, user: User, inst: DatabaseInstance, kind: str, item_id: int, result: dict | None, target: DatabaseInstance | None
) -> RedirectResponse:
    if result is None:
        return _entry_redirect(inst.id, msg=f"{kind}_not_found")
    run_job(db, user, inst, f"update_{kind}", lambda: result)
    if target is not None:
        moved = instance_service.move_entry(inst.finance_db_path, target.finance_db_path, kind, item_id, deleted_by=user.id)
        if moved and kind in ("income", "oneoff"):
            tax_service.clear_income_taxes(inst.finance_db_path, "recurring" if kind == "income" else "oneoff", item_id)
        if moved:
            run_job(db, user, target, f"update_{kind}", lambda: {**moved, "moved_from_workspace": inst.name})
            return _entry_redirect(inst.id, msg="entry_moved")
    return _entry_redirect(inst.id, msg="entry_updated")


@app.post("/instances/{instance_id}/income/{item_id}/edit")
def edit_income(
    instance_id: int,
    item_id: int,
    request: Request,
    nome: str = Form(...),
    valor: str = Form(...),
    recurrence: str = Form("monthly"),
    start_date: str = Form(""),
    end_date: str = Form(""),
    ended: str = Form(""),
    target_workspace_id: str = Form(""),
    tax_ids: list[str] = Form(default=[]),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id, action="edit")
    target = _resolve_move_target(db, user, inst, target_workspace_id)
    try:
        amount = numeric_input.parse_positive_decimal(valor)
        result = instance_service.update_income(
            inst.finance_db_path, item_id, nome=nome, valor=amount, recurrence=recurrence,
            start_date=start_date, end_date=end_date, ended=bool(ended),
        )
    except ValueError as exc:
        return _entry_redirect(instance_id, err=_err_code(exc))
    if result is not None:
        result["tax_ids"] = tax_service.set_income_taxes(inst.finance_db_path, "recurring", item_id, tax_ids)
    return _finish_edit(db, user, inst, "income", item_id, result, target)


@app.post("/instances/{instance_id}/expense/{item_id}/edit")
def edit_expense(
    instance_id: int,
    item_id: int,
    request: Request,
    nome: str = Form(...),
    valor: str = Form(...),
    recurrence: str = Form("monthly"),
    category: str = Form("Other"),
    start_date: str = Form(""),
    end_date: str = Form(""),
    expense_type: str = Form(""),
    ended: str = Form(""),
    target_workspace_id: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id, action="edit")
    target = _resolve_move_target(db, user, inst, target_workspace_id)
    try:
        amount = numeric_input.parse_positive_decimal(valor)
        result = instance_service.update_expense(
            inst.finance_db_path, item_id, nome=nome, valor=amount, recurrence=recurrence, category=category,
            start_date=start_date, end_date=end_date, expense_type=expense_type, ended=bool(ended),
        )
    except ValueError as exc:
        return _entry_redirect(instance_id, err=_err_code(exc))
    return _finish_edit(db, user, inst, "expense", item_id, result, target)


@app.post("/instances/{instance_id}/oneoff/{item_id}/edit")
def edit_oneoff(
    instance_id: int,
    item_id: int,
    request: Request,
    data: str = Form(...),
    nome: str = Form(...),
    valor: str = Form(...),
    txn_type: str = Form("expense"),
    category: str | None = Form(None),
    expense_type: str = Form(""),
    target_workspace_id: str = Form(""),
    tax_ids: list[str] = Form(default=[]),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id, action="edit")
    target = _resolve_move_target(db, user, inst, target_workspace_id)
    try:
        amount = numeric_input.parse_positive_decimal(valor)
        result = instance_service.update_oneoff(
            inst.finance_db_path, item_id, data=data, nome=nome, valor=amount, txn_type=txn_type,
            category=category, expense_type=expense_type,
        )
    except ValueError as exc:
        return _entry_redirect(instance_id, err=_err_code(exc))
    if result is not None:
        is_income = str(txn_type).lower() == "income"
        result["tax_ids"] = tax_service.set_income_taxes(inst.finance_db_path, "oneoff", item_id, tax_ids if is_income else [])
    return _finish_edit(db, user, inst, "oneoff", item_id, result, target)


@app.post("/instances/{instance_id}/income/{item_id}/delete")
def delete_income(instance_id: int, item_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id, action="delete")
    deleted = instance_service.delete_income(inst.finance_db_path, item_id)
    if not deleted:
        return RedirectResponse(f"/instances/{instance_id}?msg=income_not_found", status_code=302)
    tax_service.clear_income_taxes(inst.finance_db_path, "recurring", item_id)
    run_job(db, user, inst, "delete_income", lambda: {"deleted": {"name": deleted[0], "amount": deleted[1]}})
    return RedirectResponse(f"/instances/{instance_id}?msg=income_deleted", status_code=302)


@app.post("/instances/{instance_id}/expense/{item_id}/delete")
def delete_expense(instance_id: int, item_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id, action="delete")
    deleted = instance_service.delete_expense(inst.finance_db_path, item_id)
    if not deleted:
        return RedirectResponse(f"/instances/{instance_id}?msg=expense_not_found", status_code=302)
    run_job(db, user, inst, "delete_expense", lambda: {"deleted": {"name": deleted[0], "amount": deleted[1]}})
    return RedirectResponse(f"/instances/{instance_id}?msg=expense_deleted", status_code=302)


@app.post("/instances/{instance_id}/oneoff/{item_id}/delete")
def delete_oneoff(instance_id: int, item_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id, action="delete")
    run_job(db, user, inst, "delete_oneoff", lambda: {"deleted": instance_service.delete_oneoff(inst.finance_db_path, item_id)})
    tax_service.clear_income_taxes(inst.finance_db_path, "oneoff", item_id)
    return RedirectResponse(f"/instances/{instance_id}?msg=transaction_deleted", status_code=302)


@app.post("/instances/{instance_id}/absence")
def add_absence(instance_id: int, request: Request, data: str = Form(...), modulo: str = Form(...), horas: float = Form(...), observacao: str = Form(""), db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user.enable_iefp_mode:
        raise HTTPException(status_code=403)
    inst = require_instance(db, user, instance_id, action="create")
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
        context = ai_service.summarize_workspace_context(db, user, inst)
        result = ai_service.ask_ollama(question, context)
        answer = ai_service.render_ai_answer(result.answer if result.ok else (result.error or ""))
        return {"question": question, "answer": answer}

    run_job(db, user, inst, "ai_chat", _call_ai)
    return RedirectResponse(f"/instances/{instance_id}", status_code=302)


@app.get("/api/build-info")
def api_build_info():
    """Public build identity (version, commit) for post-image-update UX and ops probes."""
    return JSONResponse(build_info.build_info_dict())


@app.post("/api/server/restart")
def api_server_restart(request: Request, db: Session = Depends(get_db)):
    """Ask the host-side restart helper to rebuild and restart the Docker deployment."""
    user = require_user(request, db)
    if not server_restart_service.watcher_online():
        raise HTTPException(
            status_code=503,
            detail="The restart helper isn't running on the host. Install it once with: sudo make install-restart-helper",
        )
    st = server_restart_service.request_restart(user.username)
    log.info("server restart requested by %s (queued=%s, helper_online=%s)", user.username, st["queued"], st["watcher_online"])
    return JSONResponse(st)


@app.get("/api/server/restart/status")
def api_server_restart_status(request: Request, db: Session = Depends(get_db)):
    require_user(request, db)
    return JSONResponse(server_restart_service.status())


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
    """Bundled historical series for VWCE/BTC/ETH (EUR). Cached server-side."""
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


def _user_instances_and_primary(db: Session, user: User, request: Request | None = None) -> tuple[list[DatabaseInstance], DatabaseInstance | None]:
    return workspace_service.resolve_active_workspace(db, user, request)


def _resolve_workspace(
    db: Session, user: User, instance_id: int | None, request: Request | None = None
) -> tuple[list[DatabaseInstance], DatabaseInstance | None]:
    instances, primary = _user_instances_and_primary(db, user, request)
    if instance_id is not None:
        inst = require_instance(db, user, instance_id)
        return instances, inst
    return instances, primary


@app.get("/timeline", response_class=HTMLResponse)
def timeline_page(
    request: Request,
    db: Session = Depends(get_db),
    instance_id: int | None = None,
    month: str | None = None,
    event_type: str | None = None,
):
    user = require_user(request, db)
    instances, inst = _resolve_workspace(db, user, instance_id)
    events: list = []
    grouped: list = []
    if inst:
        eom_summary_service.ensure_eom_snapshots(db, inst, user, max_months=12)
        events = financial_timeline_service.build_timeline_events(
            db,
            user,
            inst,
            month_filter=month or None,
            type_filter=event_type or None,
            include_iefp=bool(user.enable_iefp_mode),
        )
        grouped = financial_timeline_service.group_events_by_date(events)
    snapshots = monthly_snapshot_service.list_monthly_snapshots(db, inst.id) if inst else []
    return templates.TemplateResponse(
        request=request,
        name="timeline.html",
        context={
            "request": request,
            "user": user,
            "instances": instances,
            "instance": inst,
            "workspace_for_nav": inst or (instances[0] if instances else None),
            "nav_active": "timeline",
            "show_back_to_dashboard": True,
            "events": events,
            "grouped_events": grouped,
            "month_filter": month or "",
            "event_type_filter": event_type or "",
            "snapshots": snapshots,
        },
    )


@app.get("/eom-summary", response_class=HTMLResponse)
def eom_summary_page(
    request: Request,
    db: Session = Depends(get_db),
    instance_id: int | None = None,
    year: int | None = None,
    month: int | None = None,
    month_q: str | None = None,
):
    user = require_user(request, db)
    instances, inst = _resolve_workspace(db, user, instance_id)
    summary = None
    snapshots: list = []
    if inst:
        sync = eom_summary_service.ensure_eom_snapshots(db, inst, user, max_months=24)
        snapshots = monthly_snapshot_service.list_monthly_snapshots(db, inst.id)
        today = date.today()
        if month_q and len(month_q) >= 7:
            sel_y, sel_m = monthly_snapshot_service.month_str_to_parts(month_q[:7])
        else:
            sel_y = year or today.year
            sel_m = month or today.month
        summary = eom_summary_service.resolve_summary_for_display(db, inst, user, sel_y, sel_m)
        summary["_sync"] = sync
    return templates.TemplateResponse(
        request=request,
        name="eom_summary.html",
        context={
            "request": request,
            "user": user,
            "instances": instances,
            "instance": inst,
            "workspace_for_nav": inst or (instances[0] if instances else None),
            "nav_active": "eom",
            "show_back_to_dashboard": True,
            "snapshots": snapshots,
            "summary": summary,
            "selected_year": year,
            "selected_month": month,
        },
    )


@app.post("/eom-summary/generate")
def eom_summary_generate(
    request: Request,
    db: Session = Depends(get_db),
    instance_id: int = Form(...),
    year: int = Form(...),
    month: int = Form(...),
):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id)
    monthly_snapshot_service.generate_monthly_snapshot(db, inst, year, month, user)
    return RedirectResponse(f"/eom-summary?instance_id={instance_id}&year={year}&month={month}", status_code=302)


@app.get("/eom-summary/current/pdf")
def eom_summary_current_pdf(
    request: Request,
    db: Session = Depends(get_db),
    instance_id: int | None = None,
    display_currency: str | None = None,
):
    user = require_user(request, db)
    _, inst = _resolve_workspace(db, user, instance_id)
    if not inst:
        raise HTTPException(status_code=404, detail="No workspace")
    now = datetime.utcnow()
    summary = eom_summary_service.build_live_preview(db, inst, user)
    is_preview = bool(summary.get("is_preview"))
    cur, rates, fx_at = pdf_currency_context(display_currency, ws_currency(inst))
    try:
        pdf_bytes = eom_summary_pdf.build_eom_summary_pdf(
            workspace_name=inst.name,
            summary=summary,
            is_preview=is_preview,
            display_currency=cur,
            fx_rates=rates,
            fx_updated_at=fx_at,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="PDF export needs optional packages: pip install reportlab",
        ) from exc
    fname = export_naming.workspace_filename(inst, "EOM-Preview", "pdf", month=now.strftime("%Y-%m"))
    return download_response(pdf_bytes, "application/pdf", fname)


@app.get("/eom-summary/{year}/{month}/pdf")
def eom_summary_month_pdf(
    year: int,
    month: int,
    request: Request,
    db: Session = Depends(get_db),
    instance_id: int | None = None,
    display_currency: str | None = None,
    preview: int = 0,
):
    user = require_user(request, db)
    _, inst = _resolve_workspace(db, user, instance_id)
    if not inst:
        raise HTTPException(status_code=404, detail="No workspace")
    today = date.today()
    is_current = year == today.year and month == today.month
    row = monthly_snapshot_service.get_monthly_snapshot(db, inst.id, year, month)
    if row and not preview:
        summary = monthly_snapshot_service.snapshot_row_to_payload(row)
        is_preview = False
    else:
        summary = eom_summary_service.build_live_preview(
            db, inst, user, month_str=monthly_snapshot_service.parts_to_month_str(year, month)
        )
        is_preview = is_current or bool(preview)
    cur, rates, fx_at = pdf_currency_context(display_currency, ws_currency(inst))
    try:
        pdf_bytes = eom_summary_pdf.build_eom_summary_pdf(
            workspace_name=inst.name,
            summary=summary,
            is_preview=is_preview,
            display_currency=cur,
            fx_rates=rates,
            fx_updated_at=fx_at,
        )
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="PDF export needs optional packages: pip install reportlab") from exc
    tag = "EOM-Preview" if is_preview else "EOM-Summary"
    fname = export_naming.workspace_filename(inst, tag, "pdf", month=f"{year:04d}-{month:02d}")
    return download_response(pdf_bytes, "application/pdf", fname)


@app.get("/wishlist", response_class=HTMLResponse)
def wishlist_page(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    instances, primary = workspace_service.resolve_active_workspace(db, user, request)
    now_m = datetime.utcnow().strftime("%Y-%m")
    mt = _user_month_totals(user, [primary] if primary else [], now_m)
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
    price_eur: str = Form(...),
    priority: str = Form("medium"),
    deadline: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not name.strip():
        return RedirectResponse("/wishlist?err=name", status_code=302)
    try:
        price = numeric_input.parse_positive_decimal(price_eur)
    except ValueError:
        return RedirectResponse("/wishlist?err=invalid_price", status_code=302)
    wishlist_service.add_item(db, user.id, name, price, priority=priority, deadline=deadline or None)
    return RedirectResponse("/wishlist", status_code=302)


@app.post("/wishlist/{item_id}/delete")
def wishlist_delete(item_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    wishlist_service.delete_item(db, user.id, item_id)
    return RedirectResponse("/wishlist", status_code=302)


@app.get("/api/expenses/panel")
def api_expenses_panel(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return JSONResponse({"error": "auth_required"}, status_code=401)
    _all, active = workspace_service.resolve_active_workspace(db, user, request)
    instances = [active] if active else []
    now_m = datetime.utcnow().strftime("%Y-%m")
    month_rows = [
        instance_service.month_summary(
            ins.finance_db_path,
            ins.logic_db_path,
            now_m,
            include_iefp=bool(user.enable_iefp_mode),
        )
        for ins in instances
    ]
    month_totals = dashboard_metrics.aggregate_current_month_totals(month_rows) if month_rows else {}
    payload = expense_panel.build_expense_panel_payload(instances, month_totals=month_totals)
    return JSONResponse(payload)


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
    _instances, primary = workspace_service.resolve_active_workspace(db, user, request)
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
    instances = workspace_service.list_user_workspaces(db, user)
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
        net_worth=net_worth_service.summary(inst.finance_db_path),
    )
    return JSONResponse(data)


@app.get("/instances/{instance_id}/analysis", response_class=HTMLResponse)
def analysis_page(instance_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst, member = workspace_service.require_workspace(db, user, instance_id, "read")
    instances = workspace_service.list_user_workspaces(db, user)
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
        net_worth=net_worth_service.summary(inst.finance_db_path),
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
            "balances_summary": net_worth_service.summary(inst.finance_db_path),
            "balances_can_edit": workspace_service.role_allows(member.role, "edit"),
        },
    )


@app.get("/instances/{instance_id}/savings-calculator", response_class=HTMLResponse)
def savings_calculator_page(instance_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id)
    instances = workspace_service.list_user_workspaces(db, user)
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
            "balances": net_worth_service.get_balances(inst.finance_db_path),
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
        if shared_workspace_service.is_shared(inst):
            summary = shared_workspace_service.combined_saved_expenses(db, inst, month)
        else:
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
    cur, rates, fx_at = pdf_currency_context(body.get("display_currency"), ws_currency(inst))
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
    fname = export_naming.workspace_filename(inst, "Emergency-Fund", "pdf")
    return download_response(pdf_bytes, "application/pdf", fname)


# ---------------------------------------------------------------------------
# Net worth, emergency fund and invested balances
# ---------------------------------------------------------------------------


@app.get("/instances/{instance_id}/net-worth", response_class=HTMLResponse)
def net_worth_page(instance_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst, member = workspace_service.require_workspace(db, user, instance_id, "read")
    instances = workspace_service.list_user_workspaces(db, user)
    return templates.TemplateResponse(
        request=request,
        name="net_worth.html",
        context={
            "request": request,
            "user": user,
            "instance": inst,
            "instances": instances,
            "workspace_for_nav": inst,
            "nav_active": "net_worth",
            "show_back_to_dashboard": True,
            "net_worth": net_worth_service.summary(inst.finance_db_path, with_history=True),
            "can_edit": workspace_service.role_allows(member.role, "edit"),
        },
    )


@app.get("/instances/{instance_id}/api/net-worth")
def api_net_worth(instance_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id)
    return JSONResponse(net_worth_service.summary(inst.finance_db_path, with_history=True))


async def _json_body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        body = None
    if isinstance(body, dict):
        return body
    form = await request.form()
    return dict(form)


@app.post("/instances/{instance_id}/api/balances")
async def api_set_balances(instance_id: int, request: Request, db: Session = Depends(get_db)):
    """Set the emergency fund and/or invested amount. Missing or empty fields stay unchanged."""
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id, action="edit")
    body = await _json_body(request)
    try:
        values = {k: net_worth_service.parse_amount(body.get(k), allow_empty=True) for k in net_worth_service.BALANCE_KEYS}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    net_worth_service.set_balances(inst.finance_db_path, **values)
    inst.last_activity_at = datetime.utcnow()
    db.add(inst)
    db.commit()
    return JSONResponse(net_worth_service.summary(inst.finance_db_path, with_history=True))


@app.post("/instances/{instance_id}/api/net-worth/items")
async def api_net_worth_add(instance_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id, action="create")
    body = await _json_body(request)
    try:
        net_worth_service.add_item(
            inst.finance_db_path, body.get("kind", ""), body.get("name", ""), body.get("amount"),
            category=body.get("category"), note=body.get("note"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(net_worth_service.summary(inst.finance_db_path, with_history=True))


@app.post("/instances/{instance_id}/api/net-worth/items/{item_id}")
async def api_net_worth_update(instance_id: int, item_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id, action="edit")
    body = await _json_body(request)
    try:
        net_worth_service.update_item(
            inst.finance_db_path, item_id, body.get("kind", ""), body.get("name", ""), body.get("amount"),
            category=body.get("category"), note=body.get("note"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return JSONResponse(net_worth_service.summary(inst.finance_db_path, with_history=True))


@app.delete("/instances/{instance_id}/api/net-worth/items/{item_id}")
def api_net_worth_delete(instance_id: int, item_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id, action="delete")
    try:
        net_worth_service.delete_item(inst.finance_db_path, item_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return JSONResponse(net_worth_service.summary(inst.finance_db_path, with_history=True))


# ---------------------------------------------------------------------------
# Taxes
# ---------------------------------------------------------------------------


def _taxes_payload(user: User, inst: DatabaseInstance) -> dict:
    month = datetime.utcnow().strftime("%Y-%m")
    sm = instance_service.month_summary(inst.finance_db_path, inst.logic_db_path, month, include_iefp=bool(user.enable_iefp_mode))
    items = instance_service.list_finance_items(inst.finance_db_path)
    return {
        "rules": tax_service.list_rules(inst.finance_db_path),
        "incomes": [
            {"kind": "recurring", "id": i["id"], "name": i["name"], "amount": i["amount"], "recurrence": i.get("recurrence")}
            for i in items["incomes"]
            if not i.get("ended")
        ],
        "current_month": {
            "month": month,
            "salary": round(float(sm.get("extras", 0) or 0) + float(sm.get("iefp", 0) or 0), 2),
            "oneoff_income": round(float(sm.get("oneoff_income_total", 0) or 0), 2),
            "taxes": sm.get("taxes"),
            "income_pre_tax": sm.get("income_pre_tax"),
            "income_after_tax": sm.get("income_after_tax"),
            "savings_pre_tax": sm.get("estimated_savings_pre_tax"),
            "savings_after_tax": sm.get("estimated_savings"),
        },
        "investment_tax_rate": tax_service.investment_tax_rate(inst.finance_db_path),
    }


@app.get("/instances/{instance_id}/taxes", response_class=HTMLResponse)
def taxes_page(instance_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst, member = workspace_service.require_workspace(db, user, instance_id, "read")
    instances = workspace_service.list_user_workspaces(db, user)
    return templates.TemplateResponse(
        request=request,
        name="taxes.html",
        context={
            "request": request,
            "user": user,
            "instance": inst,
            "instances": instances,
            "workspace_for_nav": inst,
            "nav_active": "taxes",
            "show_back_to_dashboard": True,
            "taxes": _taxes_payload(user, inst),
            "can_edit": workspace_service.role_allows(member.role, "edit"),
        },
    )


@app.get("/instances/{instance_id}/api/taxes")
def api_taxes(instance_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id)
    return JSONResponse(_taxes_payload(user, inst))


@app.post("/instances/{instance_id}/api/taxes")
async def api_taxes_add(instance_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id, action="create")
    body = await _json_body(request)
    try:
        rule_id = tax_service.add_rule(
            inst.finance_db_path, body.get("name", ""), body.get("rate_pct"), body.get("fixed_monthly"),
            body.get("on_investments"), body.get("note"),
        )
        # Optional: assign the new tax to incomes straight away.
        assignments = tax_service.assignments(inst.finance_db_path)
        for iid in tax_service.parse_tax_ids(body.get("income_ids") or []):
            current = assignments.get(f"recurring:{iid}", [])
            tax_service.set_income_taxes(inst.finance_db_path, "recurring", iid, current + [rule_id])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(_taxes_payload(user, inst))


@app.post("/instances/{instance_id}/api/taxes/{rule_id}")
async def api_taxes_update(instance_id: int, rule_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id, action="edit")
    body = await _json_body(request)
    try:
        if set(body) == {"active"}:
            tax_service.set_active(inst.finance_db_path, rule_id, bool(body["active"]))
        else:
            tax_service.update_rule(
                inst.finance_db_path, rule_id, body.get("name", ""), body.get("rate_pct"), body.get("fixed_monthly"),
                body.get("on_investments"), body.get("note"), active=bool(body.get("active", True)),
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return JSONResponse(_taxes_payload(user, inst))


@app.delete("/instances/{instance_id}/api/taxes/{rule_id}")
def api_taxes_delete(instance_id: int, rule_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id, action="delete")
    try:
        tax_service.delete_rule(inst.finance_db_path, rule_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return JSONResponse(_taxes_payload(user, inst))


@app.post("/instances/{instance_id}/bank-statements/upload")
async def bank_statement_upload(
    instance_id: int,
    request: Request,
    db: Session = Depends(get_db),
    file: UploadFile = File(...),
    statement_month: str = Form(""),
    bank_name: str | None = Form(None),
):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id, action="create")
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
    return JSONResponse(
        {
            "id": row.id,
            "statement_month": row.statement_month,
            "filename": row.original_filename,
            "detection": getattr(row, "detection", None),
        }
    )


@app.get("/instances/{instance_id}/bank-statements/{statement_id}/file")
def bank_statement_download(instance_id: int, statement_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id)
    row = bank_statement_service.get_owned(db, user.id, statement_id)
    if not row or row.instance_id != instance_id:
        raise HTTPException(status_code=404)
    path = ROOT / row.storage_rel_path
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File missing")
    # Keep the same name the user uploaded (and sees in the Reports list).
    fname = row.original_filename or export_naming.workspace_filename(
        inst, "Bank-Statement", "pdf", month=row.statement_month
    )
    return FileResponse(path, filename=fname, media_type="application/pdf")


@app.delete("/instances/{instance_id}/bank-statements/{statement_id}")
def bank_statement_delete(instance_id: int, statement_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    require_instance(db, user, instance_id, action="delete")
    row = bank_statement_service.get_owned(db, user.id, statement_id)
    if not row or row.instance_id != instance_id:
        raise HTTPException(status_code=404)
    bank_statement_service.delete_statement(db, ROOT, row)
    return JSONResponse({"deleted": True})


@app.patch("/instances/{instance_id}/bank-statements/{statement_id}")
async def bank_statement_rename(instance_id: int, statement_id: int, request: Request, db: Session = Depends(get_db)):
    """Rename the file (display/download name only — the stored PDF is untouched)."""
    user = require_user(request, db)
    require_instance(db, user, instance_id, action="edit")
    row = bank_statement_service.get_owned(db, user.id, statement_id)
    if not row or row.instance_id != instance_id:
        raise HTTPException(status_code=404)
    body = await request.json()
    err = bank_statement_service.rename_statement(db, row, str((body or {}).get("filename") or ""))
    if err:
        raise HTTPException(status_code=400, detail=err)
    return JSONResponse({"id": row.id, "filename": row.original_filename})


# --- User-defined document categories (Reports → Other documents) ---


def _doc_json(d) -> dict:
    return {
        "id": d.id,
        "category_id": d.category_id,
        "doc_month": d.doc_month,
        "source": d.source,
        "filename": d.original_filename,
        "uploaded_at": d.created_at.isoformat() + "Z" if d.created_at else None,
        "file_size": d.file_size,
    }


def _require_doc_category(db: Session, instance_id: int, category_id: int):
    cat = document_service.get_category(db, instance_id, category_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found.")
    return cat


def _require_document(db: Session, instance_id: int, document_id: int):
    row = document_service.get_document(db, instance_id, document_id)
    if not row:
        raise HTTPException(status_code=404)
    return row


@app.get("/instances/{instance_id}/document-categories")
def document_categories_list(instance_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id)
    return JSONResponse(
        {
            "items": [
                {"id": c.id, "name": c.name, "documents": [_doc_json(d) for d in document_service.list_documents(db, c.id)]}
                for c in document_service.list_categories(db, inst.id)
            ]
        }
    )


@app.post("/instances/{instance_id}/document-categories")
async def document_category_create(instance_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id, action="create")
    body = await request.json()
    cat, err = document_service.create_category(db, inst.id, str((body or {}).get("name") or ""))
    if err or not cat:
        raise HTTPException(status_code=400, detail=err or "Could not create category.")
    return JSONResponse({"id": cat.id, "name": cat.name})


@app.patch("/instances/{instance_id}/document-categories/{category_id}")
async def document_category_rename(instance_id: int, category_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    require_instance(db, user, instance_id, action="edit")
    cat = _require_doc_category(db, instance_id, category_id)
    body = await request.json()
    err = document_service.rename_category(db, cat, str((body or {}).get("name") or ""))
    if err:
        raise HTTPException(status_code=400, detail=err)
    return JSONResponse({"id": cat.id, "name": cat.name})


@app.delete("/instances/{instance_id}/document-categories/{category_id}")
def document_category_delete(instance_id: int, category_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    require_instance(db, user, instance_id, action="delete")
    cat = _require_doc_category(db, instance_id, category_id)
    document_service.delete_category(db, ROOT, cat)
    return JSONResponse({"deleted": True})


@app.post("/instances/{instance_id}/document-categories/{category_id}/upload")
async def document_upload(
    instance_id: int,
    category_id: int,
    request: Request,
    db: Session = Depends(get_db),
    file: UploadFile = File(...),
    doc_month: str = Form(""),
    source: str | None = Form(None),
):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id, action="create")
    cat = _require_doc_category(db, instance_id, category_id)
    if not file.filename or not str(file.filename).lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF uploads are allowed.")
    content = await file.read()
    row, err = document_service.save_document(
        db, ROOT, inst, cat, user.id, content=content, original_filename=file.filename, doc_month=doc_month, source=source
    )
    if err or not row:
        log.warning("document upload rejected: %s", err)
        raise HTTPException(status_code=400, detail=err or "Upload failed")
    return JSONResponse(_doc_json(row))


@app.get("/instances/{instance_id}/documents/{document_id}/file")
def document_download(instance_id: int, document_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    require_instance(db, user, instance_id)
    row = _require_document(db, instance_id, document_id)
    path = ROOT / row.storage_rel_path
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File missing")
    return FileResponse(path, filename=row.original_filename, media_type="application/pdf")


@app.patch("/instances/{instance_id}/documents/{document_id}")
async def document_rename(instance_id: int, document_id: int, request: Request, db: Session = Depends(get_db)):
    """Rename the file (display/download name only — the stored PDF is untouched)."""
    user = require_user(request, db)
    require_instance(db, user, instance_id, action="edit")
    row = _require_document(db, instance_id, document_id)
    body = await request.json()
    err = document_service.rename_document(db, row, str((body or {}).get("filename") or ""))
    if err:
        raise HTTPException(status_code=400, detail=err)
    return JSONResponse(_doc_json(row))


@app.delete("/instances/{instance_id}/documents/{document_id}")
def document_delete(instance_id: int, document_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    require_instance(db, user, instance_id, action="delete")
    row = _require_document(db, instance_id, document_id)
    document_service.delete_document(db, ROOT, row)
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
    cur = ws_currency(inst)
    w.writerow(["type", "id", "date", "name", "amount", "category", "txn_type", "currency"])
    for i in items["incomes"]:
        w.writerow(["recurring_income", i["id"], "", i["name"], i["amount"], "", "income", cur])
    for i in items["expenses"]:
        w.writerow(["recurring_expense", i["id"], "", i["name"], i["amount"], "", "expense", cur])
    for t in items["oneoffs"]:
        w.writerow(["oneoff", t["id"], t["date"], t["name"], t["amount"], t["category"], t["txn_type"], cur])
    data = buf.getvalue().encode("utf-8")
    dates = sorted(str(t["date"])[:10] for t in items["oneoffs"] if t.get("date"))
    period = {"start": dates[0], "end": dates[-1]} if dates else {}
    fname = export_naming.workspace_filename(inst, "Transactions", "csv", **period)
    return download_response(data, "text/csv", fname)


@app.get("/instances/{instance_id}/export/transactions.json")
def export_transactions_json(instance_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id)
    items = instance_service.list_finance_items(inst.finance_db_path)
    payload = {
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "workspace": inst.name,
        "workspace_id": inst.id,
        "currency": ws_currency(inst),
        "data": items,
    }
    fname = export_naming.workspace_filename(inst, "Transactions", "json")
    return download_response(json.dumps(payload, indent=2, default=str).encode("utf-8"), "application/json", fname)


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
    monthly_limit_eur: str = Form(...),
):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id, action="write")
    cat = (category or "").strip()
    if cat not in instance_service.ONEOFF_CATEGORIES:
        raise HTTPException(status_code=400, detail="Invalid category")
    try:
        lim = max(0.0, numeric_input.parse_decimal(monthly_limit_eur, allow_negative=False, min_value=0))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid monthly limit") from None
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
    inst = require_instance(db, user, instance_id, action="write")
    row = db.query(CategoryBudget).filter(CategoryBudget.id == budget_id, CategoryBudget.instance_id == inst.id).first()
    if row:
        db.delete(row)
        db.commit()
    return RedirectResponse(f"/instances/{instance_id}", status_code=302)


@app.post("/instances/{instance_id}/savings/{item_id}/delete")
def delete_savings_deposit(instance_id: int, item_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id, action="delete")
    result = instance_service.delete_savings_deposit(inst.finance_db_path, item_id, deleted_by=user.id)
    if not result:
        return RedirectResponse(f"/instances/{instance_id}?msg=savings_not_found#workspace-data", status_code=302)
    run_job(db, user, inst, "delete_savings", lambda: {"deleted": result})
    return RedirectResponse(f"/instances/{instance_id}?msg=savings_deleted#workspace-data", status_code=302)


@app.post("/instances/{instance_id}/savings/{item_id}/edit")
def edit_savings_deposit(
    instance_id: int,
    item_id: int,
    request: Request,
    data: str = Form(...),
    valor: str = Form(...),
    nome: str = Form(""),
    target_workspace_id: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id, action="edit")
    target = _resolve_move_target(db, user, inst, target_workspace_id)
    try:
        amount = numeric_input.parse_positive_decimal(valor)
        day = instance_service.parse_iso_date(data, required=True)
    except ValueError as exc:
        return _entry_redirect(instance_id, err=_err_code(exc))
    result = instance_service.update_savings_deposit(
        inst.finance_db_path, item_id, data=day, valor=amount, nome=(nome or "").strip() or "Savings deposit"
    )
    return _finish_edit(db, user, inst, "savings", item_id, result, target)


@app.post("/workspaces/{workspace_id}/switch")
def switch_workspace(workspace_id: int, request: Request, db: Session = Depends(get_db), next_url: str = Form("/dashboard")):
    user = require_user(request, db)
    require_instance(db, user, workspace_id)
    safe_next = next_url if next_url.startswith("/") and not next_url.startswith("//") else "/dashboard"
    resp = RedirectResponse(safe_next, status_code=302)
    workspace_service.set_active_workspace(resp, db, user, workspace_id)
    return resp


@app.get("/workspaces/{workspace_id}/members", response_class=HTMLResponse)
def workspace_members_page(workspace_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst, membership = workspace_service.require_workspace(db, user, workspace_id, "read")
    members = (
        db.query(WorkspaceMember, User)
        .join(User, User.id == WorkspaceMember.user_id)
        .filter(WorkspaceMember.workspace_id == workspace_id)
        .order_by(WorkspaceMember.created_at.asc())
        .all()
    )
    pending_invites = workspace_service.pending_invites_for_workspace(db, workspace_id)
    recent_invites = (
        db.query(WorkspaceInvite)
        .filter(WorkspaceInvite.workspace_id == workspace_id, WorkspaceInvite.status != "pending")
        .order_by(WorkspaceInvite.created_at.desc())
        .limit(10)
        .all()
    )
    instances = workspace_service.list_user_workspaces(db, user)
    is_shared = shared_workspace_service.is_shared(inst)
    shared_ctx: dict = {"is_shared": is_shared, "shared_workspaces": workspace_service.list_shared_workspaces(db, user)}
    if is_shared:
        source = (
            db.query(DatabaseInstance).filter(DatabaseInstance.id == inst.source_workspace_id).first()
            if inst.source_workspace_id
            else None
        )
        contributions = shared_workspace_service.member_contributions(db, inst)
        shared_ctx.update(
            {
                "source_workspace": source if source and workspace_service.get_membership(db, user.id, source.id) else None,
                "contributions": contributions,
                "combined_income": round(sum(c["monthly_income"] for c in contributions.values()), 2),
                "linkable_workspaces": shared_workspace_service.linkable_workspaces(db, user, inst),
                "my_link_id": membership.linked_workspace_id,
                "can_edit_settings": workspace_service.role_allows(membership.role, "invite"),
            }
        )
    else:
        copy = shared_workspace_service.find_shared_copy(db, inst)
        shared_ctx["shared_copy"] = copy if copy and workspace_service.get_membership(db, user.id, copy.id) else None
        shared_ctx["can_share"] = workspace_service.role_allows(membership.role, "delete_workspace")
    return templates.TemplateResponse(
        request=request,
        name="workspace_members.html",
        context={
            "request": request,
            "user": user,
            "instance": inst,
            "instances": instances,
            "workspace_for_nav": inst,
            "nav_active": "members",
            "show_back_to_dashboard": True,
            "members": [{"member": m, "user": u} for m, u in members],
            "pending_invites": pending_invites,
            "recent_invites": recent_invites,
            "workspace_role": membership.role,
            "is_owner": inst.owner_id == user.id,
            "can_invite": workspace_service.role_allows(membership.role, "invite"),
            "can_manage": workspace_service.role_allows(membership.role, "remove_member"),
            "msg": request.query_params.get("msg", ""),
            "err": request.query_params.get("err", ""),
            "currency": ws_currency(inst),
            **shared_ctx,
        },
    )


def _members_redirect(workspace_id: int, *, msg: str = "", err: str = "") -> RedirectResponse:
    from urllib.parse import urlencode

    q = urlencode({k: v for k, v in (("msg", msg), ("err", err)) if v})
    return RedirectResponse(f"/workspaces/{workspace_id}/members" + (f"?{q}" if q else ""), status_code=302)


@app.post("/workspaces/{workspace_id}/invite")
def workspace_invite(
    workspace_id: int,
    request: Request,
    username: str = Form(...),
    role: str = Form("member"),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    workspace_service.require_workspace(db, user, workspace_id, "invite")  # 403/404 for unauthorized callers
    try:
        invite = workspace_service.create_username_invite(db, workspace_id, username, role, user, root=ROOT)
    except HTTPException as exc:
        db.rollback()
        return _members_redirect(workspace_id, err=str(exc.detail))
    db.commit()
    if invite.workspace_id != workspace_id:
        shared = db.query(DatabaseInstance).filter(DatabaseInstance.id == invite.workspace_id).first()
        return _members_redirect(
            invite.workspace_id,
            msg=f'Invitation sent to {invite.email}. They will join "{shared.name}", a shared copy of this workspace; your personal workspace stays private.',
        )
    return _members_redirect(workspace_id, msg=f"Invitation sent to {invite.email}.")


@app.post("/workspaces/{workspace_id}/link")
def workspace_set_link(
    workspace_id: int,
    request: Request,
    linked_workspace_id: str = Form(""),
    db: Session = Depends(get_db),
):
    """Choose which of your own workspaces contributes income to a shared workspace."""
    user = require_user(request, db)
    inst, _m = workspace_service.require_workspace(db, user, workspace_id, "read")
    if not shared_workspace_service.is_shared(inst):
        return _members_redirect(workspace_id, err="Only shared workspaces use linked workspaces.")
    raw = (linked_workspace_id or "").strip()
    try:
        target = int(raw) if raw else None
        shared_workspace_service.set_member_link(db, inst, user, target)
        shared_workspace_service.sync_shared_workspace(db, inst)
    except ValueError:
        return _members_redirect(workspace_id, err="Invalid workspace.")
    except HTTPException as exc:
        db.rollback()
        return _members_redirect(workspace_id, err=str(exc.detail))
    db.commit()
    return _members_redirect(workspace_id, msg="Your linked workspace was updated." if target else "You no longer contribute income here.")


@app.post("/workspaces/{workspace_id}/shared-settings")
def workspace_shared_settings(
    workspace_id: int,
    request: Request,
    include_member_expenses: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    inst, _m = workspace_service.require_workspace(db, user, workspace_id, "invite")
    if not shared_workspace_service.is_shared(inst):
        return _members_redirect(workspace_id, err="Only shared workspaces have these settings.")
    inst.include_member_expenses = bool(include_member_expenses)
    db.add(inst)
    db.commit()
    shared_workspace_service.sync_shared_workspace(db, inst)
    return _members_redirect(
        workspace_id,
        msg="Members' expenses are now included." if inst.include_member_expenses else "Members' expenses are no longer included; add shared expenses manually.",
    )


@app.post("/workspaces/{workspace_id}/invites/{invite_id}/cancel")
def workspace_invite_cancel(workspace_id: int, invite_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    workspace_service.require_workspace(db, user, workspace_id, "invite")
    try:
        workspace_service.cancel_invite(db, user, workspace_id, invite_id)
    except HTTPException as exc:
        db.rollback()
        return _members_redirect(workspace_id, err=str(exc.detail))
    db.commit()
    return _members_redirect(workspace_id, msg="Invitation cancelled.")


@app.post("/workspaces/{workspace_id}/members/{member_user_id}/remove")
def workspace_remove_member(workspace_id: int, member_user_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    workspace_service.require_workspace(db, user, workspace_id, "remove_member")
    try:
        workspace_service.remove_member(db, workspace_id, member_user_id, user)
    except HTTPException as exc:
        db.rollback()
        return _members_redirect(workspace_id, err=str(exc.detail))
    return _members_redirect(workspace_id, msg="Member removed.")


@app.post("/workspaces/{workspace_id}/leave")
def workspace_leave(workspace_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    try:
        workspace_service.leave_workspace(db, user, workspace_id)
    except HTTPException as exc:
        db.rollback()
        return _members_redirect(workspace_id, err=str(exc.detail))
    resp = RedirectResponse("/dashboard", status_code=302)
    resp.delete_cookie(workspace_service.ACTIVE_WORKSPACE_COOKIE)
    return resp


@app.get("/api/users/search")
def api_users_search(request: Request, q: str = "", db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return JSONResponse({"error": "auth_required"}, status_code=401)
    return JSONResponse({"usernames": workspace_service.search_usernames(db, user, q)})


@app.get("/api/notifications")
def api_notifications(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return JSONResponse({"error": "auth_required"}, status_code=401)
    rows = notification_service.list_for_user(db, user)
    return JSONResponse(
        {
            "unread": notification_service.unread_count(db, user),
            "items": [notification_service.serialize(db, r) for r in rows],
        }
    )


@app.post("/api/notifications/{notification_id}/read")
def api_notification_read(notification_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not notification_service.mark_read(db, user, notification_id):
        return JSONResponse({"ok": False}, status_code=404)
    db.commit()
    return JSONResponse({"ok": True, "unread": notification_service.unread_count(db, user)})


@app.post("/api/notifications/read-all")
def api_notifications_read_all(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    notification_service.mark_all_read(db, user)
    db.commit()
    return JSONResponse({"ok": True, "unread": 0})


@app.post("/api/invites/{invite_id}/{decision}")
def api_invite_respond(invite_id: int, decision: str, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if decision not in ("accept", "decline"):
        raise HTTPException(status_code=404)
    try:
        inst = workspace_service.respond_to_invite(db, user, invite_id, accept=decision == "accept")
    except HTTPException as exc:
        db.commit()  # persist status changes such as expiry
        return JSONResponse({"ok": False, "error": str(exc.detail)}, status_code=exc.status_code)
    db.commit()
    body = {"ok": True, "decision": decision, "unread": notification_service.unread_count(db, user)}
    if decision == "accept":
        body["workspace_id"] = inst.id
        body["redirect"] = f"/workspaces/{inst.id}/members"
    return JSONResponse(body)


@app.get("/invite/{token}", response_class=HTMLResponse)
def invite_accept_page(token: str, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    invite = db.query(WorkspaceInvite).filter(WorkspaceInvite.token == token).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found.")
    inst = db.query(DatabaseInstance).filter(DatabaseInstance.id == invite.workspace_id).first()
    return templates.TemplateResponse(
        request=request,
        name="invite_accept.html",
        context={
            "request": request,
            "user": user,
            "invite": invite,
            "instance": inst,
            "show_back_to_dashboard": False,
        },
    )


@app.post("/invite/{token}/accept")
def invite_accept(token: str, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst = workspace_service.accept_invite(db, user, token)
    db.commit()
    if shared_workspace_service.is_shared(inst):
        # Shared workspaces are reached from the Members page, never made the dashboard's active one.
        return RedirectResponse(f"/workspaces/{inst.id}/members", status_code=302)
    resp = RedirectResponse(f"/instances/{inst.id}", status_code=302)
    workspace_service.set_active_workspace(resp, db, user, inst.id)
    return resp


@app.get("/members")
def members_entry(request: Request, db: Session = Depends(get_db)):
    """Members page for users without a personal workspace to navigate from."""
    user = require_user(request, db)
    _instances, primary = workspace_service.resolve_active_workspace(db, user, request)
    target = primary or next(iter(workspace_service.list_shared_workspaces(db, user)), None)
    if not target:
        return RedirectResponse("/dashboard", status_code=302)
    return RedirectResponse(f"/workspaces/{target.id}/members", status_code=302)


@app.get("/instances/{instance_id}/import-export", response_class=HTMLResponse)
def import_export_page(instance_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    inst, membership = workspace_service.require_workspace(db, user, instance_id, "read")
    instances = workspace_service.list_user_workspaces(db, user)
    return templates.TemplateResponse(
        request=request,
        name="import_export.html",
        context={
            "request": request,
            "user": user,
            "instance": inst,
            "instances": instances,
            "workspace_for_nav": inst,
            "nav_active": "import_export",
            "show_back_to_dashboard": True,
            "workspace_role": membership.role,
            "can_export": workspace_service.role_allows(membership.role, "export"),
            "can_import": workspace_service.role_allows(membership.role, "import"),
        },
    )


@app.get("/instances/{instance_id}/export/workspace.zip")
def export_workspace_zip(
    instance_id: int,
    request: Request,
    include_deleted: bool = False,
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    inst = require_instance(db, user, instance_id, action="export")
    zip_bytes = workspace_export_service.build_export_zip(
        db, inst, include_deleted_records=include_deleted
    )
    fname = export_naming.workspace_filename(inst, "Workspace-Backup", "zip")
    return download_response(zip_bytes, "application/zip", fname)


@app.post("/instances/{instance_id}/import/validate")
async def import_validate(instance_id: int, request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    user = require_user(request, db)
    require_instance(db, user, instance_id, action="import")
    data = await file.read()
    try:
        validated = workspace_export_service.validate_import_zip(data)
    except workspace_export_service.ImportValidationError as exc:
        log.warning("import validation failed: %s", exc.technical)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    except Exception as exc:
        log.exception("import validation error")
        return JSONResponse({"ok": False, "error": "Could not validate import file."}, status_code=400)

    token = uuid4().hex
    staging = ROOT / "import_staging"
    staging.mkdir(parents=True, exist_ok=True)
    staging_path = staging / f"{user.id}_{token}.zip"
    staging_path.write_bytes(data)
    return JSONResponse({"ok": True, "preview": validated["preview"], "staging_token": token})


@app.post("/instances/{instance_id}/import/confirm")
def import_confirm(
    instance_id: int,
    request: Request,
    staging_token: str = Form(...),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    require_instance(db, user, instance_id, action="import")
    staging_path = ROOT / "import_staging" / f"{user.id}_{staging_token}.zip"
    if not staging_path.is_file():
        return RedirectResponse(
            f"/instances/{instance_id}/import-export?err=staging_expired",
            status_code=302,
        )
    data = staging_path.read_bytes()
    try:
        validated = workspace_export_service.validate_import_zip(data)
        new_inst = workspace_export_service.import_as_new_workspace(db, user, ROOT, validated)
        staging_path.unlink(missing_ok=True)
    except workspace_export_service.ImportValidationError as exc:
        log.warning("import confirm failed: %s", exc.technical)
        return RedirectResponse(
            f"/instances/{instance_id}/import-export?err={slugify(str(exc))[:80]}",
            status_code=302,
        )
    except Exception:
        log.exception("import confirm failed")
        return RedirectResponse(
            f"/instances/{instance_id}/import-export?err=import_failed",
            status_code=302,
        )
    resp = RedirectResponse(
        f"/instances/{new_inst.id}/import-export?msg=import_success&new_id={new_inst.id}",
        status_code=302,
    )
    workspace_service.set_active_workspace(resp, db, user, new_inst.id)
    return resp
