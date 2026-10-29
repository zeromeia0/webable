"""Past spending analysis from one-time transactions and recurring totals."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from typing import Any

from dateutil.relativedelta import relativedelta

from app.services.instance_service import ONEOFF_CATEGORIES, recurring_active_in_month


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


def _monthly_equivalent(item: dict[str, Any]) -> float:
    from app.services.savings_expenses_service import recurrence_to_monthly

    return recurrence_to_monthly(float(item.get("amount") or 0), item.get("recurrence"))


def _recurring_month_total(items: Iterable[dict[str, Any]], ym: str) -> float:
    return sum(_monthly_equivalent(i) for i in items if recurring_active_in_month(i, ym))


def _month_coverage(ym: str, start: date | None, end: date | None) -> float:
    """Share of calendar month ``ym`` that falls inside [start, end] (1.0 when unbounded)."""
    first = datetime.strptime(ym + "-01", "%Y-%m-%d").date()
    last = first + relativedelta(months=1) - timedelta(days=1)
    lo = max(first, start) if start else first
    hi = min(last, end) if end else last
    if hi < lo:
        return 0.0
    return ((hi - lo).days + 1) / ((last - first).days + 1)


def _recurring_first_month(items: Iterable[dict[str, Any]]) -> date | None:
    """Earliest month a still-relevant recurring entry applies to (None = open-ended / unknown)."""
    ds = [parse_txn_date(str(i.get("start_date") or "")) for i in items if not i.get("ended")]
    ds = [d for d in ds if d]
    return min(ds) if ds else None


def build_spending_report(
    oneoffs: list[dict[str, Any]],
    recurring_income_monthly: float,
    recurring_expense_monthly: float,
    start: date | None,
    end: date | None,
    *,
    recurring_incomes: list[dict[str, Any]] | None = None,
    recurring_expenses: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Spending in [start, end]. One-off transactions count on their date.

    When ``recurring_incomes`` / ``recurring_expenses`` are given, each recurring entry counts once
    per calendar month it is active in (monthly equivalent of its recurrence, respecting start/end
    dates; prorated for months only partly inside the range) and recurring expenses are included in the category and description rankings. Otherwise
    the flat ``recurring_*_monthly`` totals are applied to every month (legacy behaviour).
    """
    itemized = recurring_incomes is not None or recurring_expenses is not None
    rec_inc_items = list(recurring_incomes or [])
    rec_exp_items = list(recurring_expenses or [])
    if itemized:
        recurring_income_monthly = sum(_monthly_equivalent(i) for i in rec_inc_items if not i.get("ended"))
        recurring_expense_monthly = sum(_monthly_equivalent(i) for i in rec_exp_items if not i.get("ended"))
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

    months = []
    if start and end:
        months = iter_months(start, end)
    else:
        dates = [parse_txn_date(str(o["date"])) for o in filtered]
        dates = [d for d in dates if d]
        if itemized and (rec_inc_items or rec_exp_items):
            rec_start = _recurring_first_month(rec_inc_items + rec_exp_items)
            if rec_start:
                dates.append(rec_start)
            dates.append(date.today())
        if dates:
            mn, mx = min(dates), max(dates)
            if start:
                mn = max(mn, start)
            if end:
                mx = min(mx, end)
            if mn <= mx:
                months = iter_months(mn, mx)

    rec_exp_by_month: dict[str, float] = {}
    rec_inc_by_month: dict[str, float] = {}
    if itemized:
        for ym in months:
            cover = _month_coverage(ym, start, end)
            rec_exp_by_month[ym] = _recurring_month_total(rec_exp_items, ym) * cover
            rec_inc_by_month[ym] = _recurring_month_total(rec_inc_items, ym) * cover
            for e in rec_exp_items:
                if not recurring_active_in_month(e, ym):
                    continue
                amt = _monthly_equivalent(e) * cover
                if amt <= 0:
                    continue
                by_cat[normalize_report_category(str(e.get("category")))].append(amt)
                by_name[(str(e.get("name") or "").strip() or "Unknown") + " (recurring)"].append(amt)
    else:
        for ym in months:
            rec_exp_by_month[ym] = recurring_expense_monthly
            rec_inc_by_month[ym] = recurring_income_monthly

    recurring_expenses_in_range = sum(rec_exp_by_month.values())
    recurring_income_in_range = sum(rec_inc_by_month.values())
    ranking_total = total_oneoff_spend + (recurring_expenses_in_range if itemized else 0.0)
    top_categories = _top_n_groups(dict(by_cat), ranking_total, 7)
    top_merchants = _top_n_groups(dict(by_name), ranking_total, 7)

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
        rexp = rec_exp_by_month.get(ym, 0.0)
        rinc = rec_inc_by_month.get(ym, 0.0)
        monthly.append(
            {
                "month": ym,
                "oneoff_expenses": round(oe, 2),
                "oneoff_income": round(oi, 2),
                "recurring_expenses": round(rexp, 2),
                "recurring_income": round(rinc, 2),
                "total_expenses": round(oe + rexp, 2),
                "total_income": round(oi + rinc, 2),
                "net": round(oi + rinc - oe - rexp, 2),
            }
        )

    cat_chart = {row["key"]: row["total"] for row in top_categories}
    daily = _daily_series(filtered, start, end, rec_exp_items, rec_inc_items) if itemized else []

    effective_start = start
    effective_end = end
    if (not effective_start or not effective_end) and itemized and months:
        first = datetime.strptime(months[0] + "-01", "%Y-%m-%d").date()
        effective_start = effective_start or first
        effective_end = effective_end or max(
            [date.today()] + [d for d in (parse_txn_date(str(o["date"])) for o in filtered) if d]
        )
    if not effective_start or not effective_end:
        if filtered:
            dates = [parse_txn_date(str(o["date"])) for o in filtered]
            dates = [d for d in dates if d]
            if dates:
                effective_start = effective_start or min(dates)
                effective_end = effective_end or max(dates)
        if not effective_start or not effective_end:
            today = date.today()
            effective_start = effective_start or today
            effective_end = effective_end or today

    return {
        "range": {
            "start": effective_start.isoformat() if effective_start else None,
            "end": effective_end.isoformat() if effective_end else None,
        },
        "totals": {
            "oneoff_expenses": round(total_oneoff_spend, 2),
            "oneoff_income": round(total_oneoff_income, 2),
            "recurring_income_monthly": round(recurring_income_monthly, 2),
            "recurring_expense_monthly": round(recurring_expense_monthly, 2),
            "transaction_count_expenses": len(expenses),
            "transaction_count_income": len(incomes),
            "recurring_expenses_in_range": round(recurring_expenses_in_range, 2),
            "recurring_income_in_range": round(recurring_income_in_range, 2),
            "total_expenses": round(total_oneoff_spend + recurring_expenses_in_range, 2),
            "total_income": round(total_oneoff_income + recurring_income_in_range, 2),
            "net": round(total_oneoff_income + recurring_income_in_range - total_oneoff_spend - recurring_expenses_in_range, 2),
            "months_in_range": len(months),
        },
        "includes_recurring": itemized,
        "top_categories": top_categories,
        "top_merchants": top_merchants,
        "monthly": monthly,
        "daily": daily,
        "charts": {
            "category_totals": cat_chart,
            "top_category_labels": [r["key"] for r in top_categories],
            "top_category_values": [r["total"] for r in top_categories],
        },
    }


DAILY_MAX_DAYS = 186


def _daily_series(
    filtered: list[dict[str, Any]],
    start: date | None,
    end: date | None,
    rec_exp_items: list[dict[str, Any]],
    rec_inc_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Per-day income/expenses for short ranges; recurring amounts are spread evenly over each month."""
    if not start or not end or (end - start).days > DAILY_MAX_DAYS:
        return []
    by_day: dict[date, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for o in filtered:
        pd = parse_txn_date(str(o.get("date", "")))
        if not pd:
            continue
        amt = abs(float(o.get("amount", 0) or 0))
        by_day[pd][1 if str(o.get("txn_type", "expense")).lower() == "income" else 0] += amt
    month_rate: dict[str, tuple[float, float]] = {}
    out: list[dict[str, Any]] = []
    d = start
    while d <= end:
        ym = month_key(d)
        if ym not in month_rate:
            days = ((date(d.year, d.month, 1) + relativedelta(months=1)) - date(d.year, d.month, 1)).days
            month_rate[ym] = (
                _recurring_month_total(rec_exp_items, ym) / days,
                _recurring_month_total(rec_inc_items, ym) / days,
            )
        rexp, rinc = month_rate[ym]
        oexp, oinc = by_day.get(d, (0.0, 0.0))
        out.append({"date": d.isoformat(), "expenses": round(oexp + rexp, 2), "income": round(oinc + rinc, 2)})
        d += timedelta(days=1)
    return out


def report_date_bounds(
    oneoffs: list[dict[str, Any]],
    recurring: list[dict[str, Any]] | None = None,
    today: date | None = None,
    min_span_months: int = 12,
) -> tuple[date, date]:
    """
    Range the Reports date picker/slider can cover: from the earliest transaction or recurring start
    (and at least ``min_span_months`` back) up to today or the latest dated transaction.
    """
    today = today or date.today()
    ds = [d for d in (parse_txn_date(str(o.get("date", ""))) for o in oneoffs) if d]
    rec_start = _recurring_first_month(recurring or [])
    if rec_start:
        ds.append(rec_start)
    lo = min(ds + [today - relativedelta(months=min_span_months)])
    hi = max(ds + [today])
    return lo, hi


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
