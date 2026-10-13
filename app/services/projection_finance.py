"""
Investment simulation tied to a long-range projection plus an investment horizon.

Monthly contribution
--------------------
For each month index t = 0 .. horizon_months-1:
  - If t is within the saved projection: use that month’s max(0, estimated_savings).
  - If t extends past the projection: use the last projected month’s savings (if
    positive); otherwise the latest earlier month with positive estimated savings
    (so the horizon still gets monthly contributions, not a hard stop at the chart length).

Contribution timing
-------------------
Beginning of month (default for the projection-linked view):
    balance = (balance + contribution) * (1 + monthly_rate)
End of month:
    balance = balance * (1 + monthly_rate) + contribution

Contributions vs. growth
------------------------
total_contributed = initial amount + every monthly deposit
compound_growth   = balance - total_contributed      (may be negative for negative returns)
Intermediate values are never rounded; rounding happens only for display/summary output.

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


MIN_ANNUAL_RATE_PCT = -50.0
MAX_ANNUAL_RATE_PCT = 50.0


def clamp_annual_rate(annual_rate_pct: float) -> float:
    try:
        v = float(annual_rate_pct)
    except (TypeError, ValueError):
        return 0.0
    if v != v:
        return 0.0
    return max(MIN_ANNUAL_RATE_PCT, min(MAX_ANNUAL_RATE_PCT, v))


def monthly_rate_from_annual_percent(annual_rate_pct: float) -> float:
    """Effective monthly rate: (1 + APR)^(1/12) - 1, APR = annual_rate_pct/100 (effective annual)."""
    apr = float(annual_rate_pct) / 100.0
    if apr <= -1.0:
        return -1.0
    if apr == 0.0:
        return 0.0
    return (1.0 + apr) ** (1.0 / 12.0) - 1.0


def normalize_timing(timing: str | None, default: str = "end") -> str:
    t = (timing or default).lower().strip()
    return t if t in ("beginning", "end") else default


def compound_growth_series(
    *,
    initial_amount: float,
    contributions: list[float],
    monthly_rate: float,
    timing: str = "end",
) -> list[dict]:
    """
    Core month-by-month engine shared by every projection.

    `contributions[k]` is the deposit for month k+1. Returns one row per month with
    unrounded floats: contribution, total_contributed, balance, growth.
    """
    timing = normalize_timing(timing)
    balance = float(initial_amount)
    contributed = float(initial_amount)
    growth_factor = 1.0 + float(monthly_rate)
    rows: list[dict] = []
    for k, c in enumerate(contributions):
        c = float(c)
        if timing == "beginning":
            balance = (balance + c) * growth_factor
        else:
            balance = balance * growth_factor + c
        contributed += c
        rows.append(
            {
                "month_index": k + 1,
                "contribution": c,
                "total_contributed": contributed,
                "balance": balance,
                "growth": balance - contributed,
            }
        )
    return rows


def reconciled_summary(total_contributed: float, balance: float) -> dict:
    """Display rounding that guarantees contributions + growth == final balance (to the cent)."""
    contrib = round(float(total_contributed), 2)
    final = round(float(balance), 2)
    return {"total_contributions": contrib, "compound_growth": round(final - contrib, 2), "final_balance": final}


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
    n = max(0, int(total_months))
    rows = compound_growth_series(
        initial_amount=float(starting_balance),
        contributions=[float(monthly_contribution)] * n,
        monthly_rate=monthly_rate_from_annual_percent(annual_rate_pct),
        timing="beginning",
    )
    balance = rows[-1]["balance"] if rows else float(starting_balance)
    cum = float(monthly_contribution) * n
    end = round(balance, 2)
    cum_r = round(cum, 2)
    return end, cum_r, round(end - cum_r, 2)


def run_monthly_simulation(
    projection_rows: list[dict],
    invest_pct: float,
    annual_rate_pct: float,
    horizon_years: float,
    *,
    initial_amount: float = 0.0,
    contribution_timing: str = "beginning",
) -> dict:
    """
    Returns JSON-serializable dict: months, series arrays, summary, meta.
    Series values are unrounded; summary values are rounded for display and reconcile
    (cumulative contributed + compounded profit == final balance).
    """
    if not projection_rows:
        return {
            "meta": {},
            "summary": {},
            "rows": [],
        }

    pct = max(0.0, min(100.0, float(invest_pct)))
    rate = clamp_annual_rate(annual_rate_pct)
    initial = max(0.0, float(initial_amount or 0))
    timing = normalize_timing(contribution_timing, "beginning")
    horizon_months = max(1, int(round(float(horizon_years) * 12)))
    i_m = monthly_rate_from_annual_percent(rate)
    n_proj = len(projection_rows)
    last_month = projection_rows[-1]["month"]
    last_acc = float(projection_rows[-1]["accumulated"])
    last_row_sav = max(0.0, float(projection_rows[-1].get("estimated_savings", 0) or 0))
    # Horizon extends past the chart: keep contributing using the terminal month’s savings,
    # or (if that month is zero) the most recent month with positive projected savings.
    tail_sav = last_row_sav if last_row_sav > 0 else tail_positive_monthly_savings(projection_rows)

    months: list[str] = []
    wealth: list[float] = []
    contributions: list[float] = []
    for t in range(horizon_months):
        if t < n_proj:
            ym = projection_rows[t]["month"]
            acc = float(projection_rows[t]["accumulated"])
            sav = max(0.0, float(projection_rows[t]["estimated_savings"]))
        else:
            ym = add_calendar_months(last_month, t - (n_proj - 1))
            acc = last_acc
            sav = tail_sav
        months.append(ym)
        wealth.append(acc)
        contributions.append((pct / 100.0) * sav)

    engine_rows = compound_growth_series(
        initial_amount=initial, contributions=contributions, monthly_rate=i_m, timing=timing
    )
    final = engine_rows[-1]
    rec = reconciled_summary(final["total_contributed"], final["balance"])

    return {
        "meta": {
            "invest_pct": pct,
            "annual_rate_pct": rate,
            "horizon_years": float(horizon_years),
            "horizon_months": horizon_months,
            "effective_monthly_rate": round(i_m, 8),
            "projection_months": n_proj,
            "extended_monthly_savings_base": round(tail_sav, 2),
            "initial_amount": initial,
            "contribution_timing": timing,
            "rate_convention": "effective_annual",
        },
        "summary": {
            "initial_amount": round(initial, 2),
            "final_investment_balance": rec["final_balance"],
            "final_cumulative_contributed": rec["total_contributions"],
            "final_compounded_profit": rec["compound_growth"],
            "final_accumulated_wealth": last_acc,
        },
        "rows": [
            {
                "month": months[k],
                "month_index": k + 1,
                "accumulated_wealth": wealth[k],
                "contribution": engine_rows[k]["contribution"],
                "cumulative_contributed": engine_rows[k]["total_contributed"],
                "investment_balance": engine_rows[k]["balance"],
                "compounded_profit": engine_rows[k]["growth"],
            }
            for k in range(len(months))
        ],
    }


def effective_monthly_rate_from_compounding(annual_rate_pct: float, compounding_per_year: int | None) -> float:
    """
    Per-month rate.

    compounding_per_year falsy/0 -> the stated rate is an *effective annual* return:
        (1 + APR)^(1/12) - 1
    compounding_per_year = n    -> nominal APR compounded n times a year:
        (1 + APR/n)^(n/12) - 1
    """
    if not compounding_per_year:
        return monthly_rate_from_annual_percent(annual_rate_pct)
    n = max(1, int(compounding_per_year))
    apr = float(annual_rate_pct) / 100.0
    if apr == 0.0:
        return 0.0
    base = 1.0 + apr / n
    if base <= 0.0:
        return -1.0
    return base ** (n / 12.0) - 1.0


def run_investment_calculator(
    *,
    initial_balance: float,
    monthly_contribution: float,
    annual_rate_pct: float,
    years: float,
    compounding_per_year: int | None = 12,
    contribution_timing: str = "beginning",
) -> dict:
    """
    Long-term projection: initial amount + fixed monthly deposits, compounded monthly.
    Total contributions = initial_balance + sum of monthly contributions.
    Compound growth = balance - total contributions.
    """
    months = max(1, int(round(float(years) * 12)))
    rate = clamp_annual_rate(annual_rate_pct)
    n = int(compounding_per_year or 0)
    r_m = effective_monthly_rate_from_compounding(rate, n)
    timing = normalize_timing(contribution_timing, "beginning")
    initial = max(0.0, float(initial_balance or 0))
    c = max(0.0, float(monthly_contribution or 0))

    rows = compound_growth_series(initial_amount=initial, contributions=[c] * months, monthly_rate=r_m, timing=timing)
    final = rows[-1]
    rec = reconciled_summary(final["total_contributed"], final["balance"])

    return {
        "meta": {
            "months": months,
            "annual_rate_pct": rate,
            "compounding_per_year": n,
            "rate_convention": "effective_annual" if n == 0 else f"nominal_compounded_{n}x",
            "effective_monthly_rate": round(r_m, 8),
            "contribution_timing": timing,
        },
        "summary": {
            "final_balance": rec["final_balance"],
            "total_contributions": rec["total_contributions"],
            "total_interest_profit": rec["compound_growth"],
            "compound_growth": rec["compound_growth"],
            "monthly_contribution": round(c, 2),
            "initial_balance": round(initial, 2),
            "months": months,
        },
        "series": {
            "labels": [f"Month {r['month_index']}" for r in rows],
            "month_index": [r["month_index"] for r in rows],
            "balance": [r["balance"] for r in rows],
            "monthly_contribution": [r["contribution"] for r in rows],
            "cumulative_contributed": [r["total_contributed"] for r in rows],
            "interest_earned": [r["growth"] for r in rows],
        },
    }
