"""FX rates (EUR base), cached on disk and refreshed every 8 hours."""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

# Frankfurter is free, no API key; ECB-based daily rates.
FRANKFURTER_URL = "https://api.frankfurter.app/latest?from=EUR&to=USD,GBP,BRL"
REFRESH_INTERVAL_SEC = 8 * 3600
SUPPORTED = ("EUR", "USD", "GBP", "BRL")

_lock = threading.Lock()
_state: dict[str, Any] = {
    "rates": {},
    "updated_at": None,
    "fetch_error": None,
    "using_fallback": True,
}


def _cache_path(root: Path) -> Path:
    return root / "fx_cache.json"


def _load_disk(root: Path) -> None:
    p = _cache_path(root)
    if not p.exists():
        return
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and isinstance(raw.get("rates"), dict):
            with _lock:
                _state["rates"] = {k: float(v) for k, v in raw["rates"].items() if k in ("USD", "GBP", "BRL")}
                _state["updated_at"] = raw.get("updated_at")
                _state["using_fallback"] = bool(raw.get("using_fallback", False))
                _state["fetch_error"] = raw.get("fetch_error")
    except (OSError, ValueError, TypeError):
        pass


def _save_disk(root: Path) -> None:
    p = _cache_path(root)
    try:
        root.mkdir(parents=True, exist_ok=True)
        with _lock:
            payload = {
                "rates": _state["rates"],
                "updated_at": _state["updated_at"],
                "using_fallback": _state["using_fallback"],
                "fetch_error": _state["fetch_error"],
            }
        p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        pass


def fetch_rates_live(root: Path) -> bool:
    """Pull fresh rates from Frankfurter. Returns True if HTTP parse succeeded."""
    try:
        with urlopen(FRANKFURTER_URL, timeout=20) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        rates = body.get("rates") or {}
        out: dict[str, float] = {}
        for c in ("USD", "GBP", "BRL"):
            if c in rates:
                out[c] = float(rates[c])
        if len(out) != 3:
            return False
        now = datetime.now(timezone.utc).isoformat()
        with _lock:
            _state["rates"] = out
            _state["updated_at"] = now
            _state["fetch_error"] = None
            _state["using_fallback"] = False
        _save_disk(root)
        return True
    except (URLError, OSError, ValueError, TypeError, KeyError) as exc:
        with _lock:
            _state["fetch_error"] = str(exc)[:200]
        return False


def ensure_fresh_rates(root: Path) -> None:
    """Fetch if cache missing or older than REFRESH_INTERVAL_SEC."""
    _load_disk(root)
    with _lock:
        updated = _state.get("updated_at")
    need = False
    if not updated:
        need = True
    else:
        try:
            ts = datetime.fromisoformat(str(updated).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - ts).total_seconds()
            if age > REFRESH_INTERVAL_SEC:
                need = True
        except ValueError:
            need = True
    if need:
        ok = fetch_rates_live(root)
        if not ok:
            _load_disk(root)


def rates_public_dict(root: Path) -> dict[str, Any]:
    ensure_fresh_rates(root)
    with _lock:
        return {
            "base": "EUR",
            "rates": dict(_state["rates"]),
            "updated_at": _state["updated_at"],
            "using_fallback": bool(_state["using_fallback"]),
            "fetch_error": _state["fetch_error"],
            "supported": list(SUPPORTED),
        }


def normalize_currency(code: str | None) -> str:
    c = (code or "EUR").upper().strip()
    return c if c in SUPPORTED else "EUR"


def eur_per_usd(root: Path) -> float:
    """How many EUR one USD is worth (from EUR→USD Frankfurter rate)."""
    ensure_fresh_rates(root)
    with _lock:
        usd_rate = float(_state["rates"].get("USD") or 0)
    if usd_rate <= 0:
        return 1.0
    return 1.0 / usd_rate


def usd_to_eur(root: Path, amount_usd: float) -> float:
    return float(amount_usd) * eur_per_usd(root)


def convert_from_eur(amount_eur: float, currency: str, rates: dict[str, float] | None = None) -> float:
    c = normalize_currency(currency)
    if c == "EUR":
        return float(amount_eur)
    rmap = rates if rates is not None else dict(_state["rates"])
    rate = float(rmap.get(c) or 0)
    if rate <= 0:
        return float(amount_eur)
    return round(float(amount_eur) * rate, 2)


def format_money(amount_eur: float, currency: str, rates: dict[str, float] | None = None) -> str:
    c = normalize_currency(currency)
    symbols = {"EUR": "€", "USD": "$", "GBP": "£", "BRL": "R$"}
    sym = symbols.get(c, c + " ")
    converted = convert_from_eur(amount_eur, c, rates)
    return f"{sym}{converted:,.2f}"


def format_meta_line(currency: str, rates_updated_iso: str | None) -> str:
    when = rates_updated_iso or "—"
    return f"Display currency: {normalize_currency(currency)} (converted from EUR). FX rates as of: {when} UTC."


def maintenance_loop(root: Path) -> None:
    while True:
        time.sleep(300)
        try:
            ensure_fresh_rates(root)
        except Exception:
            pass
