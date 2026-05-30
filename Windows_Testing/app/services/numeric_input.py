"""Strict decimal parsing — rejects scientific notation and non-numeric strings."""

from __future__ import annotations

import re
from typing import Any

# Optional leading minus; digits; optional single decimal part (no exponent).
_DECIMAL_RE = re.compile(r"^-?(\d+)(\.\d+)?$")


def is_valid_decimal_string(value: Any) -> bool:
    if value is None:
        return False
    s = str(value).strip().replace(",", ".")
    if not s or "e" in s.lower():
        return False
    return _DECIMAL_RE.match(s) is not None


def parse_decimal(
    value: Any,
    *,
    allow_negative: bool = False,
    min_value: float | None = None,
    max_value: float | None = None,
) -> float:
    """
    Parse a standard decimal string. Raises ValueError for invalid input.
    """
    if not is_valid_decimal_string(value):
        raise ValueError("invalid decimal")
    s = str(value).strip().replace(",", ".")
    n = float(s)
    if not allow_negative and n < 0:
        raise ValueError("negative not allowed")
    if min_value is not None and n < min_value:
        raise ValueError("below minimum")
    if max_value is not None and n > max_value:
        raise ValueError("above maximum")
    return n


def parse_positive_decimal(value: Any, *, min_value: float = 0, max_value: float | None = None) -> float:
    """Parse amount fields (must be > 0 unless min_value allows zero)."""
    n = parse_decimal(value, allow_negative=False, min_value=min_value, max_value=max_value)
    if min_value == 0 and n == 0:
        raise ValueError("must be positive")
    return n
