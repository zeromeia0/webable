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
    conn.commit()


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
    _ensure_oneoff_schema(conn)
    _ensure_recurring_recurrence(conn)
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


def add_income(finance_db: str, nome: str, valor: float, recurrence: str = "monthly"):
    rec = (recurrence or "monthly").lower().strip()
    if rec not in ("daily", "weekly", "monthly", "yearly"):
        rec = "monthly"
    conn = _conn(finance_db)
    _ensure_recurring_recurrence(conn)
    cur = conn.cursor()
    cur.execute("INSERT INTO rendimentos (nome, valor, ativo, recurrence, ended) VALUES (?, ?, 1, ?, 0)", (nome, valor, rec))
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    return {"id": row_id, "entry": nome, "amount": valor, "recurrence": rec}


def add_expense(finance_db: str, nome: str, valor: float, recurrence: str = "monthly"):
    rec = (recurrence or "monthly").lower().strip()
    if rec not in ("daily", "weekly", "monthly", "yearly"):
        rec = "monthly"
    conn = _conn(finance_db)
    _ensure_recurring_recurrence(conn)
    cur = conn.cursor()
    cur.execute("INSERT INTO gastos (nome, valor, ativo, recurrence, ended) VALUES (?, ?, 1, ?, 0)", (nome, valor, rec))
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    return {"id": row_id, "entry": nome, "amount": valor, "recurrence": rec}


def normalize_oneoff_category(category: str | None) -> str:
    c = (category or "").strip()
    if c in ONEOFF_CATEGORIES:
        return c
    return "Other"


def add_oneoff(finance_db: str, data: str, nome: str, valor: float, txn_type: str = "expense", category: str | None = None):
    tt = "income" if str(txn_type).lower() == "income" else "expense"
    conn = _conn(finance_db)
    _ensure_oneoff_schema(conn)
    cur = conn.cursor()
    if tt == "expense":
        c = (category or "").strip()
        if c not in ONEOFF_CATEGORIES:
            raise ValueError("Expense transactions require a valid category from the list.")
        cat = c
    else:
        cat = normalize_oneoff_category(category)
    cur.execute(
        "INSERT INTO transacoes_unicas (data, nome, valor, category, txn_type) VALUES (?, ?, ?, ?, ?)",
        (data, nome, float(valor), cat, tt),
    )
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    return {"id": row_id, "date": data, "entry": nome, "amount": valor, "category": cat, "txn_type": tt}


def delete_income(finance_db: str, item_id: int):
    conn = _conn(finance_db)
    cur = conn.cursor()
    cur.execute("SELECT nome, valor FROM rendimentos WHERE id = ?", (item_id,))
    row = cur.fetchone()
    cur.execute("DELETE FROM rendimentos WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()
    return row


def delete_expense(finance_db: str, item_id: int):
    conn = _conn(finance_db)
    cur = conn.cursor()
    cur.execute("SELECT nome, valor FROM gastos WHERE id = ?", (item_id,))
    row = cur.fetchone()
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


def list_finance_items(finance_db: str):
    conn = _conn(finance_db)
    _ensure_oneoff_schema(conn)
    _ensure_recurring_recurrence(conn)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, nome, valor, recurrence, COALESCE(ended,0), next_due FROM rendimentos WHERE ativo = 1 ORDER BY id"
    )
    incomes = []
    for r in cur.fetchall():
        incomes.append(
            {
                "id": r[0],
                "name": r[1],
                "amount": float(r[2]),
                "recurrence": r[3] if len(r) > 3 and r[3] else "monthly",
                "ended": bool(r[4]) if len(r) > 4 else False,
                "next_due": r[5] if len(r) > 5 else None,
            }
        )
    cur.execute("SELECT id, nome, valor, recurrence, COALESCE(ended,0), next_due FROM gastos WHERE ativo = 1 ORDER BY id")
    expenses = []
    for r in cur.fetchall():
        expenses.append(
            {
                "id": r[0],
                "name": r[1],
                "amount": float(r[2]),
                "recurrence": r[3] if len(r) > 3 and r[3] else "monthly",
                "ended": bool(r[4]) if len(r) > 4 else False,
                "next_due": r[5] if len(r) > 5 else None,
            }
        )
    cur.execute("SELECT id, data, nome, valor, category, txn_type FROM transacoes_unicas ORDER BY data, id")
    oneoffs = []
    for r in cur.fetchall():
        oid, d, nome, valor = r[0], r[1], r[2], float(r[3])
        cat = r[4] if len(r) > 4 and r[4] is not None else "Other"
        tt = r[5] if len(r) > 5 and r[5] is not None else "expense"
        cat = normalize_oneoff_category(cat)
        oneoffs.append(
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
    return {"incomes": incomes, "expenses": expenses, "oneoffs": oneoffs}


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
    extras = sum(i["amount"] for i in items["incomes"] if not i.get("ended"))
    gastos = sum(i["amount"] for i in items["expenses"] if not i.get("ended"))
    oneoff_inc, oneoff_exp = oneoff_month_totals(finance_db, month)
    oneoff_net = round(oneoff_inc - oneoff_exp, 2)
    # Legacy field: net effect of one-time transactions (income minus expenses)
    unicas = oneoff_net
    total = round(iefp + extras + oneoff_inc, 2)
    poupanca = round(total - gastos - oneoff_exp, 2)
    oneoffs = list_oneoffs_for_month(finance_db, month)
    return {
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
        "income_items": items["incomes"],
        "expense_items": items["expenses"],
    }


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
