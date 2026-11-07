"""Secure bank statement PDF storage and metadata."""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from datetime import date
from pathlib import Path
from sqlalchemy.orm import Session

from ..models import BankStatement, DatabaseInstance, WorkspaceMember

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


_FORBIDDEN_NAME_CHARS = re.compile(r'[\x00-\x1f<>:"/\\|?*]')


def sanitize_display_filename(name: str) -> str | None:
    """
    Clean a user-typed new name for a stored PDF. Only the download/display name changes,
    never the stored file. Spaces and accents are kept; path and reserved characters are not.
    Returns None when nothing usable is left.
    """
    base = _FORBIDDEN_NAME_CHARS.sub("_", (name or "").strip())
    base = re.sub(r"\s+", " ", base).strip()
    if base.lower().endswith(".pdf"):
        base = base[:-4]
    base = base.strip(" .")
    if not base:
        return None
    return base[:176] + ".pdf"


def rename_statement(db: Session, row: BankStatement, new_name: str) -> str | None:
    """Change only the filename shown and used for downloads. Returns an error message or None."""
    safe = sanitize_display_filename(new_name)
    if not safe:
        return "Please enter a file name."
    if safe == row.original_filename:
        return None
    clash = (
        db.query(BankStatement)
        .filter(
            BankStatement.instance_id == row.instance_id,
            BankStatement.original_filename == safe,
            BankStatement.id != row.id,
        )
        .first()
    )
    if clash:
        return "Another statement in this workspace already has that name."
    row.original_filename = safe
    db.commit()
    return None


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


_DATE = r"(\d{1,2}[-/.]\d{1,2}[-/.]\d{4}|\d{4}-\d{2}-\d{2})"
# "Período de 01-09-2026 a 30-09-2026" (Crédito Agrícola and other PT banks), "Statement period: 01/09/2026 - 30/09/2026",
# "Period from 2026-09-01 to 2026-09-30", ...
_PERIOD_PATTERNS = [
    re.compile(r"per[ií]odo\s*(?:de|:)?\s*" + _DATE + r"\s*(?:a|até|-|–)\s*" + _DATE, re.I),
    re.compile(r"(?:statement\s+)?period\s*(?:from|:)?\s*" + _DATE + r"\s*(?:to|-|–|until)\s*" + _DATE, re.I),
    re.compile(r"\bfrom\s+" + _DATE + r"\s+to\s+" + _DATE, re.I),
]


def _parse_date(s: str) -> date | None:
    s = s.strip()
    try:
        if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
            return date.fromisoformat(s)
        d, m, y = re.split(r"[-/.]", s)
        return date(int(y), int(m), int(d))
    except ValueError:
        return None


def detect_statement_period(text: str | None) -> dict | None:
    """
    Find the period a statement covers from its text. Banks often name the file after the issue
    month (e.g. the "October" statement covers September), so the period printed inside wins.
    Returns {"month": "YYYY-MM", "start": date, "end": date} using the month most of the period falls in.
    """
    if not text:
        return None
    flat = re.sub(r"\s+", " ", text)
    for pat in _PERIOD_PATTERNS:
        for m in pat.finditer(flat):
            start, end = _parse_date(m.group(1)), _parse_date(m.group(2))
            if not start or not end:
                continue
            if end < start:
                start, end = end, start
            if (end - start).days > 400:
                continue
            mid = start + (end - start) / 2
            return {"month": mid.strftime("%Y-%m"), "start": start, "end": end}
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
        .join(WorkspaceMember, WorkspaceMember.workspace_id == DatabaseInstance.id)
        .filter(
            BankStatement.id == statement_id,
            WorkspaceMember.user_id == user_id,
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
    """Save a statement. The period printed in the PDF overrides the typed month; the returned row carries ``detection``."""
    ok, err = validate_pdf_bytes(content)
    if not ok:
        log.warning("bank statement validation failed: %s", err)
        return None, err

    excerpt = optional_text_excerpt(content)
    detected = detect_statement_period(excerpt)
    typed = (statement_month or "").strip()[:7]
    if detected:
        sm = detected["month"]
    elif re.match(r"^\d{4}-\d{2}$", typed):
        sm = typed
    elif typed:
        return None, "Statement month must be YYYY-MM."
    else:
        return None, "Couldn't find the statement period in this PDF — please pick the month it covers."
    detection = {
        "detected": bool(detected),
        "typed_month": typed or None,
        "statement_month": sm,
        "period_start": detected["start"].isoformat() if detected else None,
        "period_end": detected["end"].isoformat() if detected else None,
        "corrected": bool(detected and typed and typed != sm),
    }

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
    row.detection = detection  # transient, for the upload response
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
