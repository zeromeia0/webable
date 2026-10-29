"""
User-defined taxes, stored per workspace in its finance SQLite file.

A tax is a percentage and/or a fixed monthly amount. Taxes are assigned to individual incomes
(recurring incomes and one-time income transactions) when the income is created or edited, and can
optionally also apply to investment gains in the investment tools.

Income amounts entered in the app are gross (pre-tax). ``apply_to_month`` turns a month summary into
pre-tax / tax / after-tax figures; the database calculation, dashboard and analysis then use the
after-tax savings.
"""

from __future__ import annotations

from datetime import datetime

from app.services import instance_service

INCOME_KINDS = ("recurring", "oneoff")
# Legacy rules (before per-income assignment) chose a base; kept only for the one-off migration.
_LEGACY_BASES = {"salary": ("recurring",), "oneoff_income": ("oneoff",), "all_income": ("recurring", "oneoff")}


def _ensure_tax_schema(conn) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS tax_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            applies_to TEXT NOT NULL DEFAULT 'income',
            rate_pct REAL NOT NULL DEFAULT 0,
            fixed_monthly REAL NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1,
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT,
            updated_at TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS income_taxes (
            income_kind TEXT NOT NULL,
            income_id INTEGER NOT NULL,
            tax_id INTEGER NOT NULL,
            PRIMARY KEY (income_kind, income_id, tax_id)
        )"""
    )
    cols = {r[1] for r in conn.execute("PRAGMA table_info(tax_rules)").fetchall()}
    if "on_investments" not in cols:
        conn.execute("ALTER TABLE tax_rules ADD COLUMN on_investments INTEGER NOT NULL DEFAULT 0")
        _migrate_legacy_rules(conn)
    conn.commit()


def _migrate_legacy_rules(conn) -> None:
    """Category-based rules -> per-income links, so existing totals don't change after the upgrade."""
    instance_service._ensure_all(conn)
    recurring = [r[0] for r in conn.execute("SELECT id FROM rendimentos WHERE ativo = 1").fetchall()]
    oneoff = [r[0] for r in conn.execute("SELECT id FROM transacoes_unicas WHERE txn_type = 'income'").fetchall()]
    ids = {"recurring": recurring, "oneoff": oneoff}
    for rule_id, applies_to in conn.execute("SELECT id, applies_to FROM tax_rules").fetchall():
        if applies_to == "investments":
            conn.execute("UPDATE tax_rules SET on_investments = 1, applies_to = 'income' WHERE id = ?", (rule_id,))
            continue
        for kind in _LEGACY_BASES.get(applies_to, ()):
            conn.executemany(
                "INSERT OR IGNORE INTO income_taxes (income_kind, income_id, tax_id) VALUES (?, ?, ?)",
                [(kind, iid, rule_id) for iid in ids[kind]],
            )
        conn.execute("UPDATE tax_rules SET applies_to = 'income' WHERE id = ?", (rule_id,))


def _conn(finance_db: str):
    conn = instance_service._conn(finance_db)
    _ensure_tax_schema(conn)
    return conn


def _num(v, label: str) -> float:
    try:
        return float(str(v if v not in (None, "") else 0).replace(",", ".").strip())
    except ValueError as exc:
        raise ValueError(f"{label} must be a number.") from exc


def _clean(name: str, rate_pct, fixed_monthly, on_investments, note: str | None) -> tuple:
    n = (name or "").strip()[:120]
    if not n:
        raise ValueError("Tax name is required.")
    r = _num(rate_pct, "Rate")
    f = _num(fixed_monthly, "Fixed amount")
    if not (0 <= r <= 100):
        raise ValueError("Rate must be between 0 and 100%.")
    if f < 0 or f > 1e9:
        raise ValueError("Fixed amount must be zero or positive.")
    if r == 0 and f == 0:
        raise ValueError("Enter a rate, a fixed monthly amount, or both.")
    inv = bool(on_investments) and str(on_investments).lower() not in ("0", "false", "off", "")
    if inv and r == 0:
        raise ValueError("Investment gains can only be taxed by a percentage.")
    return n, round(r, 4), round(f, 2), inv, (note or "").strip()[:300]


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def list_rules(finance_db: str, *, active_only: bool = False) -> list[dict]:
    """Rules with the incomes each one is assigned to."""
    conn = _conn(finance_db)
    try:
        sql = "SELECT id, name, rate_pct, fixed_monthly, active, note, on_investments FROM tax_rules"
        if active_only:
            sql += " WHERE active = 1"
        rows = conn.execute(sql + " ORDER BY id").fetchall()
        links = conn.execute(
            "SELECT t.tax_id, t.income_kind, t.income_id, COALESCE(r.nome, u.nome) "
            "FROM income_taxes t "
            "LEFT JOIN rendimentos r ON t.income_kind = 'recurring' AND r.id = t.income_id AND r.ativo = 1 "
            "LEFT JOIN transacoes_unicas u ON t.income_kind = 'oneoff' AND u.id = t.income_id AND u.txn_type = 'income'"
        ).fetchall()
    finally:
        conn.close()
    by_rule: dict[int, list[dict]] = {}
    for tax_id, kind, iid, name in links:
        if name is None:
            continue
        by_rule.setdefault(tax_id, []).append({"kind": kind, "id": iid, "name": name})
    return [
        {
            "id": r[0],
            "name": r[1],
            "rate_pct": float(r[2] or 0),
            "fixed_monthly": float(r[3] or 0),
            "active": bool(r[4]),
            "note": r[5] or "",
            "on_investments": bool(r[6]),
            "incomes": by_rule.get(r[0], []),
        }
        for r in rows
    ]


def add_rule(finance_db: str, name: str, rate_pct=0, fixed_monthly=0, on_investments=False, note: str | None = None) -> int:
    n, r, f, inv, nt = _clean(name, rate_pct, fixed_monthly, on_investments, note)
    now = datetime.utcnow().isoformat(timespec="seconds")
    conn = _conn(finance_db)
    try:
        cur = conn.execute(
            "INSERT INTO tax_rules (name, applies_to, rate_pct, fixed_monthly, on_investments, active, note, created_at, updated_at) "
            "VALUES (?, 'income', ?, ?, ?, 1, ?, ?, ?)",
            (n, r, f, 1 if inv else 0, nt, now, now),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def update_rule(
    finance_db: str, rule_id: int, name: str, rate_pct=0, fixed_monthly=0, on_investments=False, note: str | None = None, active: bool = True
) -> None:
    n, r, f, inv, nt = _clean(name, rate_pct, fixed_monthly, on_investments, note)
    conn = _conn(finance_db)
    try:
        cur = conn.execute(
            "UPDATE tax_rules SET name = ?, rate_pct = ?, fixed_monthly = ?, on_investments = ?, note = ?, active = ?, updated_at = ? "
            "WHERE id = ?",
            (n, r, f, 1 if inv else 0, nt, 1 if active else 0, datetime.utcnow().isoformat(timespec="seconds"), int(rule_id)),
        )
        if cur.rowcount == 0:
            raise LookupError("Tax not found.")
        conn.commit()
    finally:
        conn.close()


def set_active(finance_db: str, rule_id: int, active: bool) -> None:
    conn = _conn(finance_db)
    try:
        cur = conn.execute("UPDATE tax_rules SET active = ? WHERE id = ?", (1 if active else 0, int(rule_id)))
        if cur.rowcount == 0:
            raise LookupError("Tax not found.")
        conn.commit()
    finally:
        conn.close()


def delete_rule(finance_db: str, rule_id: int) -> None:
    conn = _conn(finance_db)
    try:
        cur = conn.execute("DELETE FROM tax_rules WHERE id = ?", (int(rule_id),))
        if cur.rowcount == 0:
            raise LookupError("Tax not found.")
        conn.execute("DELETE FROM income_taxes WHERE tax_id = ?", (int(rule_id),))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Income assignments
# ---------------------------------------------------------------------------


def parse_tax_ids(values) -> list[int]:
    out = []
    for v in values or []:
        try:
            out.append(int(v))
        except (TypeError, ValueError):
            continue
    return sorted(set(out))


def set_income_taxes(finance_db: str, kind: str, income_id: int, tax_ids) -> list[int]:
    """Replace the taxes assigned to one income. Unknown tax ids are ignored."""
    if kind not in INCOME_KINDS:
        raise ValueError("Unknown income kind.")
    ids = parse_tax_ids(tax_ids)
    conn = _conn(finance_db)
    try:
        valid = {r[0] for r in conn.execute("SELECT id FROM tax_rules").fetchall()}
        ids = [i for i in ids if i in valid]
        conn.execute("DELETE FROM income_taxes WHERE income_kind = ? AND income_id = ?", (kind, int(income_id)))
        conn.executemany(
            "INSERT INTO income_taxes (income_kind, income_id, tax_id) VALUES (?, ?, ?)",
            [(kind, int(income_id), i) for i in ids],
        )
        conn.commit()
    finally:
        conn.close()
    return ids


def clear_income_taxes(finance_db: str, kind: str, income_id: int) -> None:
    set_income_taxes(finance_db, kind, income_id, [])


def assignments(finance_db: str) -> dict[str, list[int]]:
    """{"recurring:12": [1, 3], "oneoff:7": [2]} for templates and the edit dialog."""
    conn = _conn(finance_db)
    try:
        rows = conn.execute("SELECT income_kind, income_id, tax_id FROM income_taxes ORDER BY tax_id").fetchall()
    finally:
        conn.close()
    out: dict[str, list[int]] = {}
    for kind, iid, tid in rows:
        out.setdefault(f"{kind}:{iid}", []).append(tid)
    return out


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------


def tax_on_amount(amount: float, rules: list[dict]) -> tuple[float, list[tuple[dict, float]]]:
    """Tax on one gross income amount: Σ(rate% × amount + fixed), never more than the amount."""
    amount = max(0.0, float(amount))
    parts = []
    total = 0.0
    for rule in rules:
        amt = amount * rule["rate_pct"] / 100.0 + rule["fixed_monthly"]
        amt = min(amt, max(0.0, amount - total))
        total += amt
        parts.append((rule, round(amt, 2)))
    return round(total, 2), parts


def compute_month_taxes(rules: list[dict], links: dict[str, list[int]], incomes: list[tuple[str, int, str, float]]) -> dict:
    """
    ``incomes`` = (kind, id, name, gross amount) of every income counted this month.
    Returns per-tax lines plus gross / tax / net totals.
    """
    by_id = {r["id"]: r for r in rules if r.get("active", True)}
    lines: dict[int, dict] = {}
    gross = 0.0
    total = 0.0
    for kind, iid, name, amount in incomes:
        gross += max(0.0, amount)
        applied = [by_id[t] for t in links.get(f"{kind}:{iid}", []) if t in by_id]
        if not applied:
            continue
        tax, parts = tax_on_amount(amount, applied)
        total += tax
        for rule, amt in parts:
            line = lines.setdefault(
                rule["id"],
                {"name": rule["name"], "rate_pct": rule["rate_pct"], "fixed_monthly": rule["fixed_monthly"], "base": 0.0, "amount": 0.0, "incomes": []},
            )
            line["base"] = round(line["base"] + amount, 2)
            line["amount"] = round(line["amount"] + amt, 2)
            line["incomes"].append(name)
    total = round(total, 2)
    return {
        "lines": list(lines.values()),
        "gross_income": round(gross, 2),
        "total_tax": total,
        "net_income": round(gross - total, 2),
        "effective_rate_pct": round(total / gross * 100.0, 2) if gross > 0 else 0.0,
    }


def apply_to_month(finance_db: str, summary: dict, rules: list[dict] | None = None) -> dict:
    """Add pre-tax / tax / after-tax fields to an instance_service.month_summary result (in place)."""
    if rules is None:
        rules = list_rules(finance_db, active_only=True)
    links = assignments(finance_db) if rules else {}
    month = str(summary.get("month", ""))
    incomes: list[tuple[str, int, str, float]] = [
        ("recurring", i["id"], i["name"], float(i["amount"]))
        for i in summary.get("income_items") or []
        if instance_service.recurring_active_in_month(i, month)
    ]
    incomes += [
        ("oneoff", o["id"], o.get("name", ""), abs(float(o.get("amount") or 0)))
        for o in summary.get("oneoff_transactions") or []
        if str(o.get("txn_type", "expense")).lower() == "income" and o.get("id") is not None
    ]
    tx = compute_month_taxes(rules, links, incomes)
    pre_tax_savings = float(summary.get("estimated_savings", 0) or 0)
    summary["taxes"] = tx
    summary["taxes_total"] = tx["total_tax"]
    summary["income_pre_tax"] = round(float(summary.get("total_before_expenses", 0) or 0), 2)
    summary["income_after_tax"] = round(summary["income_pre_tax"] - tx["total_tax"], 2)
    summary["estimated_savings_pre_tax"] = round(pre_tax_savings, 2)
    summary["estimated_savings"] = round(pre_tax_savings - tx["total_tax"], 2)
    if "available_balance" in summary:
        summary["available_balance"] = round(float(summary["available_balance"]) - tx["total_tax"], 2)
    return summary


def investment_tax_rate(finance_db: str) -> float:
    """Combined % taken from investment gains (capped at 100)."""
    rules = list_rules(finance_db, active_only=True)
    return round(min(100.0, sum(r["rate_pct"] for r in rules if r["on_investments"])), 4)


def apply_investment_tax(profit: float, rate_pct: float) -> dict:
    tax = round(max(0.0, profit) * rate_pct / 100.0, 2)
    return {"rate_pct": rate_pct, "gains_pre_tax": round(profit, 2), "tax": tax, "gains_after_tax": round(profit - tax, 2)}
