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


INVITE_TTL_DAYS = 30
INVITABLE_ROLES = ("viewer", "member", "admin")


def find_user_by_username(db: Session, username: str) -> User | None:
    name = (username or "").strip()
    if not name:
        return None
    exact = db.query(User).filter(User.username == name).first()
    if exact:
        return exact
    return db.query(User).filter(User.username.ilike(name)).first()


def search_usernames(db: Session, actor: User, query: str, limit: int = 8) -> list[str]:
    q = (query or "").strip()
    if len(q) < 2:
        return []
    like = q.replace("%", "").replace("_", "") + "%"
    rows = (
        db.query(User.username)
        .filter(User.username.ilike(like), User.id != actor.id)
        .order_by(User.username.asc())
        .limit(max(1, min(20, int(limit))))
        .all()
    )
    return [r[0] for r in rows]


def _expire_if_needed(invite: WorkspaceInvite) -> None:
    if invite.status == "pending" and invite.expires_at and invite.expires_at < datetime.utcnow():
        invite.status = "expired"


def create_username_invite(
    db: Session,
    workspace_id: int,
    username: str,
    role: str,
    actor: User,
) -> WorkspaceInvite:
    """
    Invite an existing account by username. Relationships are stored by user id;
    the invitee is notified in-app (no e-mail involved).
    """
    from app.services import notification_service

    inst, _member = require_workspace(db, actor, workspace_id, "invite")
    target = find_user_by_username(db, username)
    if not target:
        raise HTTPException(status_code=404, detail=f'No user named "{(username or "").strip()}" exists.')
    if target.id == actor.id:
        raise HTTPException(status_code=400, detail="You cannot invite yourself.")
    if get_membership(db, target.id, workspace_id):
        raise HTTPException(status_code=409, detail=f"{target.username} is already a member of this workspace.")
    pending = (
        db.query(WorkspaceInvite)
        .filter(
            WorkspaceInvite.workspace_id == workspace_id,
            WorkspaceInvite.invitee_user_id == target.id,
            WorkspaceInvite.status == "pending",
        )
        .all()
    )
    for inv in pending:
        _expire_if_needed(inv)
        if inv.status == "pending":
            raise HTTPException(status_code=409, detail=f"{target.username} already has a pending invitation.")
        db.add(inv)

    r = (role or "member").lower()
    if r not in INVITABLE_ROLES:
        r = "member"
    invite = WorkspaceInvite(
        workspace_id=workspace_id,
        email=target.username[:120],
        invitee_user_id=target.id,
        role=r,
        status="pending",
        token=secrets.token_urlsafe(32),
        invited_by_user_id=actor.id,
        expires_at=datetime.utcnow() + timedelta(days=INVITE_TTL_DAYS),
    )
    db.add(invite)
    db.flush()
    notification_service.notify(
        db,
        target.id,
        notification_service.KIND_INVITE_RECEIVED,
        "Workspace invitation",
        f'{actor.username} invited you to collaborate on "{inst.name}".',
        workspace_id=workspace_id,
        invite_id=invite.id,
        actor_user_id=actor.id,
    )
    return invite


def create_invite(
    db: Session,
    workspace_id: int,
    email: str,
    role: str,
    invited_by_user_id: int,
    *,
    expires_days: int = 7,
) -> WorkspaceInvite:
    """Legacy helper kept for compatibility; prefer create_username_invite."""
    actor = db.query(User).filter(User.id == invited_by_user_id).first()
    if actor is None:
        raise HTTPException(status_code=404, detail="Inviting user not found.")
    return create_username_invite(db, workspace_id, email, role, actor)


def _load_invite_for_invitee(db: Session, user: User, invite_id: int) -> WorkspaceInvite:
    invite = db.query(WorkspaceInvite).filter(WorkspaceInvite.id == invite_id).first()
    if not invite or invite.invitee_user_id != user.id:
        raise HTTPException(status_code=404, detail="Invitation not found.")
    _expire_if_needed(invite)
    if invite.status != "pending":
        raise HTTPException(status_code=409, detail=f"This invitation was already {invite.status}.")
    return invite


def respond_to_invite(db: Session, user: User, invite_id: int, accept: bool) -> DatabaseInstance:
    from app.services import notification_service

    invite = _load_invite_for_invitee(db, user, invite_id)
    inst = db.query(DatabaseInstance).filter(DatabaseInstance.id == invite.workspace_id).first()
    if not inst or not inst.is_active:
        invite.status = "cancelled"
        db.add(invite)
        raise HTTPException(status_code=404, detail="Workspace no longer exists.")
    now = datetime.utcnow()
    invite.responded_at = now
    if accept:
        if not get_membership(db, user.id, invite.workspace_id):
            db.add(WorkspaceMember(workspace_id=invite.workspace_id, user_id=user.id, role=invite.role))
        invite.status = "accepted"
        invite.accepted_at = now
        kind = notification_service.KIND_INVITE_ACCEPTED
        verb = "accepted"
    else:
        invite.status = "declined"
        kind = notification_service.KIND_INVITE_DECLINED
        verb = "declined"
    db.add(invite)
    notification_service.mark_invite_notifications_read(db, user.id, invite.id)
    notification_service.notify(
        db,
        invite.invited_by_user_id,
        kind,
        f"Invitation {verb}",
        f'{user.username} {verb} your invitation to "{inst.name}".',
        workspace_id=inst.id,
        invite_id=invite.id,
        actor_user_id=user.id,
    )
    return inst


def cancel_invite(db: Session, actor: User, workspace_id: int, invite_id: int) -> None:
    require_workspace(db, actor, workspace_id, "invite")
    invite = (
        db.query(WorkspaceInvite)
        .filter(WorkspaceInvite.id == invite_id, WorkspaceInvite.workspace_id == workspace_id)
        .first()
    )
    if not invite:
        raise HTTPException(status_code=404, detail="Invitation not found.")
    if invite.status != "pending":
        raise HTTPException(status_code=409, detail=f"This invitation was already {invite.status}.")
    invite.status = "cancelled"
    invite.responded_at = datetime.utcnow()
    db.add(invite)


def pending_invites_for_workspace(db: Session, workspace_id: int) -> list[WorkspaceInvite]:
    rows = (
        db.query(WorkspaceInvite)
        .filter(WorkspaceInvite.workspace_id == workspace_id, WorkspaceInvite.status == "pending")
        .order_by(WorkspaceInvite.created_at.desc())
        .all()
    )
    return [r for r in rows if not (r.expires_at and r.expires_at < datetime.utcnow())]


def accept_invite(db: Session, user: User, token: str) -> DatabaseInstance:
    """Accept via legacy share link; only the invited account may accept."""
    invite = db.query(WorkspaceInvite).filter(WorkspaceInvite.token == token).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found or already used.")
    if invite.invitee_user_id is None and user.username.strip().lower() == invite.email.strip().lower():
        invite.invitee_user_id = user.id
    if invite.invitee_user_id != user.id:
        raise HTTPException(status_code=403, detail="This invitation was sent to a different account.")
    return respond_to_invite(db, user, invite.id, accept=True)


def remove_member(db: Session, workspace_id: int, target_user_id: int, actor: User) -> None:
    from app.services import notification_service

    inst, _m = require_workspace(db, actor, workspace_id, "remove_member")
    target = get_membership(db, target_user_id, workspace_id)
    if not target:
        raise HTTPException(status_code=404, detail="Member not found.")
    if target_user_id == inst.owner_id:
        raise HTTPException(status_code=400, detail="The workspace owner cannot be removed.")
    if target.role == "owner":
        owner_count = (
            db.query(WorkspaceMember)
            .filter(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.role == "owner")
            .count()
        )
        if owner_count <= 1:
            raise HTTPException(status_code=400, detail="Cannot remove the last owner of a workspace.")
    db.delete(target)
    _clear_active_workspace(db, target_user_id, workspace_id)
    if target_user_id != actor.id:
        notification_service.notify(
            db,
            target_user_id,
            notification_service.KIND_MEMBER_REMOVED,
            "Removed from workspace",
            f'{actor.username} removed you from "{inst.name}".',
            workspace_id=workspace_id,
            actor_user_id=actor.id,
        )
    db.commit()
    ensure_at_least_one_owner(db, workspace_id)


def leave_workspace(db: Session, user: User, workspace_id: int) -> None:
    inst, member = require_workspace(db, user, workspace_id, "read")
    if member.role == "owner" or inst.owner_id == user.id:
        raise HTTPException(status_code=400, detail="Owners cannot leave their own workspace. Delete it instead.")
    db.delete(member)
    _clear_active_workspace(db, user.id, workspace_id)
    db.commit()


def _clear_active_workspace(db: Session, user_id: int, workspace_id: int) -> None:
    u = db.query(User).filter(User.id == user_id).first()
    if u and u.active_workspace_id == workspace_id:
        u.active_workspace_id = None
        db.add(u)
