"""Shared expense panel payload for dashboard and global Expenses FAB."""

from __future__ import annotations

from typing import Any

from app.models import DatabaseInstance
from app.services import dashboard_metrics, instance_service


def _money(value: float) -> str:
    return f"EUR {float(value):,.2f}"


def build_expense_panel_payload(
    instances: list[DatabaseInstance],
    month_totals: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Recurring expense entries with % labels for the floating Expenses panel."""
    expense_entries: list[dict[str, Any]] = []
    for ins in instances:
        items = instance_service.list_finance_items(ins.finance_db_path)
        for row in items["expenses"]:
            if row.get("ended"):
                continue
            expense_entries.append(
                {
                    "name": str(row["name"]),
                    "amount_eur": round(float(row["amount"]), 2),
                    "workspace": ins.name if len(instances) > 1 else None,
                }
            )
    expense_entries.sort(key=lambda x: x["amount_eur"], reverse=True)
    recurring_expense_total = round(sum(e["amount_eur"] for e in expense_entries), 2)

    mt = month_totals or {}
    month_income = float(mt.get("income_total") or 0)
    if month_income <= 0:
        for ins in instances:
            items = instance_service.list_finance_items(ins.finance_db_path)
            month_income += sum(float(i["amount"]) for i in items["incomes"] if not i.get("ended"))

    expense_entries_enriched = [
        dashboard_metrics.enrich_expense_entry(row, recurring_expense_total, month_income) for row in expense_entries
    ]
    expense_income_pct = dashboard_metrics.format_pct_of_total(recurring_expense_total, month_income)
    if expense_income_pct:
        summary = f"Total expenses: {_money(recurring_expense_total)} — {expense_income_pct}% of income"
    else:
        summary = f"Total expenses: {_money(recurring_expense_total)} — income unavailable"

    return {
        "entries": expense_entries_enriched,
        "summary": summary,
        "total_eur": recurring_expense_total,
    }
