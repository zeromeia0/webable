"""Simple user notes (app database)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import UserNote


def list_notes(db: Session, owner_id: int) -> list[UserNote]:
    return (
        db.query(UserNote)
        .filter(UserNote.owner_id == owner_id)
        .order_by(UserNote.created_at.desc())
        .all()
    )


def add_note(db: Session, owner_id: int, body: str) -> UserNote:
    note = UserNote(owner_id=owner_id, body=body.strip())
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


def delete_note(db: Session, owner_id: int, note_id: int) -> bool:
    row = db.query(UserNote).filter(UserNote.id == note_id, UserNote.owner_id == owner_id).first()
    if not row:
        return False
    db.delete(row)
    db.commit()
    return True
