"""Historical market series for charts (cached per symbol + range)."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import currency_service

log = logging.getLogger("webable.market")

USER_AGENT = "WebableFinanceBot/1.0 (+https://localhost)"

VALID_SYMBOLS = frozenset({"SP500", "BTC", "ETH"})
VALID_RANGES = frozenset({"24h", "7d", "1m", "6m", "1y", "max"})

_COINGECKO_ID = {"BTC": "bitcoin", "ETH": "ethereum"}

# CoinGecko `days` param (int or "max")
_RANGE_CG_DAYS: dict[str, int | str] = {
    "24h": 1,
    "7d": 7,
    "1m": 30,
    "6m": 180,
    "1y": 365,
    "max": "max",
}

# Yahoo chart: range, interval
_RANGE_YAHOO: dict[str, tuple[str, str]] = {
    "24h": ("1d", "5m"),
    "7d": ("5d", "15m"),
    "1m": ("1mo", "1d"),
    "6m": ("6mo", "1d"),
    "1y": ("1y", "1d"),
    "max": ("max", "1wk"),
}


def _ttl_seconds(range_key: str) -> int:
    return {
        "24h": 900,
        "7d": 1800,
        "1m": 3600,
        "6m": 21600,
        "1y": 21600,
        "max": 86400,
    }.get(range_key, 3600)


def _http_json(url: str, timeout: float = 25.0) -> dict[str, Any] | None:
    for attempt in range(3):
        try:
            req = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (URLError, HTTPError, OSError, ValueError, TypeError) as exc:
            log.warning("chart fetch attempt %s failed: %s", attempt + 1, exc)
            time.sleep(0.5 * (attempt + 1))
    return None


def _parse_coingecko_prices(payload: dict[str, Any] | None) -> list[dict[str, Any]] | None:
    if not payload or "prices" not in payload:
        return None
    prices = payload["prices"]
    if not isinstance(prices, list):
        return None
    out: list[dict[str, Any]] = []
    for row in prices:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        ms, val = row[0], row[1]
        try:
            dt = datetime.fromtimestamp(int(ms) / 1000.0, tz=timezone.utc)
            out.append({"t": dt.isoformat(), "v": float(val)})
        except (TypeError, ValueError, OSError):
            continue
    return out or None


def _parse_yahoo_closes_usd(payload: dict[str, Any] | None) -> list[dict[str, Any]] | None:
    if not payload:
        return None
    try:
        res = payload["chart"]["result"][0]
        ts = res.get("timestamp") or []
        quotes = (res.get("indicators") or {}).get("quote") or [{}]
        closes = quotes[0].get("close") or []
    except (KeyError, IndexError, TypeError):
        return None
    out: list[dict[str, Any]] = []
    for i, t in enumerate(ts):
        if i >= len(closes):
            break
        c = closes[i]
        if c is None:
            continue
        try:
            dt = datetime.fromtimestamp(int(t), tz=timezone.utc)
            out.append({"t": dt.isoformat(), "v": float(c)})
        except (TypeError, ValueError, OSError):
            continue
    return out or None


def fetch_live_series(root, symbol: str, range_key: str) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Return (points with v in EUR, error_message)."""
    if symbol not in VALID_SYMBOLS or range_key not in VALID_RANGES:
        return None, "Invalid symbol or range"

    if symbol in ("BTC", "ETH"):
        cg_id = _COINGECKO_ID[symbol]
        days = _RANGE_CG_DAYS[range_key]
        url = f"https://api.coingecko.com/api/v3/coins/{cg_id}/market_chart?vs_currency=eur&days={days}"
        raw = _http_json(url)
        pts = _parse_coingecko_prices(raw)
        if not pts:
            return None, "CoinGecko chart unavailable"
        return pts, None

    # SP500 proxy via SPY (USD) → EUR
    y_range, y_interval = _RANGE_YAHOO[range_key]
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/SPY?range={y_range}&interval={y_interval}"
    raw = _http_json(url)
    usd_pts = _parse_yahoo_closes_usd(raw)
    if not usd_pts:
        return None, "Yahoo chart unavailable"
    rate = currency_service.eur_per_usd(root)
    pts = [{"t": p["t"], "v": round(float(p["v"]) * rate, 6)} for p in usd_pts]
    return pts, None


def _load_cached_points(row) -> list[dict[str, Any]]:
    try:
        data = json.loads(row.points_json or "[]")
        return data if isinstance(data, list) else []
    except (TypeError, ValueError):
        return []


def get_series(db: Session, root, symbol: str, range_key: str, *, force_refresh: bool = False) -> dict[str, Any]:
    """Return chart payload for one symbol; uses DB cache with TTL."""
    from ..models import MarketChartCache

    symbol = str(symbol).upper().strip()
    range_key = str(range_key).lower().strip()
    if symbol not in VALID_SYMBOLS or range_key not in VALID_RANGES:
        return {"symbol": symbol, "range": range_key, "points": [], "error": "Invalid symbol or range", "cached_at": None}

    row = (
        db.query(MarketChartCache)
        .filter(MarketChartCache.symbol == symbol, MarketChartCache.range_key == range_key)
        .first()
    )
    existing_pts = _load_cached_points(row) if row else []
    ttl = _ttl_seconds(range_key)
    now = datetime.utcnow()
    if row and row.fetched_at and not force_refresh:
        age = (now - row.fetched_at).total_seconds()
        pts = _load_cached_points(row)
        if pts and age < ttl:
            return {
                "symbol": symbol,
                "range": range_key,
                "points": pts,
                "cached_at": row.fetched_at.isoformat() + "Z",
                "error": row.fetch_error,
                "from_cache": True,
            }

    pts, err = fetch_live_series(root, symbol, range_key)
    if not row:
        row = MarketChartCache(symbol=symbol, range_key=range_key)
        db.add(row)

    if pts:
        row.points_json = json.dumps(pts)
        row.fetch_error = None
        row.fetched_at = now
    else:
        row.fetch_error = (err or "fetch failed")[:500]
        row.fetched_at = now
        if existing_pts:
            log.warning("chart keeping stale cache for %s %s: %s", symbol, range_key, row.fetch_error)
        else:
            row.points_json = "[]"

    db.commit()

    out_pts = pts or _load_cached_points(row)
    return {
        "symbol": symbol,
        "range": range_key,
        "points": out_pts,
        "cached_at": row.fetched_at.isoformat() + "Z" if row.fetched_at else None,
        "error": None if pts else row.fetch_error,
        "from_cache": not bool(pts) and bool(out_pts),
    }


def get_bundle(db: Session, root, range_key: str) -> dict[str, Any]:
    range_key = str(range_key).lower().strip()
    if range_key not in VALID_RANGES:
        range_key = "1m"
    series: dict[str, Any] = {}
    for sym in ("SP500", "BTC", "ETH"):
        series[sym] = get_series(db, root, sym, range_key)
    return {"range": range_key, "series": series}
