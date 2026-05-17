"""Aggregated analytics for the Analysis dashboard (EUR base)."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any

from dateutil.relativedelta import relativedelta

from app.services import instance_service, projection_finance, spending_report


def _month_keys_ending(n: int, end_month: str) -> list[str]:
    """Return n consecutive YYYY-MM strings ending at end_month (oldest first)."""
    base = datetime.strptime(end_month + "-01", "%Y-%m-%d").date()
    out: list[str] = []
    for i in range(n):
        d = base - relativedelta(months=(n - 1 - i))
        out.append(d.strftime("%Y-%m"))
    return out


def _top_n_from_pairs(pairs: list[tuple[str, float]], n: int = 3) -> list[dict[str, Any]]:
    m: dict[str, float] = defaultdict(float)
    for k, v in pairs:
        kk = (k or "").strip() or "Unnamed"
        m[kk] += abs(float(v or 0))
    total = sum(m.values()) or 1.0
    ranked = sorted(m.items(), key=lambda x: x[1], reverse=True)[:n]
    return [{"label": a, "amount_eur": round(b, 2), "pct": round(100.0 * b / total, 1)} for a, b in ranked]


def _compound_savings_series(projection_rows: list[dict]) -> dict[str, Any]:
    """Compound growth on projected monthly savings (same engine as workspace investment chart)."""
    if not projection_rows:
        return {"labels": [], "values": [], "available": False}
    horizon = max(1.0, min(40.0, len(projection_rows) / 12.0 + 2.0))
    sim = projection_finance.run_monthly_simulation(
        projection_rows,
        invest_pct=100.0,
        annual_rate_pct=5.0,
        horizon_years=horizon,
    )
    rows = sim.get("rows") or []
    if not rows:
        return {"labels": [], "values": [], "available": False}
    labels = [str(r.get("month", "")) for r in rows]
    values = [round(float(r.get("investment_balance", 0) or 0), 2) for r in rows]
    return {
        "labels": labels,
        "values": values,
        "available": True,
        "annual_rate_pct": 5.0,
        "invest_pct": 100.0,
    }


def build_workspace_analytics(
    finance_db: str,
    logic_db: str,
    *,
    include_iefp: bool,
    current_month: str,
    statement_count: int = 0,
    latest_statement_month: str | None = None,
    projection_summary: dict[str, Any] | None = None,
    projection_rows: list[dict] | None = None,
) -> dict[str, Any]:
    items = instance_service.list_finance_items(finance_db)
    cur = instance_service.month_summary(finance_db, logic_db, current_month, include_iefp=include_iefp)
    prev_m = (datetime.strptime(current_month + "-01", "%Y-%m-%d").date() - relativedelta(months=1)).strftime("%Y-%m")
    prev = instance_service.month_summary(finance_db, logic_db, prev_m, include_iefp=include_iefp)
    cur_sav = float(cur.get("estimated_savings", 0))
    prev_sav = float(prev.get("estimated_savings", 0))
    mom_pct: float | None
    if prev_sav == 0:
        mom_pct = 100.0 if cur_sav != 0 else 0.0
    else:
        mom_pct = round(100.0 * (cur_sav - prev_sav) / abs(prev_sav), 1)

    income_pairs: list[tuple[str, float]] = []
    for i in items["incomes"]:
        if not i.get("ended"):
            income_pairs.append((str(i["name"]), float(i["amount"])))
    for o in items["oneoffs"]:
        if str(o.get("txn_type", "expense")).lower() == "income":
            income_pairs.append((str(o.get("name")), float(o.get("amount") or 0)))

    expense_pairs: list[tuple[str, float]] = []
    for i in items["expenses"]:
        if not i.get("ended"):
            expense_pairs.append((str(i["name"]), float(i["amount"])))
    for o in items["oneoffs"]:
        if str(o.get("txn_type", "expense")).lower() != "income":
            label = f'{str(o.get("category", "Other"))}: {str(o.get("name", ""))[:40]}'
            expense_pairs.append((label, float(o.get("amount") or 0)))

    top_income = _top_n_from_pairs(income_pairs, 3)
    top_expense = _top_n_from_pairs(expense_pairs, 3)

    months_6 = _month_keys_ending(6, current_month)
    trend: list[dict[str, Any]] = []
    for mk in months_6:
        sm = instance_service.month_summary(finance_db, logic_db, mk, include_iefp=include_iefp)
        trend.append(
            {
                "month": mk,
                "savings_eur": float(sm.get("estimated_savings", 0)),
                "inflow_eur": float(sm.get("total_before_expenses", 0)),
                "recurring_expense_eur": float(sm.get("expenses", 0)),
                "oneoff_expense_eur": float(sm.get("oneoff_expense_total", 0)),
            }
        )

    end_d = date.today()
    start_d = end_d - relativedelta(months=6)
    rec_inc = sum(float(i["amount"]) for i in items["incomes"] if not i.get("ended"))
    rec_exp = sum(float(i["amount"]) for i in items["expenses"] if not i.get("ended"))
    rep = spending_report.build_spending_report(
        items["oneoffs"],
        recurring_income_monthly=rec_inc,
        recurring_expense_monthly=rec_exp,
        start=start_d,
        end=end_d,
    )
    cat_break = list(rep.get("top_categories") or [])[:8]
    oneoff_spend_6m = float((rep.get("totals") or {}).get("oneoff_expenses") or 0)

    suggested_6m = round(rec_exp * 6 + oneoff_spend_6m, 2)

    insights: list[str] = []
    if top_expense:
        insights.append(
            f"Largest spending signal: “{top_expense[0]['label']}” "
            f"(~{top_expense[0]['amount_eur']:.0f} EUR in the combined view)."
        )
    if cur_sav < 0:
        insights.append("This month’s net savings estimate is negative — review one-time spikes and recurring bills.")
    elif mom_pct is not None and mom_pct < -15:
        insights.append(f"Savings vs prior month moved about {mom_pct:.0f}% — worth checking what changed.")

    compound = _compound_savings_series(projection_rows or [])

    return {
        "current_month": current_month,
        "headline_savings_eur": round(cur_sav, 2),
        "mom": {
            "prev_month": prev_m,
            "savings_delta_eur": round(cur_sav - prev_sav, 2),
            "savings_delta_pct": mom_pct,
        },
        "top_income_sources": top_income,
        "top_expense_sources": top_expense,
        "monthly_trend": trend,
        "category_spend_6m": cat_break,
        "emergency_fund_hint": {
            "recurring_expenses_monthly_eur": round(rec_exp, 2),
            "suggested_6m_buffer_eur": suggested_6m,
            "note": "Rough buffer = 6× recurring expenses + one-off spend in the last 6 months (not tax advice).",
        },
        "statements": {"count": int(statement_count), "latest_month": latest_statement_month},
        "projection": projection_summary or {"available": False},
        "compound_savings": compound,
        "insights": insights[:5],
    }
