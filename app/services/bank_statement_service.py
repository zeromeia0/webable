"""Secure bank statement PDF storage and metadata."""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from pathlib import Path
from sqlalchemy.orm import Session

from ..models import BankStatement, DatabaseInstance

log = logging.getLogger("webable.bank_statement")

MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MiB
PDF_MAGIC = b"%PDF"


def _statements_dir(root: Path, instance_id: int) -> Path:
    d = root / "statements" / str(instance_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def sanitize_original_filename(name: str) -> str:
    base = Path(name or "statement").name
    base = re.sub(r"[^\w.\-]", "_", base, flags=re.UNICODE)
    if not base.lower().endswith(".pdf"):
        base = (base or "statement") + ".pdf"
    return base[:180]


def validate_pdf_bytes(content: bytes) -> tuple[bool, str]:
    if not content:
        return False, "Empty file."
    if len(content) > MAX_FILE_BYTES:
        return False, f"File too large (max {MAX_FILE_BYTES // (1024 * 1024)} MB)."
    if not content.startswith(PDF_MAGIC):
        return False, "Only PDF files are accepted (invalid file header)."
    # Basic MIME sniff: PDF should contain EOF marker near end (not strict)
    if b"%%EOF" not in content[-2048:]:
        return False, "Invalid or incomplete PDF."
    return True, ""


def sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def optional_text_excerpt(content: bytes, max_chars: int = 8000) -> str | None:
    try:
        from pypdf import PdfReader
        from io import BytesIO

        reader = PdfReader(BytesIO(content))
        if not reader.pages:
            return None
        text = reader.pages[0].extract_text() or ""
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars] if text else None
    except Exception as exc:  # noqa: BLE001
        log.debug("PDF text extract skipped: %s", exc)
        return None


def find_duplicates(
    db: Session,
    instance_id: int,
    *,
    sha256: str,
    original_filename: str,
    statement_month: str,
    bank_name: str | None,
) -> str | None:
    q = db.query(BankStatement).filter(BankStatement.instance_id == instance_id)
    if q.filter(BankStatement.sha256 == sha256).first():
        return "A statement with the same file content is already uploaded."
    if q.filter(BankStatement.original_filename == original_filename).first():
        return "A file with the same original name is already uploaded for this workspace."
    bn = (bank_name or "").strip()
    if bn:
        dup = (
            q.filter(
                BankStatement.statement_month == statement_month,
                BankStatement.bank_name == bn,
            ).first()
        )
        if dup:
            return f"You already have a statement for {statement_month} from this bank."
    return None


def list_for_instance(db: Session, instance_id: int) -> list[BankStatement]:
    return (
        db.query(BankStatement)
        .filter(BankStatement.instance_id == instance_id)
        .order_by(BankStatement.created_at.desc())
        .all()
    )


def get_owned(db: Session, user_id: int, statement_id: int) -> BankStatement | None:
    return (
        db.query(BankStatement)
        .join(DatabaseInstance)
        .filter(
            BankStatement.id == statement_id,
            DatabaseInstance.owner_id == user_id,
        )
        .first()
    )


def save_statement(
    db: Session,
    root: Path,
    inst: DatabaseInstance,
    user_id: int,
    *,
    content: bytes,
    original_filename: str,
    statement_month: str,
    bank_name: str | None,
) -> tuple[BankStatement | None, str | None]:
    ok, err = validate_pdf_bytes(content)
    if not ok:
        log.warning("bank statement validation failed: %s", err)
        return None, err

    sm = (statement_month or "").strip()[:7]
    if not re.match(r"^\d{4}-\d{2}$", sm):
        return None, "Statement month must be YYYY-MM."

    safe_name = sanitize_original_filename(original_filename)
    digest = sha256_hex(content)
    dup = find_duplicates(
        db,
        inst.id,
        sha256=digest,
        original_filename=safe_name,
        statement_month=sm,
        bank_name=bank_name,
    )
    if dup:
        return None, dup

    stored = f"{uuid.uuid4().hex}.pdf"
    rel = f"statements/{inst.id}/{stored}"
    dest = root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)

    try:
        dest.write_bytes(content)
    except OSError as exc:
        log.exception("bank statement write failed")
        return None, f"Could not save file: {exc}"

    excerpt = optional_text_excerpt(content)
    row = BankStatement(
        instance_id=inst.id,
        owner_id=user_id,
        original_filename=safe_name,
        stored_filename=stored,
        statement_month=sm,
        bank_name=(bank_name or "").strip()[:120] or None,
        file_size=len(content),
        sha256=digest,
        storage_rel_path=rel,
        text_excerpt=excerpt,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, None


def delete_statement(db: Session, root: Path, row: BankStatement) -> None:
    path = root / row.storage_rel_path
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        log.warning("could not delete statement file %s", path)
    db.delete(row)
    db.commit()
