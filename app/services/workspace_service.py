"""
Shared workspace membership, authorization, and active workspace helpers.

DatabaseInstance is the workspace; finance data lives in per-workspace SQLite files.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Literal

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app.models import DatabaseInstance, User, WorkspaceInvite, WorkspaceMember

ACTIVE_WORKSPACE_COOKIE = "webable_active_workspace"

Role = Literal["owner", "admin", "member", "viewer"]

ROLE_RANK = {"viewer": 0, "member": 1, "admin": 2, "owner": 3}

READ_ACTIONS = frozenset({"read", "view"})
WRITE_ACTIONS = frozenset({"write", "create", "edit", "delete"})
EXPORT_ACTIONS = frozenset({"export"})
IMPORT_ACTIONS = frozenset({"import"})
INVITE_ACTIONS = frozenset({"invite"})
MANAGE_MEMBERS_ACTIONS = frozenset({"remove_member", "change_role"})
DELETE_WORKSPACE_ACTIONS = frozenset({"delete_workspace"})


def min_role_for_action(action: str) -> Role:
    a = (action or "read").lower()
    if a in DELETE_WORKSPACE_ACTIONS or a in MANAGE_MEMBERS_ACTIONS:
        return "owner"
    if a in INVITE_ACTIONS or a in IMPORT_ACTIONS:
        return "admin"
    if a in EXPORT_ACTIONS:
        return "member"
    if a in WRITE_ACTIONS:
        return "member"
    return "viewer"


def role_allows(role: str | None, action: str) -> bool:
    r = (role or "viewer").lower()
    needed = min_role_for_action(action)
    return ROLE_RANK.get(r, -1) >= ROLE_RANK.get(needed, 99)


def get_membership(db: Session, user_id: int, workspace_id: int) -> WorkspaceMember | None:
    return (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user_id)
        .first()
    )


def list_user_workspaces(db: Session, user: User) -> list[DatabaseInstance]:
    return (
        db.query(DatabaseInstance)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == DatabaseInstance.id)
        .filter(WorkspaceMember.user_id == user.id, DatabaseInstance.is_active.is_(True))
        .order_by(DatabaseInstance.created_at.desc())
        .all()
    )


def list_memberships(db: Session, user: User) -> list[WorkspaceMember]:
    return db.query(WorkspaceMember).filter(WorkspaceMember.user_id == user.id).all()


def membership_map(db: Session, user: User) -> dict[int, str]:
    return {m.workspace_id: m.role for m in list_memberships(db, user)}


def require_workspace(
    db: Session,
    user: User,
    workspace_id: int,
    action: str = "read",
) -> tuple[DatabaseInstance, WorkspaceMember]:
    member = get_membership(db, user.id, workspace_id)
    if not member:
        raise HTTPException(status_code=404, detail="Workspace not found or access denied.")
    if not role_allows(member.role, action):
        raise HTTPException(status_code=403, detail="You do not have permission for this action.")
    inst = db.query(DatabaseInstance).filter(DatabaseInstance.id == workspace_id).first()
    if not inst:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    return inst, member


def add_owner_member(db: Session, workspace_id: int, user_id: int) -> WorkspaceMember:
    existing = get_membership(db, user_id, workspace_id)
    if existing:
        return existing
    row = WorkspaceMember(workspace_id=workspace_id, user_id=user_id, role="owner")
    db.add(row)
    return row


def ensure_at_least_one_owner(db: Session, workspace_id: int) -> None:
    owners = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.role == "owner")
        .count()
    )
    if owners < 1:
        raise HTTPException(status_code=400, detail="A workspace must always have at least one owner.")


def get_active_workspace_id(request: Request, user: User) -> int | None:
    cookie = request.cookies.get(ACTIVE_WORKSPACE_COOKIE)
    if cookie:
        try:
            return int(cookie)
        except ValueError:
            pass
    return user.active_workspace_id


def set_active_workspace(response, db: Session, user: User, workspace_id: int) -> None:
    member = get_membership(db, user.id, workspace_id)
    if not member:
        raise HTTPException(status_code=404, detail="Workspace not found or access denied.")
    user.active_workspace_id = workspace_id
    db.add(user)
    db.commit()
    response.set_cookie(ACTIVE_WORKSPACE_COOKIE, str(workspace_id), httponly=True, samesite="lax")


def resolve_active_workspace(
    db: Session,
    user: User,
    request: Request | None = None,
) -> tuple[list[DatabaseInstance], DatabaseInstance | None]:
    instances = list_user_workspaces(db, user)
    if not instances:
        return [], None

    preferred: int | None = None
    if request is not None:
        preferred = get_active_workspace_id(request, user)

    active: DatabaseInstance | None = None
    if preferred is not None:
        active = next((i for i in instances if i.id == preferred), None)

    if active is None and len(instances) == 1:
        active = instances[0]
    elif active is None:
        active = instances[0]

    if active and user.active_workspace_id != active.id:
        user.active_workspace_id = active.id
        db.add(user)
        db.commit()

    return instances, active


def create_invite(
    db: Session,
    workspace_id: int,
    email: str,
    role: str,
    invited_by_user_id: int,
    *,
    expires_days: int = 7,
) -> WorkspaceInvite:
    role = (role or "member").lower()
    if role not in ROLE_RANK:
        role = "member"
    if role == "owner":
        role = "admin"
    token = secrets.token_urlsafe(32)
    invite = WorkspaceInvite(
        workspace_id=workspace_id,
        email=email.strip().lower(),
        role=role,
        token=token,
        invited_by_user_id=invited_by_user_id,
        expires_at=datetime.utcnow() + timedelta(days=expires_days),
    )
    db.add(invite)
    return invite


def accept_invite(db: Session, user: User, token: str) -> DatabaseInstance:
    invite = db.query(WorkspaceInvite).filter(WorkspaceInvite.token == token).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found or already used.")
    if invite.accepted_at is not None:
        raise HTTPException(status_code=400, detail="This invite has already been accepted.")
    if invite.expires_at and invite.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="This invite has expired.")

    email_match = user.username.strip().lower() == invite.email.strip().lower()
    if not email_match:
        raise HTTPException(
            status_code=403,
            detail="This invite was sent to a different email address. Log in with the invited account.",
        )

    existing = get_membership(db, user.id, invite.workspace_id)
    if existing:
        invite.accepted_at = datetime.utcnow()
        db.add(invite)
    else:
        db.add(WorkspaceMember(workspace_id=invite.workspace_id, user_id=user.id, role=invite.role))
        invite.accepted_at = datetime.utcnow()
        db.add(invite)

    inst = db.query(DatabaseInstance).filter(DatabaseInstance.id == invite.workspace_id).first()
    if not inst:
        raise HTTPException(status_code=404, detail="Workspace no longer exists.")
    return inst


def remove_member(db: Session, workspace_id: int, target_user_id: int, actor: User) -> None:
    require_workspace(db, actor, workspace_id, "remove_member")
    target = get_membership(db, target_user_id, workspace_id)
    if not target:
        raise HTTPException(status_code=404, detail="Member not found.")
    if target.role == "owner":
        owner_count = (
            db.query(WorkspaceMember)
            .filter(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.role == "owner")
            .count()
        )
        if owner_count <= 1:
            raise HTTPException(status_code=400, detail="Cannot remove the last owner of a workspace.")
    db.delete(target)
    db.commit()
    ensure_at_least_one_owner(db, workspace_id)
