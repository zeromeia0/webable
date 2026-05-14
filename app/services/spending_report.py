"""Past spending analysis from one-time transactions and recurring totals."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from typing import Any

from dateutil.relativedelta import relativedelta

from app.services.instance_service import ONEOFF_CATEGORIES


def normalize_report_category(raw: str | None) -> str:
    c = (raw or "").strip()
    return c if c in ONEOFF_CATEGORIES else "Other"


def parse_txn_date(d: str) -> date | None:
    if not d or not isinstance(d, str):
        return None
    s = d.strip()[:10]
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def month_key(d: date) -> str:
    return d.strftime("%Y-%m")


def iter_months(start: date, end: date) -> list[str]:
    out: list[str] = []
    cur = date(start.year, start.month, 1)
    end_m = date(end.year, end.month, 1)
    while cur <= end_m:
        out.append(month_key(cur))
        cur = cur + relativedelta(months=1)
    return out


def filter_oneoffs_by_range(
    oneoffs: Iterable[dict[str, Any]],
    start: date | None,
    end: date | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for o in oneoffs:
        pd = parse_txn_date(str(o.get("date", "")))
        if pd is None:
            continue
        if start and pd < start:
            continue
        if end and pd > end:
            continue
        rows.append(o)
    return rows


def _top_n_groups(
    groups: dict[str, list[float]],
    total_spent: float,
    n: int = 7,
) -> list[dict[str, Any]]:
    items: list[tuple[str, list[float]]] = sorted(groups.items(), key=lambda x: sum(x[1]), reverse=True)[:n]
    out: list[dict[str, Any]] = []
    for key, amounts in items:
        s = sum(amounts)
        cnt = len(amounts)
        out.append(
            {
                "key": key,
                "total": round(s, 2),
                "count": cnt,
                "average": round(s / cnt, 2) if cnt else 0.0,
                "pct_of_total": round((100.0 * s / total_spent), 2) if total_spent > 0 else 0.0,
            }
        )
    return out


def build_spending_report(
    oneoffs: list[dict[str, Any]],
    recurring_income_monthly: float,
    recurring_expense_monthly: float,
    start: date | None,
    end: date | None,
) -> dict[str, Any]:
    filtered = filter_oneoffs_by_range(oneoffs, start, end)
    expenses = [o for o in filtered if str(o.get("txn_type", "expense")).lower() != "income"]
    incomes = [o for o in filtered if str(o.get("txn_type", "expense")).lower() == "income"]

    expense_amounts = [abs(float(o.get("amount", 0) or 0)) for o in expenses]
    total_oneoff_spend = sum(expense_amounts)
    total_oneoff_income = sum(abs(float(o.get("amount", 0) or 0)) for o in incomes)

    by_cat: dict[str, list[float]] = defaultdict(list)
    by_name: dict[str, list[float]] = defaultdict(list)
    for o in expenses:
        amt = abs(float(o.get("amount", 0) or 0))
        cat = normalize_report_category(str(o.get("category")))
        name = str(o.get("name") or "").strip() or "Unknown"
        by_cat[cat].append(amt)
        by_name[name].append(amt)

    top_categories = _top_n_groups(dict(by_cat), total_oneoff_spend, 7)
    top_merchants = _top_n_groups(dict(by_name), total_oneoff_spend, 7)

    months = []
    if start and end:
        months = iter_months(start, end)
    elif filtered:
        dates = [parse_txn_date(str(o["date"])) for o in filtered]
        dates = [d for d in dates if d]
        if dates:
            mn, mx = min(dates), max(dates)
            months = iter_months(mn, mx)

    monthly: list[dict[str, Any]] = []
    for ym in months:
        oe = 0.0
        oi = 0.0
        for o in filtered:
            pd = parse_txn_date(str(o.get("date", "")))
            if not pd or month_key(pd) != ym:
                continue
            amt = abs(float(o.get("amount", 0) or 0))
            if str(o.get("txn_type", "expense")).lower() == "income":
                oi += amt
            else:
                oe += amt
        monthly.append(
            {
                "month": ym,
                "oneoff_expenses": round(oe, 2),
                "oneoff_income": round(oi, 2),
                "recurring_expenses": round(recurring_expense_monthly, 2),
                "recurring_income": round(recurring_income_monthly, 2),
                "total_expenses": round(oe + recurring_expense_monthly, 2),
                "total_income": round(oi + recurring_income_monthly, 2),
            }
        )

    cat_chart = {row["key"]: row["total"] for row in top_categories}

    return {
        "range": {
            "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None,
        },
        "totals": {
            "oneoff_expenses": round(total_oneoff_spend, 2),
            "oneoff_income": round(total_oneoff_income, 2),
            "recurring_income_monthly": round(recurring_income_monthly, 2),
            "recurring_expense_monthly": round(recurring_expense_monthly, 2),
            "transaction_count_expenses": len(expenses),
            "transaction_count_income": len(incomes),
        },
        "top_categories": top_categories,
        "top_merchants": top_merchants,
        "monthly": monthly,
        "charts": {
            "category_totals": cat_chart,
            "top_category_labels": [r["key"] for r in top_categories],
            "top_category_values": [r["total"] for r in top_categories],
        },
    }


def transaction_date_bounds(oneoffs: list[dict[str, Any]]) -> tuple[date | None, date | None]:
    ds: list[date] = []
    for o in oneoffs:
        pd = parse_txn_date(str(o.get("date", "")))
        if pd:
            ds.append(pd)
    if not ds:
        t = date.today()
        return t, t
    return min(ds), max(ds)


def preset_range(preset: str, today: date | None = None) -> tuple[date | None, date | None]:
    today = today or date.today()
    p = (preset or "all").lower().replace(" ", "_")
    if p in ("all", "all_time", "lifetime"):
        return None, None
    if p == "last_7_days":
        return today - timedelta(days=7), today
    if p == "last_30_days":
        return today - timedelta(days=30), today
    if p == "last_3_months":
        return today - relativedelta(months=3), today
    if p == "last_6_months":
        return today - relativedelta(months=6), today
    if p == "last_12_months":
        return today - relativedelta(months=12), today
    return None, None
