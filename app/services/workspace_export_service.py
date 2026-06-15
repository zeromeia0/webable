"""
Export and import workspace finance databases as ZIP archives.
"""

from __future__ import annotations

import io
import json
import logging
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models import CategoryBudget, DatabaseInstance, MonthlySnapshot, User
from app.services import instance_service

log = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"
REQUIRED_TABLES = (
    "workspace.json",
    "rendimentos.json",
    "gastos.json",
    "transacoes_unicas.json",
    "savings_deposits.json",
    "category_budgets.json",
    "dias_aula.json",
    "faltas.json",
)


class ImportValidationError(Exception):
    def __init__(self, message: str, *, technical: str | None = None):
        super().__init__(message)
        self.technical = technical or message


def _read_sqlite_table(db_path: str, table: str) -> list[dict[str, Any]]:
    if not Path(db_path).is_file():
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT * FROM {table}")
        return [dict(r) for r in cur.fetchall()]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def _finance_tables(finance_db: str, *, include_deleted_savings: bool = False) -> dict[str, list]:
    savings_clause = "" if include_deleted_savings else " WHERE deleted_at IS NULL"
    conn = sqlite3.connect(finance_db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    instance_service._ensure_savings_schema(conn)
    out: dict[str, list] = {}
    for table in ("rendimentos", "gastos", "transacoes_unicas"):
        try:
            cur.execute(f"SELECT * FROM {table}")
            out[table] = [dict(r) for r in cur.fetchall()]
        except sqlite3.OperationalError:
            out[table] = []
    try:
        cur.execute(f"SELECT * FROM savings_deposits{savings_clause}")
        out["savings_deposits"] = [dict(r) for r in cur.fetchall()]
    except sqlite3.OperationalError:
        out["savings_deposits"] = []
    conn.close()
    return out


def _logic_tables(logic_db: str) -> dict[str, list]:
    out: dict[str, list] = {}
    for table in ("dias_aula", "faltas"):
        out[table] = _read_sqlite_table(logic_db, table)
    return out


def build_export_zip(
    db: Session,
    inst: DatabaseInstance,
    *,
    include_deleted_records: bool = False,
) -> bytes:
    finance = _finance_tables(inst.finance_db_path, include_deleted_savings=include_deleted_records)
    logic = _logic_tables(inst.logic_db_path)
    budgets = [
        {
            "id": b.id,
            "category": b.category,
            "monthly_limit_eur": b.monthly_limit_eur,
            "created_at": b.created_at.isoformat() if b.created_at else None,
        }
        for b in db.query(CategoryBudget).filter(CategoryBudget.instance_id == inst.id).all()
    ]
    snapshots = [
        {
            "year": s.year,
            "month": s.month,
            "total_income": s.total_income,
            "total_expenses": s.total_expenses,
            "net_balance": s.net_balance,
            "average_monthly_balance": s.average_monthly_balance,
            "safe_to_spend": s.safe_to_spend,
            "fixed_expenses_total": s.fixed_expenses_total,
            "fixed_expenses_percent_income": s.fixed_expenses_percent_income,
            "top_expenses_json": s.top_expenses_json,
            "top_income_json": s.top_income_json,
            "comparison_json": s.comparison_json,
            "summary_json": s.summary_json,
        }
        for s in db.query(MonthlySnapshot).filter(MonthlySnapshot.instance_id == inst.id).all()
    ]

    manifest = {
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "workspace_id": inst.id,
        "workspace_name": inst.name,
        "mode": inst.mode,
        "tables": {
            "rendimentos": len(finance["rendimentos"]),
            "gastos": len(finance["gastos"]),
            "transacoes_unicas": len(finance["transacoes_unicas"]),
            "savings_deposits": len(finance["savings_deposits"]),
            "category_budgets": len(budgets),
            "dias_aula": len(logic["dias_aula"]),
            "faltas": len(logic["faltas"]),
            "monthly_snapshots": len(snapshots),
        },
        "include_deleted_records": include_deleted_records,
    }

    workspace_meta = {
        "name": inst.name,
        "mode": inst.mode,
        "original_workspace_id": inst.id,
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        zf.writestr("schema_version.json", json.dumps({"version": SCHEMA_VERSION}, indent=2))
        zf.writestr("workspace.json", json.dumps(workspace_meta, indent=2))
        zf.writestr("rendimentos.json", json.dumps(finance["rendimentos"], indent=2))
        zf.writestr("gastos.json", json.dumps(finance["gastos"], indent=2))
        zf.writestr("transacoes_unicas.json", json.dumps(finance["transacoes_unicas"], indent=2))
        zf.writestr("savings_deposits.json", json.dumps(finance["savings_deposits"], indent=2))
        zf.writestr("category_budgets.json", json.dumps(budgets, indent=2))
        zf.writestr("dias_aula.json", json.dumps(logic["dias_aula"], indent=2))
        zf.writestr("faltas.json", json.dumps(logic["faltas"], indent=2))
        zf.writestr("monthly_snapshots.json", json.dumps(snapshots, indent=2))
    return buf.getvalue()


def _load_zip_json(zf: zipfile.ZipFile, name: str) -> Any:
    try:
        raw = zf.read(name).decode("utf-8")
    except KeyError as exc:
        raise ImportValidationError(f"Missing required file: {name}") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ImportValidationError(f"Invalid JSON in {name}.") from exc


def validate_import_zip(data: bytes) -> dict[str, Any]:
    if not data or len(data) < 22:
        raise ImportValidationError("File is empty or not a valid ZIP archive.")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ImportValidationError("Invalid ZIP file.") from exc

    with zf:
        if zf.testzip() is not None:
            raise ImportValidationError("ZIP archive is corrupted.")

        schema = _load_zip_json(zf, "schema_version.json")
        version = str(schema.get("version", ""))
        if version != SCHEMA_VERSION:
            raise ImportValidationError(
                f"Unsupported schema version: {version}. Expected {SCHEMA_VERSION}."
            )

        manifest = _load_zip_json(zf, "manifest.json")
        workspace = _load_zip_json(zf, "workspace.json")

        tables: dict[str, list] = {}
        for fname in (
            "rendimentos.json",
            "gastos.json",
            "transacoes_unicas.json",
            "savings_deposits.json",
            "category_budgets.json",
            "dias_aula.json",
            "faltas.json",
            "monthly_snapshots.json",
        ):
            tables[fname.replace(".json", "")] = _load_zip_json(zf, fname)

        _validate_records(tables)

        dates: list[str] = []
        for row in tables.get("transacoes_unicas") or []:
            if row.get("data"):
                dates.append(str(row["data"])[:10])
        for row in tables.get("savings_deposits") or []:
            if row.get("data"):
                dates.append(str(row["data"])[:10])

        date_range = None
        if dates:
            dates.sort()
            date_range = {"min": dates[0], "max": dates[-1]}

        return {
            "manifest": manifest,
            "workspace": workspace,
            "preview": {
                "workspace_name": workspace.get("name") or manifest.get("workspace_name") or "Imported workspace",
                "accounts": 0,
                "transactions": len(tables.get("transacoes_unicas") or []),
                "categories": len(tables.get("category_budgets") or []),
                "savings_records": len(tables.get("savings_deposits") or []),
                "income_entries": len(tables.get("rendimentos") or []),
                "expense_entries": len(tables.get("gastos") or []),
                "date_range": date_range,
            },
            "tables": tables,
        }


def _validate_records(tables: dict[str, list]) -> None:
    for table, rows in tables.items():
        if not isinstance(rows, list):
            raise ImportValidationError(f"{table} must be a JSON array.")

    for row in tables.get("transacoes_unicas") or []:
        if not row.get("data") or not row.get("nome"):
            raise ImportValidationError("Transaction records require date and name.")
        try:
            float(row.get("valor", 0))
        except (TypeError, ValueError) as exc:
            raise ImportValidationError("Invalid transaction amount.") from exc

    for row in tables.get("savings_deposits") or []:
        try:
            amt = float(row.get("valor", 0))
            if amt <= 0:
                raise ImportValidationError("Savings deposit amounts must be positive.")
        except (TypeError, ValueError) as exc:
            raise ImportValidationError("Invalid savings deposit amount.") from exc


def import_as_new_workspace(
    db: Session,
    user: User,
    data_root: Path,
    validated: dict[str, Any],
) -> DatabaseInstance:
    """Create a new workspace from validated import data. Runs in a transaction."""
    tables = validated["tables"]
    ws_name = validated["preview"]["workspace_name"]
    if not str(ws_name).strip():
        ws_name = f"Imported {datetime.utcnow().strftime('%Y-%m-%d')}"

    slug = f"import_{uuid4().hex[:8]}"
    tmp_id = int(datetime.utcnow().timestamp())
    finance_path, logic_path = instance_service.instance_paths(
        data_root, user.id, tmp_id, slug
    )
    instance_service.init_finance_db(finance_path)
    instance_service.init_logic_db(logic_path)

    try:
        inst = DatabaseInstance(
            owner_id=user.id,
            name=str(ws_name).strip()[:120],
            mode=str(validated["workspace"].get("mode") or "general"),
            finance_db_path=finance_path,
            logic_db_path=logic_path,
            last_sync_status="Imported successfully",
            last_activity_at=datetime.utcnow(),
        )
        db.add(inst)
        db.flush()

        _insert_finance_rows(finance_path, tables)
        _insert_logic_rows(logic_path, tables)

        for row in tables.get("category_budgets") or []:
            db.add(
                CategoryBudget(
                    instance_id=inst.id,
                    category=str(row.get("category") or "Other"),
                    monthly_limit_eur=float(row.get("monthly_limit_eur") or 0),
                )
            )

        for row in tables.get("monthly_snapshots") or []:
            db.add(
                MonthlySnapshot(
                    instance_id=inst.id,
                    year=int(row["year"]),
                    month=int(row["month"]),
                    total_income=float(row.get("total_income") or 0),
                    total_expenses=float(row.get("total_expenses") or 0),
                    net_balance=float(row.get("net_balance") or 0),
                    average_monthly_balance=row.get("average_monthly_balance"),
                    safe_to_spend=row.get("safe_to_spend"),
                    fixed_expenses_total=float(row.get("fixed_expenses_total") or 0),
                    fixed_expenses_percent_income=row.get("fixed_expenses_percent_income"),
                    top_expenses_json=row.get("top_expenses_json") or "[]",
                    top_income_json=row.get("top_income_json") or "[]",
                    comparison_json=row.get("comparison_json") or "{}",
                    summary_json=row.get("summary_json") or "[]",
                )
            )

        from app.services.workspace_service import add_owner_member

        add_owner_member(db, inst.id, user.id)
        db.commit()
        db.refresh(inst)
        return inst
    except Exception:
        db.rollback()
        for p in (finance_path, logic_path):
            try:
                Path(p).unlink(missing_ok=True)
            except OSError:
                pass
        raise


def _insert_finance_rows(finance_path: str, tables: dict[str, list]) -> None:
    conn = sqlite3.connect(finance_path)
    cur = conn.cursor()
    instance_service._ensure_oneoff_schema(conn)
    instance_service._ensure_recurring_recurrence(conn)
    instance_service._ensure_savings_schema(conn)

    for row in tables.get("rendimentos") or []:
        cur.execute(
            "INSERT INTO rendimentos (nome, valor, ativo, recurrence, ended, next_due) VALUES (?, ?, ?, ?, ?, ?)",
            (
                row.get("nome"),
                float(row.get("valor") or 0),
                row.get("ativo", 1),
                row.get("recurrence") or "monthly",
                row.get("ended", 0),
                row.get("next_due"),
            ),
        )

    for row in tables.get("gastos") or []:
        cur.execute(
            "INSERT INTO gastos (nome, valor, ativo, recurrence, ended, next_due, category) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                row.get("nome"),
                float(row.get("valor") or 0),
                row.get("ativo", 1),
                row.get("recurrence") or "monthly",
                row.get("ended", 0),
                row.get("next_due"),
                row.get("category") or "Other",
            ),
        )

    for row in tables.get("transacoes_unicas") or []:
        cur.execute(
            "INSERT INTO transacoes_unicas (data, nome, valor, category, txn_type) VALUES (?, ?, ?, ?, ?)",
            (
                row.get("data"),
                row.get("nome"),
                float(row.get("valor") or 0),
                row.get("category") or "Other",
                row.get("txn_type") or "expense",
            ),
        )

    for row in tables.get("savings_deposits") or []:
        cur.execute(
            "INSERT INTO savings_deposits (data, nome, valor, deleted_at, deleted_by) VALUES (?, ?, ?, ?, ?)",
            (
                row.get("data"),
                row.get("nome") or "Savings deposit",
                float(row.get("valor") or 0),
                row.get("deleted_at"),
                row.get("deleted_by"),
            ),
        )

    conn.commit()
    conn.close()


def _insert_logic_rows(logic_path: str, tables: dict[str, list]) -> None:
    conn = sqlite3.connect(logic_path)
    cur = conn.cursor()
    for row in tables.get("dias_aula") or []:
        cur.execute(
            "INSERT OR REPLACE INTO dias_aula (data, horas_previstas) VALUES (?, ?)",
            (row.get("data"), float(row.get("horas_previstas") or 0)),
        )
    for row in tables.get("faltas") or []:
        cur.execute(
            "INSERT INTO faltas (data, modulo, horas, observacao) VALUES (?, ?, ?, ?)",
            (
                row.get("data"),
                row.get("modulo") or "",
                float(row.get("horas") or 0),
                row.get("observacao") or "",
            ),
        )
    conn.commit()
    conn.close()
