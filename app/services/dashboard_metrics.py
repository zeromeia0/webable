"""
Pure helpers for dashboard cards and Mother insights percentages.
"""

from __future__ import annotations

from typing import Any


SAFE_TO_SPEND_DEFAULT_PCT = 25
SAFE_TO_SPEND_OPTIONS = (10, 25, 50, 75, 100)


def safe_to_spend_amount(current_month_savings: float, percentage: float) -> float:
    """Portion of current-month savings the user is willing to spend."""
    if current_month_savings <= 0:
        return 0.0
    pct = max(0.0, min(100.0, float(percentage)))
    return round(current_month_savings * (pct / 100.0), 2)


def safe_to_spend_hint(current_month_savings: float, percentage: float, amount: float) -> str:
    if current_month_savings <= 0:
        return "Savings are low this month, so safe-to-spend is limited."
    if percentage <= 25:
        return "Conservative mode: most of your savings stay protected."
    if percentage >= 75:
        return "Flexible mode: a larger share of this month's savings is available."
    return "Balanced mode: part of this month's savings is available to spend."


def current_month_balance(total_income: float, total_expenses: float) -> float:
    return round(float(total_income) - float(total_expenses), 2)


def format_pct_of_total(part: float, total: float) -> str | None:
    if total <= 0:
        return None
    return f"{(float(part) / float(total)) * 100:.1f}"


def enrich_expense_entry(row: dict[str, Any], total_expenses: float, total_income: float) -> dict[str, Any]:
    amt = float(row.get("amount_eur") or 0)
    pct_exp = format_pct_of_total(amt, total_expenses)
    pct_inc = format_pct_of_total(amt, total_income)
    out = dict(row)
    out["pct_of_expenses"] = pct_exp
    out["pct_of_income"] = pct_inc
    out["pct_expenses_label"] = f"{pct_exp}% of expenses" if pct_exp else "expenses unavailable"
    out["pct_income_label"] = f"{pct_inc}% of income" if pct_inc else "income unavailable"
    return out


def fixed_expenses_summary(fixed_total: float, total_income: float) -> dict[str, Any]:
    """Fixed expenses as % of income (recurring expenses until we tag fixed/variable)."""
    amt = round(float(fixed_total), 2)
    pct = format_pct_of_total(amt, total_income)
    return {"amount_eur": amt, "pct_of_income": pct}


def aggregate_current_month_totals(month_rows: list[dict[str, Any]]) -> dict[str, float]:
    """Sum month_summary dicts across workspaces."""
    income = 0.0
    expenses = 0.0
    savings = 0.0
    fixed = 0.0
    for m in month_rows:
        income += float(m.get("iefp", 0) or 0) + float(m.get("extras", 0) or 0) + float(m.get("oneoff_income_total", 0) or 0)
        exp = float(m.get("expenses", 0) or 0) + float(m.get("oneoff_expense_total", 0) or 0)
        expenses += exp
        fixed += float(m.get("expenses", 0) or 0)
        savings += float(m.get("estimated_savings", 0) or 0)
    return {
        "income_total": round(income, 2),
        "expense_total": round(expenses, 2),
        "fixed_expenses_total": round(fixed, 2),
        "current_month_savings": round(savings, 2),
        "current_month_balance": current_month_balance(income, expenses),
    }


def validate_quick_oneoff(amount: float, description: str, txn_type: str) -> list[str]:
    errors: list[str] = []
    try:
        if float(amount) <= 0:
            errors.append("Amount must be a positive number.")
    except (TypeError, ValueError):
        errors.append("Amount must be a positive number.")
    if not (description or "").strip():
        errors.append("Description is required.")
    if str(txn_type).lower() not in ("income", "expense"):
        errors.append("Transaction type is required.")
    return errors


def wishlist_affordability(price: float, safe_amount: float) -> dict[str, str]:
    price = max(0.0, float(price))
    safe_amount = max(0.0, float(safe_amount))
    if price <= 0:
        return {"label": "Affordable now", "tone": "positive"}
    if safe_amount <= 0:
        return {"label": "Not safe this month", "tone": "negative"}
    if price <= safe_amount:
        pct = (price / safe_amount) * 100 if safe_amount else 100
        if pct <= 50:
            return {"label": "Affordable now", "tone": "positive"}
        return {"label": f"Would use {pct:.0f}% of your safe-to-spend amount", "tone": "warn"}
    need = round(price - safe_amount, 2)
    return {"label": f"Need €{need:,.2f} more", "tone": "negative"}
