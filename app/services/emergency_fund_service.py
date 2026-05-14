"""Emergency fund targets from essential monthly expenses (EUR base)."""

from __future__ import annotations


def _f(x) -> float:
    try:
        return max(0.0, float(x))
    except (TypeError, ValueError):
        return 0.0


def compute(inputs: dict) -> dict[str, float | dict]:
    """Inputs keys in EUR: housing, food, transport, utilities, subscriptions, insurance, debt, other, buffer_pct, current_savings."""
    parts = {
        "housing": _f(inputs.get("housing")),
        "food": _f(inputs.get("food")),
        "transport": _f(inputs.get("transport")),
        "utilities": _f(inputs.get("utilities")),
        "subscriptions": _f(inputs.get("subscriptions")),
        "insurance": _f(inputs.get("insurance")),
        "debt": _f(inputs.get("debt")),
        "other": _f(inputs.get("other")),
    }
    base_monthly = sum(parts.values())
    buffer_pct = max(0.0, min(50.0, _f(inputs.get("buffer_pct"))))
    monthly = base_monthly * (1.0 + buffer_pct / 100.0)
    targets = {3: round(monthly * 3, 2), 6: round(monthly * 6, 2), 9: round(monthly * 9, 2)}
    savings = _f(inputs.get("current_savings"))

    def prog(months: int) -> dict:
        tgt = targets[months]
        if tgt <= 0:
            return {"target": 0.0, "progress_pct": 100.0 if savings > 0 else 0.0, "still_needed": 0.0}
        pct = min(100.0, round(savings / tgt * 100.0, 1)) if tgt else 0.0
        need = max(0.0, round(tgt - savings, 2))
        return {"target": tgt, "progress_pct": pct, "still_needed": need}

    return {
        "monthly_essential_base": round(base_monthly, 2),
        "buffer_pct": buffer_pct,
        "monthly_with_buffer": round(monthly, 2),
        "targets": targets,
        "current_savings": round(savings, 2),
        "progress": {str(m): prog(m) for m in (3, 6, 9)},
        "breakdown": {k: round(v, 2) for k, v in parts.items()},
    }
