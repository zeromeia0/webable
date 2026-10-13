"""
Expense breakdown by category (and fixed vs variable) for one workspace and time range.

Counting rules (no double counting):
- Recurring expenses count once per calendar month in the range in which they are active
  (respecting ended / start_date / end_date, same rule as month_summary).
- One-time expenses count once on their transaction date.
- Income entries are never counted.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from dateutil.relativedelta import relativedelta

from app.services import instance_service

RANGES: dict[str, str] = {
    "this_month": "This month",
    "last_month": "Last month",
    "3_months": "Last 3 months",
    "6_months": "Last 6 months",
    "1_year": "Last 12 months",
    "all": "All time",
}
DEFAULT_RANGE = "this_month"


def _month_start(d: date) -> date:
    return date(d.year, d.month, 1)


def _months_between(start: date, end: date) -> list[str]:
    out: list[str] = []
    cur = _month_start(start)
    last = _month_start(end)
    while cur <= last:
        out.append(cur.strftime("%Y-%m"))
        cur += relativedelta(months=1)
    return out


def _earliest_data_month(items: dict, today: date) -> date:
    candidates: list[str] = []
    for o in items["oneoffs"]:
        if o.get("date"):
            candidates.append(str(o["date"])[:7])
    for e in items["expenses"]:
        if e.get("start_date"):
            candidates.append(str(e["start_date"])[:7])
    if not candidates:
        return _month_start(today)
    first = min(candidates)
    try:
        y, m = int(first[:4]), int(first[5:7])
        return min(date(y, m, 1), _month_start(today))
    except ValueError:
        return _month_start(today)


def resolve_range(range_key: str | None, items: dict, today: date | None = None) -> tuple[str, list[str], date, date]:
    """Return (key, months[], start_day, end_day) — whole calendar months."""
    today = today or date.today()
    key = range_key if range_key in RANGES else DEFAULT_RANGE
    this_m = _month_start(today)
    if key == "this_month":
        start = this_m
        end = this_m
    elif key == "last_month":
        start = this_m - relativedelta(months=1)
        end = start
    elif key == "3_months":
        start = this_m - relativedelta(months=2)
        end = this_m
    elif key == "6_months":
        start = this_m - relativedelta(months=5)
        end = this_m
    elif key == "1_year":
        start = this_m - relativedelta(months=11)
        end = this_m
    else:
        start = _earliest_data_month(items, today)
        end = this_m
    end_day = end + relativedelta(months=1) - relativedelta(days=1)
    return key, _months_between(start, end), start, end_day


def build_category_breakdown(finance_db: str, range_key: str | None = None, today: date | None = None) -> dict[str, Any]:
    items = instance_service.list_finance_items(finance_db)
    key, months, start_day, end_day = resolve_range(range_key, items, today)
    month_set = set(months)

    categories: dict[str, dict[str, Any]] = {}
    type_totals = {"fixed": 0.0, "variable": 0.0, "unclassified": 0.0}

    def bucket(cat: str) -> dict[str, Any]:
        if cat not in categories:
            categories[cat] = {"category": cat, "total": 0.0, "entries": []}
        return categories[cat]

    for e in items["expenses"]:
        active = [m for m in months if instance_service.recurring_active_in_month(e, m)]
        if not active:
            continue
        amount = float(e["amount"]) * len(active)
        cat = e.get("category") or "Other"
        b = bucket(cat)
        b["total"] += amount
        etype = e.get("expense_type")
        type_totals[etype or "unclassified"] += amount
        b["entries"].append(
            {
                "kind": "expense",
                "id": e["id"],
                "name": e["name"],
                "amount": amount,
                "unit_amount": float(e["amount"]),
                "months": len(active),
                "recurrence": e.get("recurrence"),
                "expense_type": etype,
            }
        )

    for o in items["oneoffs"]:
        if str(o.get("txn_type", "expense")).lower() == "income":
            continue
        d = str(o.get("date") or "")
        if d[:7] not in month_set:
            continue
        amount = abs(float(o.get("amount") or 0))
        cat = o.get("category") or "Other"
        b = bucket(cat)
        b["total"] += amount
        etype = o.get("expense_type")
        type_totals[etype or "unclassified"] += amount
        b["entries"].append(
            {
                "kind": "oneoff",
                "id": o["id"],
                "name": o["name"],
                "amount": amount,
                "date": d[:10],
                "expense_type": etype,
            }
        )

    total = sum(c["total"] for c in categories.values())
    rows = sorted(categories.values(), key=lambda c: c["total"], reverse=True)
    for r in rows:
        r["share_pct"] = (100.0 * r["total"] / total) if total > 0 else 0.0
        r["count"] = len(r["entries"])
        r["entries"].sort(key=lambda x: x["amount"], reverse=True)

    type_rows = [
        {
            "type": t,
            "label": {"fixed": "Fixed", "variable": "Variable", "unclassified": "Not classified"}[t],
            "total": type_totals[t],
            "share_pct": (100.0 * type_totals[t] / total) if total > 0 else 0.0,
        }
        for t in ("fixed", "variable", "unclassified")
    ]

    return {
        "range": key,
        "range_label": RANGES[key],
        "ranges": [{"key": k, "label": v} for k, v in RANGES.items()],
        "start": start_day.isoformat(),
        "end": end_day.isoformat(),
        "months": months,
        "total": total,
        "categories": rows,
        "fixed_variable": type_rows,
        "has_unclassified": type_totals["unclassified"] > 0,
    }
