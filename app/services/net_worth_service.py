"""
Net worth and account balances, stored per workspace in its finance SQLite file.

- Two built-in balances: the emergency fund and the amount invested. They are edited from the
  dashboard, analysis and net worth pages and feed the savings calculator, investment calculator,
  analysis hints and the AI context.
- Free-form net worth items: assets (cash, property, vehicles, ...) and liabilities (loans,
  credit cards, ...).
- One history row per day, rewritten on every change, so the net worth page can chart the trend.

All amounts are in the workspace base currency.
"""

from __future__ import annotations

from datetime import date, datetime

from app.services import instance_service

BALANCE_KEYS = ("emergency_fund", "invested")
ITEM_KINDS = ("asset", "liability")
ASSET_CATEGORIES = ("Cash", "Bank account", "Savings", "Investments", "Retirement", "Crypto", "Property", "Vehicle", "Other")
LIABILITY_CATEGORIES = ("Mortgage", "Car loan", "Student loan", "Personal loan", "Credit card", "Other")
MAX_AMOUNT = 1e12


def _ensure_net_worth_schema(conn) -> None:
    cur = conn.cursor()
    cur.execute(
        """CREATE TABLE IF NOT EXISTS account_balances (
            key TEXT PRIMARY KEY,
            amount REAL NOT NULL DEFAULT 0,
            updated_at TEXT
        )"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS net_worth_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL DEFAULT 'asset',
            name TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'Other',
            amount REAL NOT NULL DEFAULT 0,
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT,
            updated_at TEXT
        )"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS net_worth_history (
            day TEXT PRIMARY KEY,
            assets REAL NOT NULL DEFAULT 0,
            liabilities REAL NOT NULL DEFAULT 0,
            net_worth REAL NOT NULL DEFAULT 0
        )"""
    )
    conn.commit()


def ensure_schema(finance_db: str) -> None:
    conn = instance_service._conn(finance_db)
    try:
        _ensure_net_worth_schema(conn)
    finally:
        conn.close()


def _now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def parse_amount(value, *, allow_empty: bool = False) -> float | None:
    """Non-negative amount; accepts '1 234,56' and '1,234.56'. Raises ValueError when invalid."""
    if value is None or (isinstance(value, str) and not value.strip()):
        if allow_empty:
            return None
        raise ValueError("Amount is required.")
    if isinstance(value, (int, float)):
        v = float(value)
    else:
        s = str(value).strip().replace(" ", "").replace(" ", "")
        if "," in s and "." in s:
            s = s.replace(",", "") if s.rfind(".") > s.rfind(",") else s.replace(".", "").replace(",", ".")
        elif "," in s:
            s = s.replace(",", ".")
        try:
            v = float(s)
        except ValueError as exc:
            raise ValueError("Amount must be a number.") from exc
    if v != v or v < 0:
        raise ValueError("Amount must be zero or positive.")
    if v > MAX_AMOUNT:
        raise ValueError("Amount is too large.")
    return round(v, 2)


# ---------------------------------------------------------------------------
# Balances
# ---------------------------------------------------------------------------


def get_balances(finance_db: str) -> dict:
    conn = instance_service._conn(finance_db)
    try:
        _ensure_net_worth_schema(conn)
        rows = conn.execute("SELECT key, amount, updated_at FROM account_balances").fetchall()
    finally:
        conn.close()
    out: dict = {k: 0.0 for k in BALANCE_KEYS}
    updated = None
    for key, amount, upd in rows:
        if key in BALANCE_KEYS:
            out[key] = round(float(amount or 0), 2)
            if upd and (updated is None or upd > updated):
                updated = upd
    out["updated_at"] = updated
    out["is_set"] = bool(rows)
    return out


def set_balances(finance_db: str, **values: float | None) -> dict:
    """Update any of BALANCE_KEYS (None = leave unchanged) and record today's history row."""
    conn = instance_service._conn(finance_db)
    try:
        _ensure_net_worth_schema(conn)
        now = _now()
        for key, amount in values.items():
            if key not in BALANCE_KEYS or amount is None:
                continue
            conn.execute(
                "INSERT INTO account_balances (key, amount, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET amount = excluded.amount, updated_at = excluded.updated_at",
                (key, float(amount), now),
            )
        conn.commit()
        _record_history(conn)
    finally:
        conn.close()
    return get_balances(finance_db)


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------


def _clean_item(kind: str, name: str, category: str | None, amount, note: str | None) -> tuple:
    k = (kind or "").strip().lower()
    if k not in ITEM_KINDS:
        raise ValueError("Type must be asset or liability.")
    n = (name or "").strip()[:120]
    if not n:
        raise ValueError("Name is required.")
    allowed = ASSET_CATEGORIES if k == "asset" else LIABILITY_CATEGORIES
    c = (category or "").strip()
    if c not in allowed:
        c = "Other"
    return k, n, c, parse_amount(amount), (note or "").strip()[:300]


def list_items(finance_db: str) -> list[dict]:
    conn = instance_service._conn(finance_db)
    try:
        _ensure_net_worth_schema(conn)
        rows = conn.execute(
            "SELECT id, kind, name, category, amount, note, updated_at FROM net_worth_items "
            "ORDER BY kind, amount DESC, id"
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "id": r[0],
            "kind": r[1],
            "name": r[2],
            "category": r[3],
            "amount": round(float(r[4] or 0), 2),
            "note": r[5] or "",
            "updated_at": r[6],
        }
        for r in rows
    ]


def add_item(finance_db: str, kind: str, name: str, amount, category: str | None = None, note: str | None = None) -> int:
    k, n, c, a, nt = _clean_item(kind, name, category, amount, note)
    conn = instance_service._conn(finance_db)
    try:
        _ensure_net_worth_schema(conn)
        now = _now()
        cur = conn.execute(
            "INSERT INTO net_worth_items (kind, name, category, amount, note, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (k, n, c, a, nt, now, now),
        )
        conn.commit()
        _record_history(conn)
        return int(cur.lastrowid)
    finally:
        conn.close()


def update_item(finance_db: str, item_id: int, kind: str, name: str, amount, category: str | None = None, note: str | None = None) -> None:
    k, n, c, a, nt = _clean_item(kind, name, category, amount, note)
    conn = instance_service._conn(finance_db)
    try:
        _ensure_net_worth_schema(conn)
        cur = conn.execute(
            "UPDATE net_worth_items SET kind = ?, name = ?, category = ?, amount = ?, note = ?, updated_at = ? WHERE id = ?",
            (k, n, c, a, nt, _now(), int(item_id)),
        )
        if cur.rowcount == 0:
            raise LookupError("Item not found.")
        conn.commit()
        _record_history(conn)
    finally:
        conn.close()


def delete_item(finance_db: str, item_id: int) -> None:
    conn = instance_service._conn(finance_db)
    try:
        _ensure_net_worth_schema(conn)
        cur = conn.execute("DELETE FROM net_worth_items WHERE id = ?", (int(item_id),))
        if cur.rowcount == 0:
            raise LookupError("Item not found.")
        conn.commit()
        _record_history(conn)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Totals and history
# ---------------------------------------------------------------------------


def _totals_from_conn(conn) -> tuple[float, float]:
    bal = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM account_balances WHERE key IN (%s)" % ",".join("?" for _ in BALANCE_KEYS),
        BALANCE_KEYS,
    ).fetchone()[0]
    assets = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM net_worth_items WHERE kind = 'asset'").fetchone()[0]
    liabilities = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM net_worth_items WHERE kind = 'liability'").fetchone()[0]
    return round(float(bal or 0) + float(assets or 0), 2), round(float(liabilities or 0), 2)


def _record_history(conn, day: date | None = None) -> None:
    assets, liabilities = _totals_from_conn(conn)
    conn.execute(
        "INSERT INTO net_worth_history (day, assets, liabilities, net_worth) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(day) DO UPDATE SET assets = excluded.assets, liabilities = excluded.liabilities, "
        "net_worth = excluded.net_worth",
        ((day or date.today()).isoformat(), assets, liabilities, round(assets - liabilities, 2)),
    )
    conn.commit()


def history(finance_db: str, limit: int = 730) -> list[dict]:
    conn = instance_service._conn(finance_db)
    try:
        _ensure_net_worth_schema(conn)
        rows = conn.execute(
            "SELECT day, assets, liabilities, net_worth FROM net_worth_history ORDER BY day DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    finally:
        conn.close()
    return [
        {"day": r[0], "assets": round(float(r[1]), 2), "liabilities": round(float(r[2]), 2), "net_worth": round(float(r[3]), 2)}
        for r in reversed(rows)
    ]


def essential_monthly_expenses(finance_db: str) -> float:
    """Monthly-equivalent recurring expenses currently active (the emergency fund benchmark)."""
    from app.services.savings_expenses_service import recurrence_to_monthly

    items = instance_service.list_finance_items(finance_db)
    month = date.today().strftime("%Y-%m")
    return round(
        sum(
            recurrence_to_monthly(e["amount"], e.get("recurrence"))
            for e in items["expenses"]
            if instance_service.recurring_active_in_month(e, month)
        ),
        2,
    )


def emergency_fund_status(emergency_fund: float, monthly_expenses: float, target_months: int = 6) -> dict:
    target = round(monthly_expenses * target_months, 2)
    months_covered = round(emergency_fund / monthly_expenses, 1) if monthly_expenses > 0 else None
    if target > 0:
        progress = min(100.0, round(emergency_fund / target * 100.0, 1))
    else:
        progress = 100.0 if emergency_fund > 0 else 0.0
    if months_covered is None:
        level = "unknown"
    elif months_covered >= target_months:
        level = "healthy"
    elif months_covered >= 3:
        level = "building"
    else:
        level = "low"
    return {
        "target_months": target_months,
        "target": target,
        "monthly_expenses": round(monthly_expenses, 2),
        "months_covered": months_covered,
        "progress_pct": progress,
        "still_needed": max(0.0, round(target - emergency_fund, 2)),
        "level": level,
    }


def summary(finance_db: str, *, with_history: bool = False) -> dict:
    """Everything the UI needs: balances, items, totals, emergency fund status (and optional history)."""
    balances = get_balances(finance_db)
    items = list_items(finance_db)
    other_assets = round(sum(i["amount"] for i in items if i["kind"] == "asset"), 2)
    liabilities = round(sum(i["amount"] for i in items if i["kind"] == "liability"), 2)
    total_assets = round(balances["emergency_fund"] + balances["invested"] + other_assets, 2)
    monthly_exp = essential_monthly_expenses(finance_db)
    out = {
        "balances": balances,
        "items": items,
        "totals": {
            "emergency_fund": balances["emergency_fund"],
            "invested": balances["invested"],
            "other_assets": other_assets,
            "assets": total_assets,
            "liabilities": liabilities,
            "net_worth": round(total_assets - liabilities, 2),
            "debt_to_asset_pct": round(liabilities / total_assets * 100.0, 1) if total_assets > 0 else None,
        },
        "emergency": emergency_fund_status(balances["emergency_fund"], monthly_exp),
        "categories": {"asset": list(ASSET_CATEGORIES), "liability": list(LIABILITY_CATEGORIES)},
    }
    if with_history:
        out["history"] = history(finance_db)
    return out
