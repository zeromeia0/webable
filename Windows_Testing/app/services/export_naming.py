"""
Central naming convention for every generated download.

    Webable_<Workspace>-<CUR>_<Report-Type>_<Date-or-Range>.<ext>

Examples:
    Webable_Personal-EUR_Spending-Report_2026-01-01_to_2026-09-30.pdf
    Webable_Household-USD_Transactions_2026-10-12.csv
    Webable_Personal-EUR_EOM-Summary_2026-09.pdf
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from urllib.parse import quote

APP_NAME = "Webable"
MAX_SEGMENT_LEN = 40
MAX_FILENAME_LEN = 150

_INVALID = re.compile(r"[^A-Za-z0-9._-]+")
_DASHES = re.compile(r"-{2,}")


def sanitize_segment(value: object, max_len: int = MAX_SEGMENT_LEN) -> str:
    """ASCII-only, spaces -> hyphens, strip characters invalid in filenames on any OS."""
    raw = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    raw = raw.replace("_", "-").strip()
    raw = re.sub(r"\s+", "-", raw)
    raw = _INVALID.sub("", raw)
    raw = _DASHES.sub("-", raw).strip("-.")
    return raw[:max_len].rstrip("-.")


def _fmt_day(d: date | datetime | str | None) -> str | None:
    if d is None or d == "":
        return None
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d")
    if isinstance(d, date):
        return d.isoformat()
    return sanitize_segment(str(d)[:10], 10) or None


def period_label(
    *,
    start: date | datetime | str | None = None,
    end: date | datetime | str | None = None,
    month: str | None = None,
    on: date | datetime | str | None = None,
) -> str:
    """Pick the most specific period: explicit month, a start..end range, or a single day (default today)."""
    if month:
        return sanitize_segment(str(month)[:7], 7)
    s, e = _fmt_day(start), _fmt_day(end)
    if s and e:
        return s if s == e else f"{s}_to_{e}"
    return _fmt_day(on) or datetime.utcnow().strftime("%Y-%m-%d")


def build_filename(
    report_type: str,
    extension: str,
    *,
    workspace_name: str | None = None,
    currency: str | None = None,
    start: date | datetime | str | None = None,
    end: date | datetime | str | None = None,
    month: str | None = None,
    on: date | datetime | str | None = None,
) -> str:
    parts = [APP_NAME]
    ws = sanitize_segment(workspace_name) if workspace_name else ""
    cur = sanitize_segment((currency or "").upper(), 3) if currency else ""
    if ws and cur:
        parts.append(f"{ws}-{cur}")
    elif ws or cur:
        parts.append(ws or cur)
    parts.append(sanitize_segment(report_type) or "Export")
    parts.append(period_label(start=start, end=end, month=month, on=on))
    ext = sanitize_segment(extension.lstrip("."), 8).lower() or "bin"
    stem = "_".join(p for p in parts if p)
    max_stem = MAX_FILENAME_LEN - len(ext) - 1
    if len(stem) > max_stem:
        stem = stem[:max_stem].rstrip("-_.")
    return f"{stem}.{ext}"


def workspace_filename(inst, report_type: str, extension: str, **period) -> str:
    return build_filename(
        report_type,
        extension,
        workspace_name=getattr(inst, "name", None),
        currency=getattr(inst, "currency", None) or "EUR",
        **period,
    )


def content_disposition(filename: str, inline: bool = False) -> str:
    """Content-Disposition header with an ASCII fallback plus RFC 5987 form.

    ``inline=True`` lets the browser display the file instead of downloading it.
    """
    kind = "inline" if inline else "attachment"
    ascii_name = filename.encode("ascii", "replace").decode("ascii").replace('"', "")
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"
