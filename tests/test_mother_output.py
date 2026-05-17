"""Tests for dashboard mother insights payload."""

from __future__ import annotations

import os
import tempfile
import unittest

from app.services import instance_service


def _collect_mother_entries(instances):
    """Mirror entry aggregation used on the dashboard (kept in tests to avoid importing FastAPI app)."""
    income_entries = []
    expense_entries = []
    for ins in instances:
        items = instance_service.list_finance_items(ins.finance_db_path)
        for row in items["incomes"]:
            if row.get("ended"):
                continue
            income_entries.append({"name": str(row["name"]), "amount_eur": round(float(row["amount"]), 2)})
        for row in items["expenses"]:
            if row.get("ended"):
                continue
            expense_entries.append({"name": str(row["name"]), "amount_eur": round(float(row["amount"]), 2)})
    return income_entries, expense_entries


class TestMotherOutput(unittest.TestCase):
    def test_income_expense_entry_lists(self):
        tmp = tempfile.TemporaryDirectory()
        finance = os.path.join(tmp.name, "f.sqlite")
        logic = os.path.join(tmp.name, "l.sqlite")
        import sqlite3

        lc = sqlite3.connect(logic)
        lc.execute("CREATE TABLE faltas (data TEXT, modulo TEXT, horas REAL, observacao TEXT)")
        lc.execute("CREATE TABLE dias_aula (data TEXT, horas_previstas REAL)")
        lc.commit()
        lc.close()
        instance_service.init_finance_db(finance)
        instance_service.add_income(finance, "Salary", 2000.0)
        instance_service.add_expense(finance, "Rent", 800.0)

        class FakeInst:
            id = 1
            name = "Home"
            finance_db_path = finance
            logic_db_path = logic

        inc, exp = _collect_mother_entries([FakeInst()])
        self.assertEqual(len(inc), 1)
        self.assertEqual(inc[0]["name"], "Salary")
        self.assertAlmostEqual(sum(x["amount_eur"] for x in inc), 2000.0)
        self.assertEqual(len(exp), 1)
        self.assertAlmostEqual(sum(x["amount_eur"] for x in exp), 800.0)
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
