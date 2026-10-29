import math
import sqlite3
from pathlib import Path
from datetime import datetime
from dateutil.relativedelta import relativedelta

ONEOFF_CATEGORIES = (
    "Housing",
    "Food",
    "Transport",
    "Subscriptions",
    "Shopping",
    "Health",
    "Entertainment",
    "Education",
    "Savings",
    "Investments",
    "Other",
)

VALOR_HORA_BOLSA = 2.06
LIMITE_MENSAL_BOLSA = 268.57
VALOR_ALIMENTACAO_DIA = 6.15
MIN_HORAS_ALIMENTACAO = 3

HORAS_MES = {
    "2026-04": 36, "2026-05": 119, "2026-06": 118,
    "2026-07": 138, "2026-08": 60, "2026-09": 132,
    "2026-10": 126, "2026-11": 117, "2026-12": 36,
    "2027-01": 120, "2027-02": 97, "2027-03": 138,
    "2027-04": 132, "2027-05": 120, "2027-06": 54,
}


def _conn(path: str):
    return sqlite3.connect(path)


def _ensure_oneoff_schema(conn):
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(transacoes_unicas)")
    cols = {row[1] for row in cur.fetchall()}
    if "category" not in cols:
        cur.execute("ALTER TABLE transacoes_unicas ADD COLUMN category TEXT NOT NULL DEFAULT 'Other'")
    if "txn_type" not in cols:
        cur.execute("ALTER TABLE transacoes_unicas ADD COLUMN txn_type TEXT NOT NULL DEFAULT 'expense'")
    conn.commit()


def _ensure_recurring_recurrence(conn):
    cur = conn.cursor()
    for table in ("rendimentos", "gastos"):
        cur.execute(f"PRAGMA table_info({table})")
        cols = {row[1] for row in cur.fetchall()}
        if "recurrence" not in cols:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN recurrence TEXT NOT NULL DEFAULT 'monthly'")
        if "ended" not in cols:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN ended INTEGER NOT NULL DEFAULT 0")
        if "next_due" not in cols:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN next_due TEXT")
    cur.execute("PRAGMA table_info(gastos)")
    gcols = {row[1] for row in cur.fetchall()}
    if "category" not in gcols:
        cur.execute("ALTER TABLE gastos ADD COLUMN category TEXT NOT NULL DEFAULT 'Other'")
    conn.commit()


def _ensure_savings_schema(conn):
    cur = conn.cursor()
    cur.execute(
        """CREATE TABLE IF NOT EXISTS savings_deposits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data TEXT NOT NULL,
            nome TEXT NOT NULL DEFAULT '',
            valor REAL NOT NULL,
            deleted_at TEXT,
            deleted_by INTEGER
        )"""
    )
    cur.execute("PRAGMA table_info(savings_deposits)")
    cols = {row[1] for row in cur.fetchall()}
    if "deleted_at" not in cols:
        cur.execute("ALTER TABLE savings_deposits ADD COLUMN deleted_at TEXT")
    if "deleted_by" not in cols:
        cur.execute("ALTER TABLE savings_deposits ADD COLUMN deleted_by INTEGER")
    conn.commit()


EXPENSE_TYPES = ("fixed", "variable")
RECURRENCES = ("daily", "weekly", "monthly", "yearly")


def _ensure_entry_metadata_schema(conn):
    """Additive columns for editable recurring windows and fixed/variable classification."""
    cur = conn.cursor()
    for table in ("rendimentos", "gastos"):
        cur.execute(f"PRAGMA table_info({table})")
        cols = {row[1] for row in cur.fetchall()}
        if "start_date" not in cols:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN start_date TEXT")
        if "end_date" not in cols:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN end_date TEXT")
        if "linked_source" not in cols:
            # Set on rows a shared workspace mirrors from a member's own workspace; NULL = entered here.
            cur.execute(f"ALTER TABLE {table} ADD COLUMN linked_source TEXT")
    for table in ("gastos", "transacoes_unicas"):
        cur.execute(f"PRAGMA table_info({table})")
        cols = {row[1] for row in cur.fetchall()}
        if "expense_type" not in cols:
            # NULL = not classified yet; never guessed.
            cur.execute(f"ALTER TABLE {table} ADD COLUMN expense_type TEXT")
    conn.commit()


def _ensure_all(conn):
    _ensure_oneoff_schema(conn)
    _ensure_recurring_recurrence(conn)
    _ensure_savings_schema(conn)
    _ensure_entry_metadata_schema(conn)


def parse_iso_date(value: str | None, *, required: bool = False) -> str | None:
    """Validate a YYYY-MM-DD string. Empty -> None unless required."""
    raw = (value or "").strip()
    if not raw:
        if required:
            raise ValueError("Date is required.")
        return None
    try:
        return datetime.strptime(raw[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("Invalid date; expected YYYY-MM-DD.") from exc


def normalize_recurrence(recurrence: str | None) -> str:
    rec = (recurrence or "monthly").lower().strip()
    return rec if rec in RECURRENCES else "monthly"


def normalize_expense_type(value: str | None) -> str | None:
    v = (value or "").strip().lower()
    return v if v in EXPENSE_TYPES else None


def validate_date_window(start_date: str | None, end_date: str | None) -> tuple[str | None, str | None]:
    s = parse_iso_date(start_date)
    e = parse_iso_date(end_date)
    if s and e and e < s:
        raise ValueError("End date must be on or after the start date.")
    return s, e


def recurring_active_in_month(item: dict, month: str) -> bool:
    """A recurring entry counts in YYYY-MM unless ended or outside its start/end window."""
    if item.get("ended"):
        return False
    m = str(month)[:7]
    start = item.get("start_date")
    end = item.get("end_date")
    if start and str(start)[:7] > m:
        return False
    if end and str(end)[:7] < m:
        return False
    return True


def _savings_active_clause(include_deleted: bool = False) -> str:
    return "" if include_deleted else " AND deleted_at IS NULL"


def init_finance_db(path: str):
    conn = _conn(path)
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS rendimentos (id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL, valor REAL NOT NULL, ativo INTEGER DEFAULT 1)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS gastos (id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL, valor REAL NOT NULL, ativo INTEGER DEFAULT 1)""")
    cur.execute(
        """CREATE TABLE IF NOT EXISTS transacoes_unicas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data TEXT NOT NULL,
            nome TEXT NOT NULL,
            valor REAL NOT NULL,
            category TEXT NOT NULL DEFAULT 'Other',
            txn_type TEXT NOT NULL DEFAULT 'expense'
        )"""
    )
    _ensure_all(conn)
    conn.commit()
    conn.close()


def init_logic_db(path: str):
    conn = _conn(path)
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS dias_aula (data TEXT PRIMARY KEY, horas_previstas REAL NOT NULL)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS faltas (id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL, modulo TEXT NOT NULL, horas REAL NOT NULL, observacao TEXT)""")
    conn.commit()
    conn.close()


def instance_paths(root: Path, user_id: int, instance_id: int, slug: str):
    user_dir = root / f"user_{user_id}"
    user_dir.mkdir(parents=True, exist_ok=True)
    finance = user_dir / f"{instance_id}_{slug}_financas.db"
    logic = user_dir / f"{instance_id}_{slug}_logic.db"
    return str(finance), str(logic)


def add_income(
    finance_db: str,
    nome: str,
    valor: float,
    recurrence: str = "monthly",
    start_date: str | None = None,
    end_date: str | None = None,
):
    rec = normalize_recurrence(recurrence)
    start, end = validate_date_window(start_date, end_date)
    conn = _conn(finance_db)
    _ensure_all(conn)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO rendimentos (nome, valor, ativo, recurrence, ended, start_date, end_date) VALUES (?, ?, 1, ?, 0, ?, ?)",
        (nome, valor, rec, start, end),
    )
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    return {"id": row_id, "entry": nome, "amount": valor, "recurrence": rec, "start_date": start, "end_date": end}


def add_expense(
    finance_db: str,
    nome: str,
    valor: float,
    recurrence: str = "monthly",
    category: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    expense_type: str | None = None,
):
    rec = normalize_recurrence(recurrence)
    cat = normalize_oneoff_category(category)
    start, end = validate_date_window(start_date, end_date)
    etype = normalize_expense_type(expense_type)
    conn = _conn(finance_db)
    _ensure_all(conn)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO gastos (nome, valor, ativo, recurrence, ended, category, start_date, end_date, expense_type) "
        "VALUES (?, ?, 1, ?, 0, ?, ?, ?, ?)",
        (nome, valor, rec, cat, start, end, etype),
    )
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    return {
        "id": row_id,
        "entry": nome,
        "amount": valor,
        "recurrence": rec,
        "category": cat,
        "start_date": start,
        "end_date": end,
        "expense_type": etype,
    }


def _require_name(nome: str | None) -> str:
    n = (nome or "").strip()
    if not n:
        raise ValueError("Name is required.")
    return n[:200]


def _require_amount(valor: float) -> float:
    v = float(valor)
    if not math.isfinite(v) or v <= 0:
        raise ValueError("Amount must be greater than zero.")
    return v


def update_income(
    finance_db: str,
    item_id: int,
    *,
    nome: str,
    valor: float,
    recurrence: str = "monthly",
    start_date: str | None = None,
    end_date: str | None = None,
    ended: bool = False,
):
    """Edit a recurring income in place (same row id). Returns None if missing."""
    name = _require_name(nome)
    amount = _require_amount(valor)
    rec = normalize_recurrence(recurrence)
    start, end = validate_date_window(start_date, end_date)
    conn = _conn(finance_db)
    _ensure_all(conn)
    cur = conn.cursor()
    cur.execute("SELECT id FROM rendimentos WHERE id = ? AND ativo = 1 AND linked_source IS NULL", (item_id,))
    if not cur.fetchone():
        conn.close()
        return None
    cur.execute(
        "UPDATE rendimentos SET nome = ?, valor = ?, recurrence = ?, start_date = ?, end_date = ?, ended = ? WHERE id = ?",
        (name, amount, rec, start, end, 1 if ended else 0, item_id),
    )
    conn.commit()
    conn.close()
    return {"id": item_id, "entry": name, "amount": amount, "recurrence": rec, "start_date": start, "end_date": end, "ended": bool(ended)}


def update_expense(
    finance_db: str,
    item_id: int,
    *,
    nome: str,
    valor: float,
    recurrence: str = "monthly",
    category: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    expense_type: str | None = None,
    ended: bool = False,
):
    """Edit a recurring expense in place (same row id). Returns None if missing."""
    name = _require_name(nome)
    amount = _require_amount(valor)
    rec = normalize_recurrence(recurrence)
    cat = normalize_oneoff_category(category)
    start, end = validate_date_window(start_date, end_date)
    etype = normalize_expense_type(expense_type)
    conn = _conn(finance_db)
    _ensure_all(conn)
    cur = conn.cursor()
    cur.execute("SELECT id FROM gastos WHERE id = ? AND ativo = 1 AND linked_source IS NULL", (item_id,))
    if not cur.fetchone():
        conn.close()
        return None
    cur.execute(
        "UPDATE gastos SET nome = ?, valor = ?, recurrence = ?, category = ?, start_date = ?, end_date = ?, "
        "expense_type = ?, ended = ? WHERE id = ?",
        (name, amount, rec, cat, start, end, etype, 1 if ended else 0, item_id),
    )
    conn.commit()
    conn.close()
    return {
        "id": item_id,
        "entry": name,
        "amount": amount,
        "recurrence": rec,
        "category": cat,
        "start_date": start,
        "end_date": end,
        "expense_type": etype,
        "ended": bool(ended),
    }


def update_oneoff(
    finance_db: str,
    item_id: int,
    *,
    data: str,
    nome: str,
    valor: float,
    txn_type: str = "expense",
    category: str | None = None,
    expense_type: str | None = None,
):
    """Edit a one-time transaction in place. Same category rules as add_oneoff."""
    name = _require_name(nome)
    amount = _require_amount(valor)
    day = parse_iso_date(data, required=True)
    tt = "income" if str(txn_type).lower() == "income" else "expense"
    if tt == "expense":
        c = (category or "").strip()
        if c not in ONEOFF_CATEGORIES:
            raise ValueError("Expense transactions require a valid category from the list.")
        cat = c
        etype = normalize_expense_type(expense_type)
    else:
        cat = normalize_oneoff_category(category)
        etype = None
    conn = _conn(finance_db)
    _ensure_all(conn)
    cur = conn.cursor()
    cur.execute("SELECT id FROM transacoes_unicas WHERE id = ?", (item_id,))
    if not cur.fetchone():
        conn.close()
        return None
    cur.execute(
        "UPDATE transacoes_unicas SET data = ?, nome = ?, valor = ?, category = ?, txn_type = ?, expense_type = ? WHERE id = ?",
        (day, name, amount, cat, tt, etype, item_id),
    )
    conn.commit()
    conn.close()
    return {"id": item_id, "date": day, "entry": name, "amount": amount, "category": cat, "txn_type": tt, "expense_type": etype}


def add_savings_deposit(finance_db: str, data: str, valor: float, nome: str = ""):
    conn = _conn(finance_db)
    _ensure_savings_schema(conn)
    cur = conn.cursor()
    label = (nome or "").strip() or "Savings deposit"
    cur.execute(
        "INSERT INTO savings_deposits (data, nome, valor) VALUES (?, ?, ?)",
        (data, label, float(valor)),
    )
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    return {"id": row_id, "date": data, "entry": label, "amount": valor}


def delete_savings_deposit(finance_db: str, item_id: int, deleted_by: int | None = None):
    conn = _conn(finance_db)
    _ensure_savings_schema(conn)
    cur = conn.cursor()
    cur.execute(
        "SELECT data, nome, valor FROM savings_deposits WHERE id = ? AND deleted_at IS NULL",
        (item_id,),
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return None
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
    cur.execute(
        "UPDATE savings_deposits SET deleted_at = ?, deleted_by = ? WHERE id = ?",
        (now, deleted_by, item_id),
    )
    conn.commit()
    conn.close()
    return {"id": item_id, "date": row[0], "entry": row[1], "amount": float(row[2])}


def update_savings_deposit(
    finance_db: str,
    item_id: int,
    *,
    data: str | None = None,
    valor: float | None = None,
    nome: str | None = None,
):
    conn = _conn(finance_db)
    _ensure_savings_schema(conn)
    cur = conn.cursor()
    cur.execute(
        "SELECT data, nome, valor FROM savings_deposits WHERE id = ? AND deleted_at IS NULL",
        (item_id,),
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return None
    new_data = data if data is not None else row[0]
    new_nome = nome if nome is not None else row[1]
    new_valor = float(valor) if valor is not None else float(row[2])
    cur.execute(
        "UPDATE savings_deposits SET data = ?, nome = ?, valor = ? WHERE id = ?",
        (new_data, new_nome, new_valor, item_id),
    )
    conn.commit()
    conn.close()
    return {"id": item_id, "date": new_data, "entry": new_nome, "amount": new_valor}


def total_savings_deposits(finance_db: str, *, include_deleted: bool = False) -> float:
    conn = _conn(finance_db)
    _ensure_savings_schema(conn)
    cur = conn.cursor()
    clause = _savings_active_clause(include_deleted)
    cur.execute(f"SELECT COALESCE(SUM(valor), 0) FROM savings_deposits WHERE 1=1{clause}")
    total = float(cur.fetchone()[0] or 0)
    conn.close()
    return round(total, 2)


def savings_deposits_for_month(finance_db: str, month: str, *, include_deleted: bool = False) -> float:
    conn = _conn(finance_db)
    _ensure_savings_schema(conn)
    cur = conn.cursor()
    clause = _savings_active_clause(include_deleted)
    cur.execute(
        f"SELECT COALESCE(SUM(valor), 0) FROM savings_deposits WHERE substr(data,1,7)=?{clause}",
        (month[:7],),
    )
    total = float(cur.fetchone()[0] or 0)
    conn.close()
    return round(total, 2)


def normalize_oneoff_category(category: str | None) -> str:
    c = (category or "").strip()
    if c in ONEOFF_CATEGORIES:
        return c
    return "Other"


def add_oneoff(
    finance_db: str,
    data: str,
    nome: str,
    valor: float,
    txn_type: str = "expense",
    category: str | None = None,
    expense_type: str | None = None,
):
    tt = "income" if str(txn_type).lower() == "income" else "expense"
    etype = normalize_expense_type(expense_type) if tt == "expense" else None
    conn = _conn(finance_db)
    _ensure_all(conn)
    cur = conn.cursor()
    if tt == "expense":
        c = (category or "").strip()
        if c not in ONEOFF_CATEGORIES:
            raise ValueError("Expense transactions require a valid category from the list.")
        cat = c
    else:
        cat = normalize_oneoff_category(category)
    cur.execute(
        "INSERT INTO transacoes_unicas (data, nome, valor, category, txn_type, expense_type) VALUES (?, ?, ?, ?, ?, ?)",
        (data, nome, float(valor), cat, tt, etype),
    )
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    return {"id": row_id, "date": data, "entry": nome, "amount": valor, "category": cat, "txn_type": tt, "expense_type": etype}


def delete_income(finance_db: str, item_id: int):
    """Linked rows (mirrored from a member's workspace) cannot be deleted here; returns None."""
    conn = _conn(finance_db)
    _ensure_all(conn)
    cur = conn.cursor()
    cur.execute("SELECT nome, valor FROM rendimentos WHERE id = ? AND linked_source IS NULL", (item_id,))
    row = cur.fetchone()
    if row is None:
        conn.close()
        return None
    cur.execute("DELETE FROM rendimentos WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()
    return row


def delete_expense(finance_db: str, item_id: int):
    """Linked rows (mirrored from a member's workspace) cannot be deleted here; returns None."""
    conn = _conn(finance_db)
    _ensure_all(conn)
    cur = conn.cursor()
    cur.execute("SELECT nome, valor FROM gastos WHERE id = ? AND linked_source IS NULL", (item_id,))
    row = cur.fetchone()
    if row is None:
        conn.close()
        return None
    cur.execute("DELETE FROM gastos WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()
    return row


def delete_oneoff(finance_db: str, item_id: int):
    conn = _conn(finance_db)
    cur = conn.cursor()
    cur.execute("SELECT data, nome, valor FROM transacoes_unicas WHERE id = ?", (item_id,))
    row = cur.fetchone()
    cur.execute("DELETE FROM transacoes_unicas WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()
    return row


ENTRY_KINDS = ("income", "expense", "oneoff", "savings")


def get_entry(finance_db: str, kind: str, item_id: int) -> dict | None:
    items = list_finance_items(finance_db)
    key = {"income": "incomes", "expense": "expenses", "oneoff": "oneoffs", "savings": "savings"}.get(kind)
    if not key:
        return None
    return next((row for row in items[key] if int(row["id"]) == int(item_id)), None)


def move_entry(src_db: str, dst_db: str, kind: str, item_id: int, *, deleted_by: int | None = None) -> dict | None:
    """
    Move one entry to another workspace file: insert the same fields in the target, then remove
    it from the source. The record exists in exactly one workspace afterwards (no duplicates).
    """
    row = get_entry(src_db, kind, item_id)
    if row is None or row.get("linked_source"):
        return None
    if kind == "income":
        created = add_income(
            dst_db, row["name"], row["amount"], recurrence=row.get("recurrence"),
            start_date=row.get("start_date"), end_date=row.get("end_date"),
        )
        delete_income(src_db, item_id)
    elif kind == "expense":
        created = add_expense(
            dst_db, row["name"], row["amount"], recurrence=row.get("recurrence"), category=row.get("category"),
            start_date=row.get("start_date"), end_date=row.get("end_date"), expense_type=row.get("expense_type"),
        )
        delete_expense(src_db, item_id)
    elif kind == "oneoff":
        created = add_oneoff(
            dst_db, row["date"], row["name"], row["amount"], txn_type=row.get("txn_type", "expense"),
            category=row.get("category"), expense_type=row.get("expense_type"),
        )
        delete_oneoff(src_db, item_id)
    elif kind == "savings":
        created = add_savings_deposit(dst_db, row["date"], row["amount"], nome=row.get("name") or "")
        delete_savings_deposit(src_db, item_id, deleted_by=deleted_by)
    else:
        return None
    return {"moved_from_id": item_id, "kind": kind, "new": created}


def add_absence(logic_db: str, data: str, modulo: str, horas: float, observacao: str = ""):
    conn = _conn(logic_db)
    cur = conn.cursor()
    cur.execute("INSERT INTO faltas (data, modulo, horas, observacao) VALUES (?, ?, ?, ?)", (data, modulo, horas, observacao))
    conn.commit()
    conn.close()
    return {"date": data, "module": modulo, "hours": horas}


def _sum_finance(finance_db: str, table: str):
    conn = _conn(finance_db)
    cur = conn.cursor()
    cur.execute(f"SELECT COALESCE(SUM(valor),0) FROM {table} WHERE ativo = 1")
    total = cur.fetchone()[0]
    conn.close()
    return float(total)


def list_oneoffs_for_month(finance_db: str, month: str) -> list[dict]:
    """One-time transactions in YYYY-MM (sorted by date, id)."""
    conn = _conn(finance_db)
    _ensure_oneoff_schema(conn)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, data, nome, valor, category, txn_type FROM transacoes_unicas WHERE substr(data,1,7)=? ORDER BY data ASC, id ASC",
        (month,),
    )
    rows = []
    for r in cur.fetchall():
        oid, d, nome, valor = r[0], r[1], r[2], float(r[3])
        cat = r[4] if len(r) > 4 and r[4] is not None else "Other"
        tt = r[5] if len(r) > 5 and r[5] is not None else "expense"
        cat = normalize_oneoff_category(cat)
        rows.append(
            {
                "id": oid,
                "date": d,
                "name": nome,
                "amount": valor,
                "category": cat,
                "txn_type": tt,
            }
        )
    conn.close()
    return rows


def oneoff_month_totals(finance_db: str, month: str) -> tuple[float, float]:
    """Returns (sum of income one-offs, sum of expense one-offs) for month, amounts positive."""
    inc = exp = 0.0
    for o in list_oneoffs_for_month(finance_db, month):
        amt = abs(float(o.get("amount") or 0))
        if str(o.get("txn_type", "expense")).lower() == "income":
            inc += amt
        else:
            exp += amt
    return round(inc, 2), round(exp, 2)


def list_finance_items(finance_db: str, *, include_deleted_savings: bool = False):
    conn = _conn(finance_db)
    _ensure_all(conn)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, nome, valor, recurrence, COALESCE(ended,0), next_due, start_date, end_date, linked_source "
        "FROM rendimentos WHERE ativo = 1 ORDER BY id"
    )
    incomes = []
    for r in cur.fetchall():
        incomes.append(
            {
                "id": r[0],
                "name": r[1],
                "amount": float(r[2]),
                "recurrence": r[3] or "monthly",
                "ended": bool(r[4]),
                "next_due": r[5],
                "start_date": r[6],
                "end_date": r[7],
                "linked_source": r[8],
            }
        )
    cur.execute(
        "SELECT id, nome, valor, recurrence, COALESCE(ended,0), next_due, category, start_date, end_date, expense_type, "
        "linked_source FROM gastos WHERE ativo = 1 ORDER BY id"
    )
    expenses = []
    for r in cur.fetchall():
        cat = r[6] if r[6] is not None else "Other"
        expenses.append(
            {
                "id": r[0],
                "name": r[1],
                "amount": float(r[2]),
                "recurrence": r[3] or "monthly",
                "ended": bool(r[4]),
                "next_due": r[5],
                "category": normalize_oneoff_category(cat),
                "start_date": r[7],
                "end_date": r[8],
                "expense_type": normalize_expense_type(r[9]),
                "linked_source": r[10],
            }
        )
    cur.execute("SELECT id, data, nome, valor, category, txn_type, expense_type FROM transacoes_unicas ORDER BY data, id")
    oneoffs = []
    for r in cur.fetchall():
        oid, d, nome, valor = r[0], r[1], r[2], float(r[3])
        cat = r[4] if r[4] is not None else "Other"
        tt = r[5] if r[5] is not None else "expense"
        cat = normalize_oneoff_category(cat)
        oneoffs.append(
            {
                "id": oid,
                "date": d,
                "name": nome,
                "amount": valor,
                "category": cat,
                "txn_type": tt,
                "expense_type": normalize_expense_type(r[6]),
            }
        )
    _ensure_savings_schema(conn)
    clause = _savings_active_clause(include_deleted=include_deleted_savings)
    cur.execute(
        f"SELECT id, data, nome, valor, deleted_at FROM savings_deposits WHERE 1=1{clause} ORDER BY data DESC, id DESC"
    )
    savings = [
        {
            "id": r[0],
            "date": r[1],
            "name": r[2],
            "amount": float(r[3]),
            "deleted_at": r[4] if len(r) > 4 else None,
        }
        for r in cur.fetchall()
    ]
    conn.close()
    return {"incomes": incomes, "expenses": expenses, "oneoffs": oneoffs, "savings": savings}


def _calc_iefp(logic_db: str, month: str):
    if month not in HORAS_MES:
        return 0.0
    conn = _conn(logic_db)
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(SUM(horas),0) FROM faltas WHERE substr(data,1,7)=?", (month,))
    faltas_mes = cur.fetchone()[0]
    cur.execute("SELECT data, horas_previstas FROM dias_aula WHERE substr(data,1,7)=?", (month,))
    dias = cur.fetchall()
    cur.execute("SELECT data, COALESCE(SUM(horas),0) FROM faltas WHERE substr(data,1,7)=? GROUP BY data", (month,))
    faltas_por_dia = dict(cur.fetchall())
    conn.close()
    horas_consideradas = max(HORAS_MES[month] - faltas_mes, 0)
    bolsa = min(horas_consideradas * VALOR_HORA_BOLSA, LIMITE_MENSAL_BOLSA)
    dias_alimentacao = 0
    for data, horas_dia in dias:
        if max(horas_dia - faltas_por_dia.get(data, 0), 0) >= MIN_HORAS_ALIMENTACAO:
            dias_alimentacao += 1
    return bolsa + (dias_alimentacao * VALOR_ALIMENTACAO_DIA)


def month_summary(finance_db: str, logic_db: str, month: str, include_iefp: bool = False):
    items = list_finance_items(finance_db)
    iefp = _calc_iefp(logic_db, month) if include_iefp else 0.0
    extras = sum(i["amount"] for i in items["incomes"] if recurring_active_in_month(i, month))
    gastos = sum(i["amount"] for i in items["expenses"] if recurring_active_in_month(i, month))
    oneoff_inc, oneoff_exp = oneoff_month_totals(finance_db, month)
    oneoff_net = round(oneoff_inc - oneoff_exp, 2)
    unicas = oneoff_net
    total = round(iefp + extras + oneoff_inc, 2)
    poupanca = round(total - gastos - oneoff_exp, 2)
    savings_month = savings_deposits_for_month(finance_db, month)
    savings_total = total_savings_deposits(finance_db)
    available_balance = round(poupanca - savings_month, 2)
    oneoffs = list_oneoffs_for_month(finance_db, month)
    summary = {
        "month": month,
        "iefp": round(iefp, 2),
        "extras": round(extras, 2),
        "one_off": unicas,
        "oneoff_income_total": oneoff_inc,
        "oneoff_expense_total": oneoff_exp,
        "oneoff_net": oneoff_net,
        "oneoff_transactions": oneoffs,
        "expenses": round(gastos, 2),
        "total_before_expenses": total,
        "estimated_savings": poupanca,
        "savings_deposits_month": savings_month,
        "savings_total": savings_total,
        "available_balance": available_balance,
        "income_items": items["incomes"],
        "expense_items": items["expenses"],
    }
    # Amounts are entered gross; user-defined taxes turn savings into after-tax figures.
    from app.services import tax_service

    return tax_service.apply_to_month(finance_db, summary)


def long_range(finance_db: str, logic_db: str, start_month: str, months: int, include_iefp: bool = False):
    start = datetime.strptime(start_month, "%Y-%m")
    rows = []
    accum = 0.0
    for i in range(months):
        m = (start + relativedelta(months=i)).strftime("%Y-%m")
        summary = month_summary(finance_db, logic_db, m, include_iefp=include_iefp)
        accum += summary["estimated_savings"]
        summary["accumulated"] = round(accum, 2)
        rows.append(summary)
    return rows


def list_metadata(finance_db: str, logic_db: str):
    items = list_finance_items(finance_db)
    absences = 0
    conn = _conn(logic_db)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM faltas")
    absences = cur.fetchone()[0]
    conn.close()
    return {
        "incomes": len(items["incomes"]),
        "expenses": len(items["expenses"]),
        "oneoffs": len(items["oneoffs"]),
        "absences": absences,
    }


def search_oneoffs(
    finance_db: str,
    *,
    q: str | None = None,
    category: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    amt_min: float | None = None,
    amt_max: float | None = None,
    txn_type: str | None = None,
    sort: str = "newest",
    limit: int = 50,
    offset: int = 0,
) -> dict:
    conn = _conn(finance_db)
    _ensure_oneoff_schema(conn)
    cur = conn.cursor()

    def _filters():
        frag, par = ["1=1"], []
        if q and str(q).strip():
            like = f"%{str(q).strip()}%"
            frag.append("(nome LIKE ? OR category LIKE ?)")
            par.extend([like, like])
        if category and str(category).strip() and str(category).lower() != "all":
            frag.append("category = ?")
            par.append(str(category).strip())
        if date_from:
            frag.append("data >= ?")
            par.append(str(date_from)[:10])
        if date_to:
            frag.append("data <= ?")
            par.append(str(date_to)[:10])
        if amt_min is not None:
            frag.append("ABS(valor) >= ?")
            par.append(abs(float(amt_min)))
        if amt_max is not None:
            frag.append("ABS(valor) <= ?")
            par.append(abs(float(amt_max)))
        if txn_type and str(txn_type).lower() in ("income", "expense"):
            frag.append("lower(txn_type) = ?")
            par.append(str(txn_type).lower())
        return " AND ".join(frag), par

    where_sql, params = _filters()
    order = "data DESC, id DESC"
    s = (sort or "newest").lower()
    if s == "oldest":
        order = "data ASC, id ASC"
    elif s in ("amount_high", "highest"):
        order = "ABS(valor) DESC, data DESC"
    elif s in ("amount_low", "lowest"):
        order = "ABS(valor) ASC, data DESC"
    cur.execute(f"SELECT COUNT(*) FROM transacoes_unicas WHERE {where_sql}", params)
    total = int(cur.fetchone()[0])
    lim = max(1, min(200, int(limit)))
    off = max(0, int(offset))
    cur.execute(
        f"SELECT id, data, nome, valor, category, txn_type FROM transacoes_unicas WHERE {where_sql} ORDER BY {order} LIMIT ? OFFSET ?",
        params + [lim, off],
    )
    rows = [
        {
            "id": r[0],
            "date": r[1],
            "name": r[2],
            "amount": float(r[3]),
            "category": r[4],
            "txn_type": r[5],
        }
        for r in cur.fetchall()
    ]
    conn.close()
    return {"total": total, "items": rows, "limit": lim, "offset": off}
