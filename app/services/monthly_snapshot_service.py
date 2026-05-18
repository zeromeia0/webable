"""Monthly financial snapshots — compute, persist, and list per workspace."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import Session

from app.models import DatabaseInstance, MonthlySnapshot, User
from app.services import dashboard_metrics, instance_service

SAFE_PCT_DEFAULT = dashboard_metrics.SAFE_TO_SPEND_DEFAULT_PCT


def _money(value: float) -> str:
    return f"€{float(value):,.2f}"


def month_str_to_parts(month_str: str) -> tuple[int, int]:
    y, m = month_str.split("-")
    return int(y), int(m)


def parts_to_month_str(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def previous_month(year: int, month: int) -> tuple[int, int]:
    d = date(year, month, 1) - relativedelta(months=1)
    return d.year, d.month


def is_completed_month(year: int, month: int, today: date | None = None) -> bool:
    today = today or date.today()
    if year < today.year:
        return True
    if year > today.year:
        return False
    return month < today.month


def _top_expense_rows(month_summary: dict[str, Any], total_expenses: float, total_income: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for e in month_summary.get("expense_items") or []:
        if e.get("ended"):
            continue
        rows.append(
            {
                "name": str(e.get("name") or ""),
                "amount_eur": round(float(e.get("amount") or 0), 2),
                "kind": "recurring",
            }
        )
    for o in month_summary.get("oneoff_transactions") or []:
        if str(o.get("txn_type", "expense")).lower() == "income":
            continue
        rows.append(
            {
                "name": str(o.get("name") or ""),
                "amount_eur": round(abs(float(o.get("amount") or 0)), 2),
                "kind": "one-time",
                "category": o.get("category"),
            }
        )
    rows.sort(key=lambda x: x["amount_eur"], reverse=True)
    enriched = [
        dashboard_metrics.enrich_expense_entry(r, total_expenses, total_income) for r in rows[:12]
    ]
    return enriched


def _top_income_rows(month_summary: dict[str, Any], total_income: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i in month_summary.get("income_items") or []:
        if i.get("ended"):
            continue
        amt = round(float(i.get("amount") or 0), 2)
        pct = dashboard_metrics.format_pct_of_total(amt, total_income)
        rows.append(
            {
                "name": str(i.get("name") or ""),
                "amount_eur": amt,
                "kind": "recurring",
                "pct_of_income_label": f"{pct}% of income" if pct else "income unavailable",
            }
        )
    for o in month_summary.get("oneoff_transactions") or []:
        if str(o.get("txn_type", "expense")).lower() != "income":
            continue
        amt = round(abs(float(o.get("amount") or 0)), 2)
        pct = dashboard_metrics.format_pct_of_total(amt, total_income)
        rows.append(
            {
                "name": str(o.get("name") or ""),
                "amount_eur": amt,
                "kind": "one-time",
                "pct_of_income_label": f"{pct}% of income" if pct else "income unavailable",
            }
        )
    rows.sort(key=lambda x: x["amount_eur"], reverse=True)
    return rows[:12]


def _average_monthly_balance(finance_db: str, logic_db: str, end_month: str, include_iefp: bool, n: int = 6) -> float | None:
    end = datetime.strptime(end_month + "-01", "%Y-%m-%d").date()
    vals: list[float] = []
    for i in range(n):
        mk = (end - relativedelta(months=i)).strftime("%Y-%m")
        sm = instance_service.month_summary(finance_db, logic_db, mk, include_iefp=include_iefp)
        vals.append(float(sm.get("estimated_savings") or 0))
    if not vals:
        return None
    return round(sum(vals) / len(vals), 2)


def compute_snapshot_payload(
    finance_db: str,
    logic_db: str,
    month_str: str,
    *,
    include_iefp: bool = False,
    safe_pct: float = SAFE_PCT_DEFAULT,
    prev_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pure calculation for one month (no DB)."""
    year, month = month_str_to_parts(month_str)
    sm = instance_service.month_summary(finance_db, logic_db, month_str, include_iefp=include_iefp)
    total_income = round(float(sm.get("total_before_expenses") or 0), 2)
    recurring_exp = round(float(sm.get("expenses") or 0), 2)
    oneoff_exp = round(float(sm.get("oneoff_expense_total") or 0), 2)
    total_expenses = round(recurring_exp + oneoff_exp, 2)
    net_balance = round(float(sm.get("estimated_savings") or 0), 2)
    fixed_total = recurring_exp
    fixed_pct = dashboard_metrics.format_pct_of_total(fixed_total, total_income)
    safe_to_spend = dashboard_metrics.safe_to_spend_amount(max(net_balance, 0), safe_pct)
    avg_bal = _average_monthly_balance(finance_db, logic_db, month_str, include_iefp)

    top_expenses = _top_expense_rows(sm, total_expenses, total_income)
    top_income = _top_income_rows(sm, total_income)

    comparison: dict[str, Any] = {}
    if prev_payload:
        pi = float(prev_payload.get("total_income") or 0)
        pe = float(prev_payload.get("total_expenses") or 0)
        pn = float(prev_payload.get("net_balance") or 0)
        comparison = {
            "income_change": round(total_income - pi, 2),
            "expenses_change": round(total_expenses - pe, 2),
            "savings_change": round(net_balance - pn, 2),
            "previous_month": prev_payload.get("month_label"),
        }
        prev_top = {r["name"]: r["amount_eur"] for r in (prev_payload.get("top_expenses") or [])}
        cur_top = {r["name"]: r["amount_eur"] for r in top_expenses}
        biggest_name = None
        biggest_delta = 0.0
        for name in set(prev_top) | set(cur_top):
            delta = cur_top.get(name, 0) - prev_top.get(name, 0)
            if abs(delta) > abs(biggest_delta):
                biggest_delta = delta
                biggest_name = name
        if biggest_name and biggest_delta != 0:
            comparison["biggest_expense_change"] = {
                "name": biggest_name,
                "delta_eur": round(biggest_delta, 2),
            }
        comparison["plain_summary"] = _comparison_plain(comparison)

    summary_lines = _build_plain_summary(
        month_str=month_str,
        net_balance=net_balance,
        total_income=total_income,
        total_expenses=total_expenses,
        comparison=comparison,
        top_expenses=top_expenses,
        fixed_pct=fixed_pct,
        fixed_total=fixed_total,
    )

    month_label = datetime(year, month, 1).strftime("%B %Y")

    return {
        "year": year,
        "month": month,
        "month_str": month_str,
        "month_label": month_label,
        "total_income": total_income,
        "total_expenses": total_expenses,
        "net_balance": net_balance,
        "average_monthly_balance": avg_bal,
        "safe_to_spend": safe_to_spend,
        "fixed_expenses_total": fixed_total,
        "fixed_expenses_percent_income": fixed_pct,
        "top_expenses": top_expenses,
        "top_income": top_income,
        "comparison": comparison,
        "summary_lines": summary_lines,
    }


def _comparison_plain(comparison: dict[str, Any]) -> str:
    parts: list[str] = []
    inc = comparison.get("income_change")
    exp = comparison.get("expenses_change")
    sav = comparison.get("savings_change")
    if inc is not None and inc != 0:
        parts.append(f"Income {'increased' if inc > 0 else 'decreased'} by {_money(abs(inc))} compared with last month.")
    if exp is not None and exp != 0:
        parts.append(f"Expenses {'increased' if exp > 0 else 'decreased'} by {_money(abs(exp))} compared with last month.")
    if sav is not None and sav != 0:
        parts.append(f"Savings {'improved' if sav > 0 else 'declined'} by {_money(abs(sav))} compared with last month.")
    bec = comparison.get("biggest_expense_change")
    if bec:
        d = float(bec.get("delta_eur") or 0)
        if d > 0:
            parts.append(f"Largest increase was {bec.get('name')} (+{_money(d)}).")
        elif d < 0:
            parts.append(f"Largest decrease was {bec.get('name')} ({_money(d)}).")
    return " ".join(parts) if parts else "Spending was similar to last month."


def _build_plain_summary(
    *,
    month_str: str,
    net_balance: float,
    total_income: float,
    total_expenses: float,
    comparison: dict[str, Any],
    top_expenses: list[dict[str, Any]],
    fixed_pct: str | None,
    fixed_total: float,
) -> list[str]:
    lines: list[str] = []
    if net_balance >= 0:
        lines.append(f"You saved {_money(net_balance)} this month.")
    else:
        lines.append(f"You ended the month {_money(abs(net_balance))} below break-even.")
    if comparison.get("expenses_change"):
        ec = float(comparison["expenses_change"])
        if ec != 0:
            lines.append(
                f"Expenses {'increased' if ec > 0 else 'decreased'} by {_money(abs(ec))} compared with last month."
            )
    if top_expenses:
        names = [t["name"] for t in top_expenses[:3] if t.get("name")]
        if names:
            lines.append(f"Most spending went to {', '.join(names)}.")
    if fixed_pct:
        lines.append(f"Fixed expenses used {fixed_pct}% of income ({_money(fixed_total)}).")
    elif total_income <= 0 and total_expenses > 0:
        lines.append(f"Total expenses were {_money(total_expenses)}; income data was limited.")
    if comparison.get("savings_change") is not None:
        sc = float(comparison["savings_change"])
        if sc > 0:
            lines.append("Savings improved compared with last month.")
        elif sc < 0:
            lines.append("Savings declined compared with last month.")
        else:
            lines.append("This month was stable compared with last month.")
    return lines


def snapshot_row_to_payload(row: MonthlySnapshot) -> dict[str, Any]:
    return {
        "id": row.id,
        "instance_id": row.instance_id,
        "year": row.year,
        "month": row.month,
        "month_str": parts_to_month_str(row.year, row.month),
        "month_label": datetime(row.year, row.month, 1).strftime("%B %Y"),
        "total_income": row.total_income,
        "total_expenses": row.total_expenses,
        "net_balance": row.net_balance,
        "average_monthly_balance": row.average_monthly_balance,
        "safe_to_spend": row.safe_to_spend,
        "fixed_expenses_total": row.fixed_expenses_total,
        "fixed_expenses_percent_income": row.fixed_expenses_percent_income,
        "top_expenses": json.loads(row.top_expenses_json or "[]"),
        "top_income": json.loads(row.top_income_json or "[]"),
        "comparison": json.loads(row.comparison_json or "{}"),
        "summary_lines": json.loads(row.summary_json or "[]"),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _upsert_snapshot(db: Session, instance_id: int, payload: dict[str, Any]) -> MonthlySnapshot:
    row = (
        db.query(MonthlySnapshot)
        .filter(
            MonthlySnapshot.instance_id == instance_id,
            MonthlySnapshot.year == payload["year"],
            MonthlySnapshot.month == payload["month"],
        )
        .first()
    )
    now = datetime.utcnow()
    fields = {
        "total_income": payload["total_income"],
        "total_expenses": payload["total_expenses"],
        "net_balance": payload["net_balance"],
        "average_monthly_balance": payload.get("average_monthly_balance"),
        "safe_to_spend": payload.get("safe_to_spend"),
        "fixed_expenses_total": payload["fixed_expenses_total"],
        "fixed_expenses_percent_income": payload.get("fixed_expenses_percent_income"),
        "top_expenses_json": json.dumps(payload.get("top_expenses") or []),
        "top_income_json": json.dumps(payload.get("top_income") or []),
        "comparison_json": json.dumps(payload.get("comparison") or {}),
        "summary_json": json.dumps(payload.get("summary_lines") or []),
        "updated_at": now,
    }
    if row:
        for k, v in fields.items():
            setattr(row, k, v)
    else:
        row = MonthlySnapshot(
            instance_id=instance_id,
            year=payload["year"],
            month=payload["month"],
            created_at=now,
            **fields,
        )
        db.add(row)
    db.commit()
    db.refresh(row)
    return row


def generate_monthly_snapshot(
    db: Session,
    instance: DatabaseInstance,
    year: int,
    month: int,
    user: User,
    *,
    safe_pct: float = SAFE_PCT_DEFAULT,
) -> dict[str, Any]:
    month_str = parts_to_month_str(year, month)
    py, pm = previous_month(year, month)
    prev_payload = None
    prev_row = get_monthly_snapshot(db, instance.id, py, pm)
    if prev_row:
        prev_payload = snapshot_row_to_payload(prev_row)
    else:
        prev_ms = parts_to_month_str(py, pm)
        prev_payload = compute_snapshot_payload(
            instance.finance_db_path,
            instance.logic_db_path,
            prev_ms,
            include_iefp=bool(user.enable_iefp_mode),
            safe_pct=safe_pct,
        )
    payload = compute_snapshot_payload(
        instance.finance_db_path,
        instance.logic_db_path,
        month_str,
        include_iefp=bool(user.enable_iefp_mode),
        safe_pct=safe_pct,
        prev_payload=prev_payload,
    )
    row = _upsert_snapshot(db, instance.id, payload)
    return snapshot_row_to_payload(row)


def get_monthly_snapshot(db: Session, instance_id: int, year: int, month: int) -> MonthlySnapshot | None:
    return (
        db.query(MonthlySnapshot)
        .filter(
            MonthlySnapshot.instance_id == instance_id,
            MonthlySnapshot.year == year,
            MonthlySnapshot.month == month,
        )
        .first()
    )


def list_monthly_snapshots(db: Session, instance_id: int) -> list[dict[str, Any]]:
    rows = (
        db.query(MonthlySnapshot)
        .filter(MonthlySnapshot.instance_id == instance_id)
        .order_by(MonthlySnapshot.year.desc(), MonthlySnapshot.month.desc())
        .all()
    )
    return [snapshot_row_to_payload(r) for r in rows]


def iter_completed_months(
    start_month: str,
    end_month: str,
) -> list[tuple[int, int]]:
    """Inclusive range of YYYY-MM from start to end (both completed-style strings)."""
    start = datetime.strptime(start_month + "-01", "%Y-%m-%d").date()
    end = datetime.strptime(end_month + "-01", "%Y-%m-%d").date()
    if start > end:
        return []
    out: list[tuple[int, int]] = []
    cur = start
    while cur <= end:
        out.append((cur.year, cur.month))
        cur = cur + relativedelta(months=1)
    return out


def generate_missing_completed_month_snapshots(
    db: Session,
    instance: DatabaseInstance,
    user: User,
    *,
    max_months: int = 24,
) -> int:
    today = date.today()
    if today.month == 1:
        prev_y, prev_m = today.year - 1, 12
    else:
        prev_y, prev_m = today.year, today.month - 1
    end_month = parts_to_month_str(prev_y, prev_m)
    start_d = instance.created_at.date() if instance.created_at else today
    start_month = start_d.strftime("%Y-%m")
    months = iter_completed_months(start_month, end_month)
    if len(months) > max_months:
        months = months[-max_months:]
    created = 0
    for y, m in months:
        if not is_completed_month(y, m, today):
            continue
        existing = get_monthly_snapshot(db, instance.id, y, m)
        if existing:
            continue
        generate_monthly_snapshot(db, instance, y, m, user)
        created += 1
    return created


def ensure_day_one_snapshot(db: Session, instance: DatabaseInstance, user: User) -> bool:
    """On day 1 of a month, generate previous month's snapshot. Returns True if generated/updated."""
    today = date.today()
    if today.day != 1:
        return False
    py, pm = previous_month(today.year, today.month)
    generate_monthly_snapshot(db, instance, py, pm, user)
    return True
