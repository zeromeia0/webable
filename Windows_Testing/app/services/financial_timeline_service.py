"""Narrative financial timeline from existing data and monthly snapshots."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any

from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import Session

from app.models import DatabaseInstance, User
from app.services import instance_service, monthly_snapshot_service as mss, notes_service, wishlist_service


def _event(
    *,
    date_s: str,
    type_: str,
    title: str,
    amount: float | None = None,
    description: str = "",
    severity: str = "normal",
    source: str = "system",
) -> dict[str, Any]:
    return {
        "date": date_s,
        "type": type_,
        "title": title,
        "amount": amount,
        "description": description,
        "severity": severity,
        "source": source,
    }


def _is_large_expense(amount: float, rank: int, total_expenses: float, total_income: float) -> bool:
    if rank < 3:
        return True
    if total_expenses > 0 and amount / total_expenses > 0.20:
        return True
    if total_income > 0 and amount / total_income > 0.10:
        return True
    return False


def build_timeline_events(
    db: Session,
    user: User,
    instance: DatabaseInstance,
    *,
    month_filter: str | None = None,
    type_filter: str | None = None,
    include_iefp: bool = False,
    max_events: int = 200,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    items = instance_service.list_finance_items(instance.finance_db_path)

    # Recurring fixed expenses — first day of filtered month or current month
    if month_filter:
        y, m = mss.month_str_to_parts(month_filter)
        anchor = date(y, m, 1).isoformat()
        sm = instance_service.month_summary(
            instance.finance_db_path, instance.logic_db_path, month_filter, include_iefp=include_iefp
        )
        total_exp = float(sm.get("expenses") or 0) + float(sm.get("oneoff_expense_total") or 0)
        total_inc = float(sm.get("total_before_expenses") or 0)
    else:
        anchor = date.today().replace(day=1).isoformat()
        now_m = datetime.utcnow().strftime("%Y-%m")
        sm = instance_service.month_summary(
            instance.finance_db_path, instance.logic_db_path, now_m, include_iefp=include_iefp
        )
        total_exp = float(sm.get("expenses") or 0) + float(sm.get("oneoff_expense_total") or 0)
        total_inc = float(sm.get("total_before_expenses") or 0)

    for e in items["expenses"]:
        if e.get("ended"):
            continue
        if month_filter and type_filter == "income":
            continue
        events.append(
            _event(
                date_s=anchor,
                type_="fixed_expense",
                title=str(e.get("name") or "Expense"),
                amount=-round(float(e.get("amount") or 0), 2),
                description="Recurring expense",
                source="recurring",
            )
        )

    for i in items["incomes"]:
        if i.get("ended"):
            continue
        if month_filter and type_filter == "expense":
            continue
        events.append(
            _event(
                date_s=anchor,
                type_="income",
                title=str(i.get("name") or "Income"),
                amount=round(float(i.get("amount") or 0), 2),
                description="Recurring income",
                source="recurring",
            )
        )

    # One-off transactions
    month_expense_amounts: list[tuple[str, float]] = []
    for o in items["oneoffs"]:
        d = str(o.get("date") or "")[:10]
        if not d:
            continue
        if month_filter and not d.startswith(month_filter):
            continue
        if str(o.get("txn_type", "expense")).lower() != "income":
            month_expense_amounts.append((str(o.get("name") or "Expense"), abs(float(o.get("amount") or 0))))

    month_expense_amounts.sort(key=lambda x: x[1], reverse=True)
    rank_map = {name: i for i, (name, _) in enumerate(month_expense_amounts)}

    for o in items["oneoffs"]:
        d = str(o.get("date") or "")[:10]
        if not d:
            continue
        if month_filter and not d.startswith(month_filter):
            continue
        is_income = str(o.get("txn_type", "expense")).lower() == "income"
        if is_income:
            if type_filter == "expense":
                continue
            events.append(
                _event(
                    date_s=d,
                    type_="income",
                    title=str(o.get("name") or "Income"),
                    amount=round(abs(float(o.get("amount") or 0)), 2),
                    description="One-time income",
                    source="transaction",
                )
            )
            continue
        if type_filter == "income":
            continue
        amt = abs(float(o.get("amount") or 0))
        name = str(o.get("name") or "Expense")
        rank = rank_map.get(name, 99)
        large = _is_large_expense(amt, rank, total_exp, total_inc)
        cat = o.get("category") or "Other"
        events.append(
            _event(
                date_s=d,
                type_="large_expense" if large else "expense",
                title=name,
                amount=-round(amt, 2),
                description=f"{cat} · one-time",
                severity="highlight" if large else "normal",
                source="transaction",
            )
        )

    # Monthly snapshots as timeline anchors
    snapshots = mss.list_monthly_snapshots(db, instance.id)
    for snap in snapshots:
        ms = snap.get("month_str") or ""
        if month_filter and ms != month_filter:
            continue
        if type_filter and type_filter not in ("snapshot", "insight", None, ""):
            if type_filter != "snapshot":
                continue
        d = f"{ms}-01"
        events.append(
            _event(
                date_s=d,
                type_="snapshot",
                title=f"Monthly summary · {snap.get('month_label', ms)}",
                amount=snap.get("net_balance"),
                description="; ".join((snap.get("summary_lines") or [])[:2]),
                severity="normal",
                source="snapshot",
            )
        )
        comp = snap.get("comparison") or {}
        if comp.get("plain_summary"):
            events.append(
                _event(
                    date_s=d,
                    type_="insight",
                    title="Compared with last month",
                    description=str(comp.get("plain_summary")),
                    severity="normal",
                    source="snapshot",
                )
            )
        fixed_pct = snap.get("fixed_expenses_percent_income")
        if fixed_pct:
            events.append(
                _event(
                    date_s=d,
                    type_="insight",
                    title="Fixed expenses share",
                    description=f"Fixed expenses used {fixed_pct}% of income.",
                    severity="normal",
                    source="snapshot",
                )
            )
        top = snap.get("top_expenses") or []
        if top:
            t0 = top[0]
            events.append(
                _event(
                    date_s=d,
                    type_="insight",
                    title="Largest expense",
                    description=f"{t0.get('name')} — €{float(t0.get('amount_eur', 0)):,.2f}",
                    severity="normal",
                    source="snapshot",
                )
            )

    # Notes (user-wide)
    if not type_filter or type_filter == "note":
        for n in notes_service.list_notes(db, user.id)[:40]:
            created = n.created_at.date().isoformat() if n.created_at else ""
            if month_filter and not created.startswith(month_filter):
                continue
            body = (n.body or "").strip()
            preview = body[:120] + ("…" if len(body) > 120 else "")
            events.append(
                _event(
                    date_s=created,
                    type_="note",
                    title="Note",
                    description=preview,
                    source="note",
                )
            )

    # Wishlist
    if not type_filter or type_filter == "wishlist":
        for w in wishlist_service.list_items(db, user.id)[:30]:
            created = w.created_at.date().isoformat() if w.created_at else ""
            if month_filter and not created.startswith(month_filter):
                continue
            events.append(
                _event(
                    date_s=created,
                    type_="wishlist",
                    title=str(w.name),
                    amount=-round(float(w.price_eur or 0), 2),
                    description=f"Wishlist · {w.priority} priority",
                    source="wishlist",
                )
            )

    events.sort(key=lambda e: (e.get("date") or "", e.get("type") or ""), reverse=True)
    if type_filter:
        events = [e for e in events if e.get("type") == type_filter]
    return events[:max_events]


def group_events_by_date(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in events:
        grouped[e.get("date") or "unknown"].append(e)
    out = []
    for d in sorted(grouped.keys(), reverse=True):
        out.append({"date": d, "events": grouped[d]})
    return out
