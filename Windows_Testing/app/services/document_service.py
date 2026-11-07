"""User-defined PDF categories (Reports → Other documents), stored like bank statements."""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from ..models import DatabaseInstance, Document, DocumentCategory
from .bank_statement_service import (
    sanitize_display_filename,
    sanitize_original_filename,
    sha256_hex,
    validate_pdf_bytes,
)

log = logging.getLogger("webable.documents")

MAX_CATEGORIES = 30


def _clean_category_name(name: str) -> str | None:
    n = re.sub(r"\s+", " ", (name or "").strip())[:80]
    return n or None


def list_categories(db: Session, instance_id: int) -> list[DocumentCategory]:
    return (
        db.query(DocumentCategory)
        .filter(DocumentCategory.instance_id == instance_id)
        .order_by(DocumentCategory.created_at.asc(), DocumentCategory.id.asc())
        .all()
    )


def list_documents(db: Session, category_id: int) -> list[Document]:
    return (
        db.query(Document)
        .filter(Document.category_id == category_id)
        .order_by(Document.created_at.desc())
        .all()
    )


def get_category(db: Session, instance_id: int, category_id: int) -> DocumentCategory | None:
    return (
        db.query(DocumentCategory)
        .filter(DocumentCategory.id == category_id, DocumentCategory.instance_id == instance_id)
        .first()
    )


def get_document(db: Session, instance_id: int, document_id: int) -> Document | None:
    return db.query(Document).filter(Document.id == document_id, Document.instance_id == instance_id).first()


def _name_taken(db: Session, instance_id: int, name: str, exclude_id: int | None = None) -> bool:
    q = db.query(DocumentCategory).filter(DocumentCategory.instance_id == instance_id)
    if exclude_id is not None:
        q = q.filter(DocumentCategory.id != exclude_id)
    return any(c.name.casefold() == name.casefold() for c in q.all())


def create_category(db: Session, instance_id: int, name: str) -> tuple[DocumentCategory | None, str | None]:
    clean = _clean_category_name(name)
    if not clean:
        return None, "Please enter a category name."
    if clean.casefold() == "bank statements":
        return None, "Bank statements already has its own section."
    if _name_taken(db, instance_id, clean):
        return None, "You already have a category with that name."
    if db.query(DocumentCategory).filter(DocumentCategory.instance_id == instance_id).count() >= MAX_CATEGORIES:
        return None, f"You can have at most {MAX_CATEGORIES} categories."
    row = DocumentCategory(instance_id=instance_id, name=clean)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, None


def rename_category(db: Session, cat: DocumentCategory, name: str) -> str | None:
    clean = _clean_category_name(name)
    if not clean:
        return "Please enter a category name."
    if clean.casefold() == "bank statements":
        return "Bank statements already has its own section."
    if _name_taken(db, cat.instance_id, clean, exclude_id=cat.id):
        return "You already have a category with that name."
    cat.name = clean
    db.commit()
    return None


def _unlink(root: Path, rel: str) -> None:
    path = root / rel
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        log.warning("could not delete document file %s", path)


def delete_category(db: Session, root: Path, cat: DocumentCategory) -> None:
    for doc in list(cat.documents):
        _unlink(root, doc.storage_rel_path)
    db.delete(cat)
    db.commit()


def delete_instance_files(db: Session, root: Path, instance_id: int) -> None:
    """Remove every stored document file of a workspace (rows go with the workspace cascade)."""
    for doc in db.query(Document).filter(Document.instance_id == instance_id).all():
        _unlink(root, doc.storage_rel_path)


def find_duplicates(db: Session, cat: DocumentCategory, *, sha256: str, original_filename: str) -> str | None:
    q = db.query(Document).filter(Document.category_id == cat.id)
    if q.filter(Document.sha256 == sha256).first():
        return f"A file with the same content is already in {cat.name}."
    if q.filter(Document.original_filename == original_filename).first():
        return f"A file with the same name is already in {cat.name}."
    return None


def save_document(
    db: Session,
    root: Path,
    inst: DatabaseInstance,
    cat: DocumentCategory,
    user_id: int,
    *,
    content: bytes,
    original_filename: str,
    doc_month: str | None,
    source: str | None,
) -> tuple[Document | None, str | None]:
    ok, err = validate_pdf_bytes(content)
    if not ok:
        return None, err
    month = (doc_month or "").strip()[:7]
    if month and not re.match(r"^\d{4}-\d{2}$", month):
        return None, "Month must be YYYY-MM."
    safe_name = sanitize_original_filename(original_filename)
    digest = sha256_hex(content)
    dup = find_duplicates(db, cat, sha256=digest, original_filename=safe_name)
    if dup:
        return None, dup

    stored = f"{uuid.uuid4().hex}.pdf"
    rel = f"documents/{inst.id}/{stored}"
    dest = root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        dest.write_bytes(content)
    except OSError as exc:
        log.exception("document write failed")
        return None, f"Could not save file: {exc}"

    row = Document(
        instance_id=inst.id,
        category_id=cat.id,
        owner_id=user_id,
        original_filename=safe_name,
        stored_filename=stored,
        doc_month=month or None,
        source=(source or "").strip()[:120] or None,
        file_size=len(content),
        sha256=digest,
        storage_rel_path=rel,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, None


def rename_document(db: Session, row: Document, new_name: str) -> str | None:
    safe = sanitize_display_filename(new_name)
    if not safe:
        return "Please enter a file name."
    if safe == row.original_filename:
        return None
    clash = (
        db.query(Document)
        .filter(Document.category_id == row.category_id, Document.original_filename == safe, Document.id != row.id)
        .first()
    )
    if clash:
        return "Another file in this category already has that name."
    row.original_filename = safe
    db.commit()
    return None


def delete_document(db: Session, root: Path, row: Document) -> None:
    _unlink(root, row.storage_rel_path)
    db.delete(row)
    db.commit()
