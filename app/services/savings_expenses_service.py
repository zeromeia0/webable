"""Aggregate workspace expenses for the Savings Calculator (EUR monthly equivalents)."""

from __future__ import annotations

import re
from typing import Any

from app.services.instance_service import ONEOFF_CATEGORIES, list_finance_items, list_oneoffs_for_month

SAVINGS_CATEGORY_KEYS = (
    "housing",
    "food",
    "transport",
    "utilities",
    "subscriptions",
    "insurance",
    "debt",
    "other",
)

# One-off categories excluded from survival expense totals.
_EXCLUDED_ONEOFF_CATEGORIES = frozenset({"Savings", "Investments"})

_RECURRING_EXCLUDE_RE = re.compile(
    r"\b(savings?|invest(?:ment)?s?|brokerage|portfolio|etf|crypto)\b",
    re.IGNORECASE,
)

_ONEOFF_TO_SAVINGS: dict[str, str] = {
    "Housing": "housing",
    "Food": "food",
    "Transport": "transport",
    "Subscriptions": "subscriptions",
    "Health": "insurance",
    "Shopping": "other",
    "Entertainment": "other",
    "Education": "other",
    "Other": "other",
}

_RECURRING_KEYWORDS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(rent|mortgage|housing|apartment|condo|landlord)\b", re.I), "housing"),
    (re.compile(r"\b(food|grocery|groceries|supermarket|restaurant)\b", re.I), "food"),
    (re.compile(r"\b(transport|uber|taxi|fuel|gas|petrol|metro|bus|train|car)\b", re.I), "transport"),
    (re.compile(r"\b(utilit|electric|water|gas bill|internet|phone|mobile|broadband)\b", re.I), "utilities"),
    (re.compile(r"\b(subscription|netflix|spotify|streaming)\b", re.I), "subscriptions"),
    (re.compile(r"\b(insurance|health|medical|dental|pharmacy)\b", re.I), "insurance"),
    (re.compile(r"\b(debt|loan|credit card|financ)\b", re.I), "debt"),
]


def _empty_categories() -> dict[str, float]:
    return {k: 0.0 for k in SAVINGS_CATEGORY_KEYS}


def recurrence_to_monthly(amount: float, recurrence: str | None) -> float:
    """Convert a recurring line item to an approximate monthly EUR amount."""
    rec = (recurrence or "monthly").lower().strip()
    v = max(0.0, float(amount))
    if rec == "daily":
        return v * 365.0 / 12.0
    if rec == "weekly":
        return v * 52.0 / 12.0
    if rec == "yearly":
        return v / 12.0
    return v


def map_oneoff_category(category: str | None) -> str | None:
    """Map app one-off category to savings bucket, or None if excluded."""
    c = (category or "").strip()
    if c in _EXCLUDED_ONEOFF_CATEGORIES:
        return None
    return _ONEOFF_TO_SAVINGS.get(c, "other")


def map_recurring_expense_name(name: str | None) -> str:
    n = (name or "").strip()
    if _RECURRING_EXCLUDE_RE.search(n):
        return ""
    for pattern, bucket in _RECURRING_KEYWORDS:
        if pattern.search(n):
            return bucket
    return "other"


def should_exclude_recurring_expense(name: str | None) -> bool:
    return map_recurring_expense_name(name) == ""


def summarize_saved_expenses(finance_db: str, month: str | None = None) -> dict[str, Any]:
    """
    Build monthly essential expense snapshot from workspace finance DB (EUR).
    Includes active recurring expenses (normalized to monthly) and expense one-offs in `month`.
    """
    from datetime import datetime

    month_key = (month or datetime.utcnow().strftime("%Y-%m"))[:7]
    categories = _empty_categories()
    recurring_items: list[dict[str, Any]] = []
    oneoff_items: list[dict[str, Any]] = []

    items = list_finance_items(finance_db)
    for exp in items.get("expenses") or []:
        if exp.get("ended"):
            continue
        name = str(exp.get("name") or "")
        if should_exclude_recurring_expense(name):
            continue
        monthly_amt = round(recurrence_to_monthly(float(exp.get("amount") or 0), exp.get("recurrence")), 2)
        if monthly_amt <= 0:
            continue
        bucket = map_recurring_expense_name(name)
        categories[bucket] = round(categories[bucket] + monthly_amt, 2)
        recurring_items.append(
            {
                "name": name,
                "amount_monthly_eur": monthly_amt,
                "recurrence": exp.get("recurrence") or "monthly",
                "category": bucket,
            }
        )

    for o in list_oneoffs_for_month(finance_db, month_key):
        if str(o.get("txn_type", "expense")).lower() != "expense":
            continue
        bucket = map_oneoff_category(str(o.get("category") or "Other"))
        if bucket is None:
            continue
        amt = abs(float(o.get("amount") or 0))
        if amt <= 0:
            continue
        categories[bucket] = round(categories[bucket] + amt, 2)
        oneoff_items.append(
            {
                "name": str(o.get("name") or ""),
                "amount_eur": round(amt, 2),
                "date": str(o.get("date") or ""),
                "source_category": str(o.get("category") or "Other"),
                "category": bucket,
            }
        )

    monthly_total = round(sum(categories.values()), 2)
    return {
        "month": month_key,
        "monthly_total": monthly_total,
        "categories": {k: round(categories[k], 2) for k in SAVINGS_CATEGORY_KEYS},
        "recurring_count": len(recurring_items),
        "oneoff_count": len(oneoff_items),
        "recurring_items": recurring_items,
        "oneoff_items": oneoff_items,
        "has_data": monthly_total > 0,
    }
