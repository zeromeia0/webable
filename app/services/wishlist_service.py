"""User wishlist items (app database)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models import WishlistItem

PRIORITIES = ("low", "medium", "high")


def list_items(db: Session, owner_id: int) -> list[WishlistItem]:
    return (
        db.query(WishlistItem)
        .filter(WishlistItem.owner_id == owner_id)
        .order_by(WishlistItem.created_at.desc())
        .all()
    )


def add_item(
    db: Session,
    owner_id: int,
    name: str,
    price_eur: float,
    priority: str = "medium",
    deadline: str | None = None,
) -> WishlistItem:
    pr = (priority or "medium").strip().lower()
    if pr not in PRIORITIES:
        pr = "medium"
    item = WishlistItem(
        owner_id=owner_id,
        name=name.strip(),
        price_eur=max(0.0, float(price_eur)),
        priority=pr,
        deadline=(deadline or "").strip() or None,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def delete_item(db: Session, owner_id: int, item_id: int) -> bool:
    row = db.query(WishlistItem).filter(WishlistItem.id == item_id, WishlistItem.owner_id == owner_id).first()
    if not row:
        return False
    db.delete(row)
    db.commit()
    return True
