"""Cached market quotes (S&P 500 proxy via SPY, BTC, ETH). Refreshed at most every 12 hours."""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen

from sqlalchemy.orm import Session

from . import currency_service

log = logging.getLogger("webable.market")

REFRESH_INTERVAL_SEC = 12 * 3600
SYMBOLS = ("SP500", "BTC", "ETH")
USER_AGENT = "WebableFinanceBot/1.0 (+https://localhost)"

_coingecko_url = (
    "https://api.coingecko.com/api/v3/simple/price"
    "?ids=bitcoin,ethereum&vs_currencies=eur,usd&include_24hr_change=true"
)
_yahoo_spy_url = "https://query1.finance.yahoo.com/v8/finance/chart/SPY?range=5d&interval=1d"


def _http_json(url: str, timeout: float = 20.0) -> dict[str, Any] | None:
    for attempt in range(3):
        try:
            req = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (URLError, HTTPError, OSError, ValueError, TypeError) as exc:
            log.warning("market fetch attempt %s failed: %s", attempt + 1, exc)
            time.sleep(0.6 * (attempt + 1))
    return None


def _parse_coingecko(payload: dict[str, Any] | None) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not payload:
        return None, None
    btc = payload.get("bitcoin") or {}
    eth = payload.get("ethereum") or {}
    if not btc.get("eur") or not eth.get("eur"):
        return None, None
    out_btc = {
        "price_eur": float(btc["eur"]),
        "change_pct": float(btc.get("eur_24h_change") or 0),
        "price_usd": float(btc.get("usd") or 0),
    }
    out_eth = {
        "price_eur": float(eth["eur"]),
        "change_pct": float(eth.get("eur_24h_change") or 0),
        "price_usd": float(eth.get("usd") or 0),
    }
    return out_btc, out_eth


def _parse_yahoo_spy(payload: dict[str, Any] | None, root) -> dict[str, Any] | None:
    if not payload:
        return None
    try:
        res = payload["chart"]["result"][0]
        meta = res.get("meta") or {}
        price_usd = float(meta.get("regularMarketPrice") or 0)
        prev = float(meta.get("chartPreviousClose") or meta.get("previousClose") or 0)
        if price_usd <= 0:
            return None
        change_pct = ((price_usd - prev) / prev * 100.0) if prev > 0 else 0.0
        eur = currency_service.usd_to_eur(root, price_usd)
        return {"price_eur": float(eur), "change_pct": float(change_pct), "price_usd": price_usd}
    except (KeyError, IndexError, TypeError, ValueError, ZeroDivisionError) as exc:
        log.warning("yahoo SPY parse failed: %s", exc)
        return None


def fetch_live(root) -> dict[str, Any]:
    """Returns dict symbol -> {price_eur, change_pct, price_usd?} and errors per symbol."""
    out: dict[str, Any] = {}
    errs: dict[str, str] = {}

    cg = _http_json(_coingecko_url)
    btc, eth = _parse_coingecko(cg)
    if btc:
        out["BTC"] = btc
    else:
        errs["BTC"] = "CoinGecko unavailable or parse error"
    if eth:
        out["ETH"] = eth
    else:
        errs["ETH"] = "CoinGecko unavailable or parse error"

    y = _http_json(_yahoo_spy_url)
    spy = _parse_yahoo_spy(y, root)
    if spy:
        # SPY ETF tracks S&P 500 closely — label as proxy in API/UI
        out["SP500"] = spy
    else:
        errs["SP500"] = "Market data provider unavailable"

    return {"quotes": out, "errors": errs, "fetched_at": datetime.now(timezone.utc).isoformat()}


def persist_snapshot(db: Session, root, payload: dict[str, Any]) -> None:
    from ..models import MarketQuote

    quotes = payload.get("quotes") or {}
    errs = payload.get("errors") or {}
    fetched = payload.get("fetched_at")
    for sym in SYMBOLS:
        row = db.query(MarketQuote).filter(MarketQuote.symbol == sym).first()
        if not row:
            row = MarketQuote(symbol=sym, label=_default_label(sym))
            db.add(row)
        data = quotes.get(sym)
        if data:
            row.price_eur = float(data["price_eur"])
            row.change_pct = float(data.get("change_pct") or 0)
            row.price_usd = float(data["price_usd"]) if data.get("price_usd") else None
            row.meta_json = json.dumps(data)
            row.fetched_at = datetime.utcnow()
            row.fetch_error = None
        else:
            row.fetch_error = (errs.get(sym) or "Unknown error")[:500]
    db.commit()


def _default_label(sym: str) -> str:
    return {"SP500": "S&P 500 (SPY proxy)", "BTC": "Bitcoin", "ETH": "Ethereum"}.get(sym, sym)


def public_dict(db: Session) -> dict[str, Any]:
    from ..models import MarketQuote

    rows = db.query(MarketQuote).filter(MarketQuote.symbol.in_(SYMBOLS)).all()
    by = {r.symbol: r for r in rows}
    items = []
    stale = False
    for sym in SYMBOLS:
        r = by.get(sym)
        if not r:
            items.append(
                {
                    "symbol": sym,
                    "label": _default_label(sym),
                    "price_eur": None,
                    "change_pct": None,
                    "fetched_at": None,
                    "fetch_error": "No data yet",
                }
            )
            stale = True
            continue
        items.append(
            {
                "symbol": sym,
                "label": r.label,
                "price_eur": float(r.price_eur) if r.price_eur is not None else None,
                "change_pct": float(r.change_pct) if r.change_pct is not None else None,
                "price_usd": float(r.price_usd) if r.price_usd is not None else None,
                "fetched_at": r.fetched_at.isoformat() + "Z" if r.fetched_at else None,
                "fetch_error": r.fetch_error,
            }
        )
        if r.fetch_error:
            stale = True
    return {"items": items, "stale": stale}


def needs_refresh(db: Session) -> bool:
    from ..models import MarketQuote

    row = db.query(MarketQuote).filter(MarketQuote.symbol == "BTC").first()
    if not row or not row.fetched_at:
        return True
    age = (datetime.utcnow() - row.fetched_at).total_seconds()
    return age > REFRESH_INTERVAL_SEC


def refresh_if_stale(db: Session, root) -> None:
    if not needs_refresh(db):
        return
    try:
        payload = fetch_live(root)
        persist_snapshot(db, root, payload)
    except Exception as exc:  # noqa: BLE001
        log.exception("market refresh failed: %s", exc)


def maintenance_loop(root, session_factory):
    while True:
        time.sleep(600)
        db = session_factory()
        try:
            refresh_if_stale(db, root)
        except Exception:
            log.exception("market maintenance tick failed")
        finally:
            db.close()
