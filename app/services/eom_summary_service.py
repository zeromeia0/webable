"""End-of-month summary orchestration (auto-generation + live preview)."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy.orm import Session

from app.models import DatabaseInstance, User
from app.services import monthly_snapshot_service as mss


def ensure_eom_snapshots(
    db: Session,
    instance: DatabaseInstance,
    user: User,
    *,
    max_months: int = 24,
) -> dict[str, int]:
    """
    Lightweight sync: day-1 previous month + missing completed months (capped).
    Returns counts for logging/UI.
    """
    day_one = mss.ensure_day_one_snapshot(db, instance, user)
    created = mss.generate_missing_completed_month_snapshots(
        db, instance, user, max_months=max_months
    )
    return {"day_one_updated": int(day_one), "new_snapshots": created}


def build_live_preview(
    db: Session,
    instance: DatabaseInstance,
    user: User,
    *,
    month_str: str | None = None,
) -> dict:
    """Current (or selected) month without persisting as finalized snapshot."""
    month_str = month_str or datetime.utcnow().strftime("%Y-%m")
    y, m = mss.month_str_to_parts(month_str)
    py, pm = mss.previous_month(y, m)
    prev_row = mss.get_monthly_snapshot(db, instance.id, py, pm)
    prev_payload = mss.snapshot_row_to_payload(prev_row) if prev_row else None
    if not prev_payload:
        prev_payload = mss.compute_snapshot_payload(
            instance.finance_db_path,
            instance.logic_db_path,
            mss.parts_to_month_str(py, pm),
            include_iefp=bool(user.enable_iefp_mode),
        )
    payload = mss.compute_snapshot_payload(
        instance.finance_db_path,
        instance.logic_db_path,
        month_str,
        include_iefp=bool(user.enable_iefp_mode),
        prev_payload=prev_payload,
    )
    today = date.today()
    is_current = y == today.year and m == today.month
    payload["is_preview"] = is_current and not mss.is_completed_month(y, m, today)
    payload["is_finalized"] = mss.get_monthly_snapshot(db, instance.id, y, m) is not None
    return payload


def resolve_summary_for_display(
    db: Session,
    instance: DatabaseInstance,
    user: User,
    year: int,
    month: int,
) -> dict:
    """Saved snapshot for completed months; live compute for current month if no snapshot."""
    row = mss.get_monthly_snapshot(db, instance.id, year, month)
    if row:
        out = mss.snapshot_row_to_payload(row)
        out["is_preview"] = False
        out["is_finalized"] = True
        return out
    month_str = mss.parts_to_month_str(year, month)
    out = build_live_preview(db, instance, user, month_str=month_str)
    out["is_finalized"] = False
    return out
