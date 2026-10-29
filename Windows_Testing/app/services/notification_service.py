"""
Persistent in-app notifications (stored in webable_app.db).

Notifications are delivered when the recipient loads or refreshes a page; the bell polls
`/api/notifications` so new items also appear while a page stays open.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import DatabaseInstance, Notification, User, WorkspaceInvite

KIND_INVITE_RECEIVED = "workspace_invite"
KIND_INVITE_ACCEPTED = "invite_accepted"
KIND_INVITE_DECLINED = "invite_declined"
KIND_MEMBER_REMOVED = "member_removed"


def notify(
    db: Session,
    user_id: int,
    kind: str,
    title: str,
    body: str = "",
    *,
    workspace_id: int | None = None,
    invite_id: int | None = None,
    actor_user_id: int | None = None,
) -> Notification:
    row = Notification(
        user_id=user_id,
        kind=kind,
        title=title[:160],
        body=body or "",
        workspace_id=workspace_id,
        invite_id=invite_id,
        actor_user_id=actor_user_id,
    )
    db.add(row)
    return row


def unread_count(db: Session, user: User) -> int:
    return db.query(Notification).filter(Notification.user_id == user.id, Notification.is_read.is_(False)).count()


def list_for_user(db: Session, user: User, limit: int = 30) -> list[Notification]:
    return (
        db.query(Notification)
        .filter(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(max(1, min(100, int(limit))))
        .all()
    )


def mark_read(db: Session, user: User, notification_id: int) -> bool:
    row = (
        db.query(Notification)
        .filter(Notification.id == notification_id, Notification.user_id == user.id)
        .first()
    )
    if not row:
        return False
    if not row.is_read:
        row.is_read = True
        row.read_at = datetime.utcnow()
        db.add(row)
    return True


def mark_all_read(db: Session, user: User) -> int:
    rows = db.query(Notification).filter(Notification.user_id == user.id, Notification.is_read.is_(False)).all()
    now = datetime.utcnow()
    for row in rows:
        row.is_read = True
        row.read_at = now
        db.add(row)
    return len(rows)


def mark_invite_notifications_read(db: Session, user_id: int, invite_id: int) -> None:
    now = datetime.utcnow()
    for row in (
        db.query(Notification)
        .filter(Notification.user_id == user_id, Notification.invite_id == invite_id, Notification.is_read.is_(False))
        .all()
    ):
        row.is_read = True
        row.read_at = now
        db.add(row)


def serialize(db: Session, row: Notification) -> dict[str, Any]:
    invite_state = None
    if row.invite_id is not None:
        inv = db.query(WorkspaceInvite).filter(WorkspaceInvite.id == row.invite_id).first()
        invite_state = inv.status if inv else "cancelled"
    ws_name = None
    if row.workspace_id is not None:
        ws = db.query(DatabaseInstance).filter(DatabaseInstance.id == row.workspace_id).first()
        ws_name = ws.name if ws else None
    return {
        "id": row.id,
        "kind": row.kind,
        "title": row.title,
        "body": row.body,
        "is_read": bool(row.is_read),
        "created_at": row.created_at.isoformat() + "Z" if row.created_at else None,
        "workspace_id": row.workspace_id,
        "workspace_name": ws_name,
        "invite_id": row.invite_id,
        "invite_status": invite_state,
        # Accept/Decline only make sense for an invite that is still pending.
        "actionable": row.kind == KIND_INVITE_RECEIVED and invite_state == "pending",
    }
