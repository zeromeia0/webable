"""
Investment simulation tied to a long-range projection plus an investment horizon.

Monthly contribution
--------------------
For each month index t = 0 .. horizon_months-1:
  - If t is within the saved projection: use that month’s max(0, estimated_savings).
  - If t extends past the projection: use the last projected month’s savings (if
    positive); otherwise the latest earlier month with positive estimated savings
    (so the horizon still gets monthly contributions, not a hard stop at the chart length).

Contribution timing (beginning of month)
----------------------------------------
Each month:
    balance += contribution
    balance *= (1 + monthly_rate)

Monthly rate from stated annual return (percent, e.g. 8 for 8%)
--------------------------------------------------------------
    monthly_rate = (1 + APR)^(1/12) - 1
where APR = annual_rate_pct / 100.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from dateutil.relativedelta import relativedelta


def add_calendar_months(ym: str, delta: int) -> str:
    base = datetime.strptime(f"{ym}-01", "%Y-%m-%d")
    d = base + relativedelta(months=delta)
    return d.strftime("%Y-%m")


def monthly_rate_from_annual_percent(annual_rate_pct: float) -> float:
    """Effective monthly rate: (1 + APR)^(1/12) - 1, APR = annual_rate_pct/100."""
    apr = float(annual_rate_pct) / 100.0
    if apr <= -1.0:
        return 0.0
    if apr == 0.0:
        return 0.0
    return (1.0 + apr) ** (1.0 / 12.0) - 1.0


def tail_positive_monthly_savings(projection_rows: list[dict]) -> float:
    """Latest month in the projection with strictly positive estimated_savings; else 0."""
    for r in reversed(projection_rows):
        s = float(r.get("estimated_savings", 0) or 0)
        if s > 0:
            return s
    return 0.0


def _row_metric(row: dict, key: str) -> float:
    try:
        return float(row.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def parse_projection_rows(metrics: object) -> list[dict]:
    if not isinstance(metrics, list):
        return []
    rows: list[dict] = []
    for r in metrics:
        if not isinstance(r, dict):
            continue
        if "month" not in r or "accumulated" not in r:
            continue
        rows.append(
            {
                "month": str(r.get("month", "")),
                "accumulated": float(r.get("accumulated", 0) or 0),
                "estimated_savings": float(r.get("estimated_savings", 0) or 0),
                "total_before_expenses": _row_metric(r, "total_before_expenses"),
                "expenses": _row_metric(r, "expenses"),
                "extras": _row_metric(r, "extras"),
                "one_off": _row_metric(r, "one_off"),
                "iefp": _row_metric(r, "iefp"),
            }
        )
    return rows


@dataclass
class SimulationSummary:
    final_investment_balance: float
    final_cumulative_contributed: float
    final_compounded_profit: float
    final_accumulated_wealth: float | None


def compound_investment_monthly_beginning(
    *,
    starting_balance: float,
    monthly_contribution: float,
    annual_rate_pct: float,
    total_months: int,
) -> tuple[float, float, float]:
    """
    Standalone reference engine: beginning-of-month add, then grow.
    Returns (end_balance, total_contributions, interest_profit).
    """
    i_m = monthly_rate_from_annual_percent(annual_rate_pct)
    balance = float(starting_balance)
    cum = 0.0
    c = round(float(monthly_contribution), 2)
    for _ in range(max(0, int(total_months))):
        balance += c
        balance *= 1.0 + i_m
        cum = round(cum + c, 2)
    end = round(balance, 2)
    return end, cum, round(end - cum, 2)


def run_monthly_simulation(
    projection_rows: list[dict],
    invest_pct: float,
    annual_rate_pct: float,
    horizon_years: float,
) -> dict:
    """
    Returns JSON-serializable dict: months, series arrays, summary, meta.
    Monetary values rounded to 2 decimals for UI/PDF parity.
    """
    if not projection_rows:
        return {
            "meta": {},
            "summary": {},
            "rows": [],
        }

    pct = max(0.0, min(100.0, float(invest_pct)))
    horizon_months = max(1, int(round(float(horizon_years) * 12)))
    i_m = monthly_rate_from_annual_percent(annual_rate_pct)
    n_proj = len(projection_rows)
    last_month = projection_rows[-1]["month"]
    last_acc = float(projection_rows[-1]["accumulated"])
    last_row_sav = max(0.0, float(projection_rows[-1].get("estimated_savings", 0) or 0))
    # Horizon extends past the chart: keep contributing using the terminal month’s savings,
    # or (if that month is zero) the most recent month with positive projected savings.
    tail_sav = last_row_sav if last_row_sav > 0 else tail_positive_monthly_savings(projection_rows)

    months: list[str] = []
    wealth: list[float | None] = []
    investment_balance: list[float] = []
    cumulative_contributed: list[float] = []
    compounded_profit: list[float] = []
    contributions: list[float] = []

    balance = 0.0
    cum_c = 0.0

    for t in range(horizon_months):
        if t < n_proj:
            ym = projection_rows[t]["month"]
            acc = float(projection_rows[t]["accumulated"])
            sav = max(0.0, float(projection_rows[t]["estimated_savings"]))
        else:
            ym = add_calendar_months(last_month, t - (n_proj - 1))
            acc = last_acc
            sav = tail_sav

        c = round((pct / 100.0) * sav, 2)
        cum_c = round(cum_c + c, 2)
        balance += c
        balance *= 1.0 + i_m

        months.append(ym)
        wealth.append(round(acc, 2) if t < n_proj else round(last_acc, 2))
        contributions.append(c)
        investment_balance.append(round(balance, 2))
        cumulative_contributed.append(cum_c)
        compounded_profit.append(round(balance - cum_c, 2))

    summary = SimulationSummary(
        final_investment_balance=investment_balance[-1],
        final_cumulative_contributed=cumulative_contributed[-1],
        final_compounded_profit=compounded_profit[-1],
        final_accumulated_wealth=last_acc,
    )

    return {
        "meta": {
            "invest_pct": pct,
            "annual_rate_pct": float(annual_rate_pct),
            "horizon_years": float(horizon_years),
            "horizon_months": horizon_months,
            "effective_monthly_rate": round(i_m, 8),
            "projection_months": n_proj,
            "extended_monthly_savings_base": round(tail_sav, 2),
        },
        "summary": {
            "final_investment_balance": summary.final_investment_balance,
            "final_cumulative_contributed": summary.final_cumulative_contributed,
            "final_compounded_profit": summary.final_compounded_profit,
            "final_accumulated_wealth": summary.final_accumulated_wealth,
        },
        "rows": [
            {
                "month": months[k],
                "accumulated_wealth": wealth[k],
                "contribution": contributions[k],
                "cumulative_contributed": cumulative_contributed[k],
                "investment_balance": investment_balance[k],
                "compounded_profit": compounded_profit[k],
            }
            for k in range(len(months))
        ],
    }


def effective_monthly_rate_from_compounding(annual_rate_pct: float, compounding_per_year: int) -> float:
    """Per-month rate so 12 steps match (1 + APR/n)^n over one year."""
    n = max(1, int(compounding_per_year))
    apr = float(annual_rate_pct) / 100.0
    if apr <= -1.0:
        return 0.0
    if apr == 0.0:
        return 0.0
    return (1.0 + apr / n) ** (n / 12.0) - 1.0


def run_investment_calculator(
    *,
    initial_balance: float,
    monthly_contribution: float,
    annual_rate_pct: float,
    years: float,
    compounding_per_year: int = 12,
    contribution_timing: str = "beginning",
) -> dict:
    """
    Month-by-month balance with configurable compounding frequency and contribution timing.
    Total contributions = initial_balance + sum of monthly contributions (each month).
    """
    months = max(1, int(round(float(years) * 12)))
    r_m = effective_monthly_rate_from_compounding(annual_rate_pct, compounding_per_year)
    timing = (contribution_timing or "beginning").lower()
    if timing not in ("beginning", "end"):
        timing = "beginning"

    balance = round(float(initial_balance), 2)
    cum_deposits = round(float(initial_balance), 2)
    c = round(float(monthly_contribution), 2)
    balances: list[float] = []
    contributions_series: list[float] = []
    cumulative_series: list[float] = []
    interest_series: list[float] = []

    for _ in range(months):
        if timing == "beginning":
            balance += c
            cum_deposits = round(cum_deposits + c, 2)
            balance *= 1.0 + r_m
        else:
            balance *= 1.0 + r_m
            balance += c
            cum_deposits = round(cum_deposits + c, 2)
        balances.append(round(balance, 2))
        contributions_series.append(c)
        cumulative_series.append(round(cum_deposits, 2))
        interest_series.append(round(balance - cum_deposits, 2))

    final_b = balances[-1] if balances else round(balance, 2)
    profit = round(final_b - cum_deposits, 2)
    labels = [f"M{i+1}" for i in range(len(balances))]

    return {
        "meta": {
            "months": months,
            "annual_rate_pct": float(annual_rate_pct),
            "compounding_per_year": int(compounding_per_year),
            "effective_monthly_rate": round(r_m, 8),
            "contribution_timing": timing,
        },
        "summary": {
            "final_balance": final_b,
            "total_contributions": cum_deposits,
            "total_interest_profit": profit,
            "monthly_contribution": c,
            "initial_balance": round(float(initial_balance), 2),
        },
        "series": {
            "labels": labels,
            "balance": balances,
            "monthly_contribution": contributions_series,
            "cumulative_contributed": cumulative_series,
            "interest_earned": interest_series,
        },
    }
