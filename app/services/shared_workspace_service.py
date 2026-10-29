"""
Shared workspaces: a copy of a personal workspace that several users collaborate on.

Inviting someone to a personal workspace never exposes it directly. Instead a shared copy is
created (once per source workspace) and the invitation points at the copy. Every member links
one of their own personal workspaces to the shared one:

- incomes from every linked workspace are always mirrored into the shared copy, so the shared
  totals are the members' incomes summed together;
- expenses are only mirrored when the shared workspace opts in (include_member_expenses);
  otherwise members enter shared expenses manually, which is the preferred flow.

Mirrored rows carry a ``linked_source`` key in the shared finance file, are read-only there and
are rebuilt by ``sync_shared_workspace`` whenever the shared workspace is opened. Because the
mirrored rows live in the shared file itself, every feature that reads a workspace file
(dashboard, reports, analysis, timeline, projections, exports) sees the combined data.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import CategoryBudget, DatabaseInstance, User, WorkspaceMember
from app.services import instance_service, savings_expenses_service

log = logging.getLogger("webable")

KIND_PERSONAL = "personal"
KIND_SHARED = "shared"
SHARED_SUFFIX = " (Shared)"


def is_shared(inst: DatabaseInstance | None) -> bool:
    return bool(inst) and (inst.kind or KIND_PERSONAL) == KIND_SHARED


def _slug(name: str) -> str:
    return "".join(c.lower() if c.isalnum() else "_" for c in name).strip("_") or "db"


def _copy_sqlite(src: str, dst: str) -> None:
    """Consistent copy of a SQLite file (safe while the source is open elsewhere)."""
    src_conn = sqlite3.connect(src)
    dst_conn = sqlite3.connect(dst)
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()


def find_shared_copy(db: Session, source: DatabaseInstance) -> DatabaseInstance | None:
    return (
        db.query(DatabaseInstance)
        .filter(
            DatabaseInstance.source_workspace_id == source.id,
            DatabaseInstance.kind == KIND_SHARED,
            DatabaseInstance.is_active.is_(True),
        )
        .order_by(DatabaseInstance.created_at.asc())
        .first()
    )


def create_shared_copy(db: Session, source: DatabaseInstance, actor: User, root: Path) -> DatabaseInstance:
    """
    Copy ``source`` into a new shared workspace owned by ``actor``.

    Everything is copied except recurring incomes: those come back as linked rows mirrored from
    each member's workspace (the actor's link is ``source``), so they are never counted twice.
    """
    if is_shared(source):
        raise HTTPException(status_code=400, detail="This workspace is already shared.")
    name = (source.name[: 120 - len(SHARED_SUFFIX)] + SHARED_SUFFIX).strip()
    stamp = int(datetime.utcnow().timestamp())
    finance_path, logic_path = instance_service.instance_paths(root, actor.id, stamp, f"{_slug(name)}_{uuid4().hex[:8]}")
    _copy_sqlite(source.finance_db_path, finance_path)
    _copy_sqlite(source.logic_db_path, logic_path)

    conn = sqlite3.connect(finance_path)
    try:
        instance_service._ensure_all(conn)
        conn.execute("DELETE FROM rendimentos")
        conn.commit()
    finally:
        conn.close()

    shared = DatabaseInstance(
        owner_id=actor.id,
        name=name,
        mode=source.mode or "general",
        currency=source.currency or "EUR",
        kind=KIND_SHARED,
        source_workspace_id=source.id,
        include_member_expenses=False,
        finance_db_path=finance_path,
        logic_db_path=logic_path,
        last_sync_status="Shared copy created",
        last_activity_at=datetime.utcnow(),
    )
    db.add(shared)
    db.flush()
    for b in db.query(CategoryBudget).filter(CategoryBudget.instance_id == source.id).all():
        db.add(CategoryBudget(instance_id=shared.id, category=b.category, monthly_limit_eur=b.monthly_limit_eur))
    db.add(WorkspaceMember(workspace_id=shared.id, user_id=actor.id, role="owner", linked_workspace_id=source.id))
    db.flush()
    sync_shared_workspace(db, shared)
    return shared


def get_or_create_shared_copy(db: Session, source: DatabaseInstance, actor: User, root: Path) -> tuple[DatabaseInstance, bool]:
    existing = find_shared_copy(db, source)
    if existing:
        return existing, False
    return create_shared_copy(db, source, actor, root), True


# ---------------------------------------------------------------------------
# Member links
# ---------------------------------------------------------------------------


def linkable_workspaces(db: Session, user: User, shared: DatabaseInstance) -> list[DatabaseInstance]:
    """Personal workspaces the user owns, in the shared workspace's currency."""
    rows = (
        db.query(DatabaseInstance)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == DatabaseInstance.id)
        .filter(
            WorkspaceMember.user_id == user.id,
            WorkspaceMember.role == "owner",
            DatabaseInstance.is_active.is_(True),
            DatabaseInstance.kind != KIND_SHARED,
        )
        .order_by(DatabaseInstance.created_at.asc())
        .all()
    )
    cur = (shared.currency or "EUR").upper()
    return [w for w in rows if (w.currency or "EUR").upper() == cur]


def default_link_for(db: Session, user: User, shared: DatabaseInstance) -> int | None:
    options = linkable_workspaces(db, user, shared)
    if not options:
        return None
    active = next((w for w in options if w.id == user.active_workspace_id), None)
    return (active or options[0]).id


def set_member_link(db: Session, shared: DatabaseInstance, user: User, linked_workspace_id: int | None) -> WorkspaceMember:
    member = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.workspace_id == shared.id, WorkspaceMember.user_id == user.id)
        .first()
    )
    if not member:
        raise HTTPException(status_code=404, detail="You are not a member of this workspace.")
    if linked_workspace_id is not None:
        allowed = {w.id for w in linkable_workspaces(db, user, shared)}
        if linked_workspace_id not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"You can only link a personal workspace you own that uses {shared.currency or 'EUR'}.",
            )
    member.linked_workspace_id = linked_workspace_id
    db.add(member)
    db.flush()
    return member


def _linked_sources(db: Session, shared: DatabaseInstance) -> list[tuple[WorkspaceMember, User, DatabaseInstance]]:
    """(member, user, linked workspace) for members whose link is still valid."""
    out = []
    rows = (
        db.query(WorkspaceMember, User)
        .join(User, User.id == WorkspaceMember.user_id)
        .filter(WorkspaceMember.workspace_id == shared.id)
        .order_by(WorkspaceMember.created_at.asc())
        .all()
    )
    for member, user in rows:
        if not member.linked_workspace_id:
            continue
        linked = db.query(DatabaseInstance).filter(DatabaseInstance.id == member.linked_workspace_id).first()
        if not linked or not linked.is_active or is_shared(linked):
            continue
        if (linked.currency or "EUR").upper() != (shared.currency or "EUR").upper():
            continue
        still_member = (
            db.query(WorkspaceMember)
            .filter(WorkspaceMember.workspace_id == linked.id, WorkspaceMember.user_id == user.id)
            .first()
        )
        if not still_member or not Path(linked.finance_db_path).is_file():
            continue
        out.append((member, user, linked))
    return out


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------


def _mirror_expenses_from(shared: DatabaseInstance, linked: DatabaseInstance) -> bool:
    # The source workspace's expenses were copied into the shared one at creation time.
    return bool(shared.include_member_expenses) and linked.id != shared.source_workspace_id


def _desired_rows(db: Session, shared: DatabaseInstance) -> tuple[dict[str, tuple], dict[str, tuple]]:
    incomes: dict[str, tuple] = {}
    expenses: dict[str, tuple] = {}
    for _member, user, linked in _linked_sources(db, shared):
        items = instance_service.list_finance_items(linked.finance_db_path)
        for inc in items["incomes"]:
            if inc.get("linked_source"):
                continue
            key = f"ws{linked.id}:income:{inc['id']}"
            incomes[key] = (
                f"{user.username} · {inc['name']}",
                float(inc["amount"]),
                inc.get("recurrence") or "monthly",
                1 if inc.get("ended") else 0,
                inc.get("start_date"),
                inc.get("end_date"),
            )
        if not _mirror_expenses_from(shared, linked):
            continue
        for exp in items["expenses"]:
            if exp.get("linked_source"):
                continue
            key = f"ws{linked.id}:expense:{exp['id']}"
            expenses[key] = (
                f"{user.username} · {exp['name']}",
                float(exp["amount"]),
                exp.get("recurrence") or "monthly",
                1 if exp.get("ended") else 0,
                exp.get("start_date"),
                exp.get("end_date"),
                exp.get("category") or "Other",
                exp.get("expense_type"),
            )
    return incomes, expenses


_INCOME_COLS = ("nome", "valor", "recurrence", "ended", "start_date", "end_date")
_EXPENSE_COLS = _INCOME_COLS + ("category", "expense_type")


def _apply(cur: sqlite3.Cursor, table: str, desired: dict[str, tuple], cols: tuple[str, ...]) -> int:
    col_sql = ", ".join(cols)
    cur.execute(f"SELECT id, linked_source, {col_sql} FROM {table} WHERE linked_source IS NOT NULL")
    existing = {row[1]: (row[0], tuple(row[2:])) for row in cur.fetchall()}
    changes = 0
    for src, (rid, _vals) in existing.items():
        if src not in desired:
            cur.execute(f"DELETE FROM {table} WHERE id = ?", (rid,))
            changes += 1
    sets = ", ".join(f"{c} = ?" for c in cols)
    marks = ", ".join("?" for _ in cols)
    for src, vals in desired.items():
        if src in existing:
            rid, current = existing[src]
            if current != vals:
                cur.execute(f"UPDATE {table} SET {sets}, ativo = 1 WHERE id = ?", (*vals, rid))
                changes += 1
        else:
            cur.execute(f"INSERT INTO {table} ({col_sql}, ativo, linked_source) VALUES ({marks}, 1, ?)", (*vals, src))
            changes += 1
    return changes


def sync_shared_workspace(db: Session, shared: DatabaseInstance) -> int:
    """Bring mirrored rows in a shared workspace up to date. Returns the number of rows changed."""
    if not is_shared(shared) or not Path(shared.finance_db_path).is_file():
        return 0
    incomes, expenses = _desired_rows(db, shared)
    conn = sqlite3.connect(shared.finance_db_path)
    try:
        instance_service._ensure_all(conn)
        cur = conn.cursor()
        changes = _apply(cur, "rendimentos", incomes, _INCOME_COLS)
        changes += _apply(cur, "gastos", expenses, _EXPENSE_COLS)
        if changes:
            conn.commit()
    finally:
        conn.close()
    return changes


def sync_if_shared(db: Session, inst: DatabaseInstance | None) -> None:
    if not is_shared(inst):
        return
    try:
        sync_shared_workspace(db, inst)
    except Exception as exc:  # never block page loads on a sync problem
        log.warning("shared workspace sync failed for %s: %s", inst.id, exc)


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


def member_contributions(db: Session, shared: DatabaseInstance) -> dict[int, dict]:
    """Per user id: linked workspace and its monthly-equivalent income / expense totals."""
    out: dict[int, dict] = {}
    for _member, user, linked in _linked_sources(db, shared):
        items = instance_service.list_finance_items(linked.finance_db_path)
        income = sum(
            savings_expenses_service.recurrence_to_monthly(i["amount"], i.get("recurrence"))
            for i in items["incomes"]
            if not i.get("ended")
        )
        expense = sum(
            savings_expenses_service.recurrence_to_monthly(e["amount"], e.get("recurrence"))
            for e in items["expenses"]
            if not e.get("ended")
        )
        out[user.id] = {
            "workspace": linked,
            "monthly_income": round(income, 2),
            "monthly_expenses": round(expense, 2),
            "expenses_mirrored": _mirror_expenses_from(shared, linked),
        }
    return out


def combined_saved_expenses(db: Session, shared: DatabaseInstance, month: str | None = None) -> dict:
    """
    Savings Calculator "use saved expenses" for a shared workspace: the shared workspace's own
    expenses plus every member's linked workspace expenses, regardless of the mirroring toggle.
    Mirrored rows in the shared file are skipped so nothing is counted twice.
    """
    base = savings_expenses_service.summarize_saved_expenses(shared.finance_db_path, month, skip_linked=True)
    categories = dict(base["categories"])
    recurring = list(base["recurring_items"])
    oneoffs = list(base["oneoff_items"])
    members = [{"username": "Shared workspace", "workspace": shared.name, "monthly_total": base["monthly_total"]}]
    for _member, user, linked in _linked_sources(db, shared):
        if linked.id == shared.source_workspace_id:
            # Its expenses were copied into the shared workspace and are already in `base`.
            continue
        part = savings_expenses_service.summarize_saved_expenses(linked.finance_db_path, base["month"])
        for k, v in part["categories"].items():
            categories[k] = round(categories.get(k, 0.0) + v, 2)
        recurring += [{**r, "name": f"{user.username} · {r['name']}"} for r in part["recurring_items"]]
        oneoffs += [{**o, "name": f"{user.username} · {o['name']}"} for o in part["oneoff_items"]]
        members.append({"username": user.username, "workspace": linked.name, "monthly_total": part["monthly_total"]})
    total = round(sum(categories.values()), 2)
    return {
        **base,
        "monthly_total": total,
        "categories": categories,
        "recurring_count": len(recurring),
        "oneoff_count": len(oneoffs),
        "recurring_items": recurring,
        "oneoff_items": oneoffs,
        "has_data": total > 0,
        "shared": True,
        "members": members,
    }
