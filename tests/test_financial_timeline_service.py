"""Financial timeline event generation tests."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock

from app.services import financial_timeline_service as fts, instance_service


class TestFinancialTimelineService(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.finance = os.path.join(self.tmp.name, "f.sqlite")
        self.logic = os.path.join(self.tmp.name, "l.sqlite")
        lc = sqlite3.connect(self.logic)
        lc.execute("CREATE TABLE faltas (data TEXT, modulo TEXT, horas REAL, observacao TEXT)")
        lc.execute("CREATE TABLE dias_aula (data TEXT, horas_previstas REAL)")
        lc.commit()
        lc.close()
        instance_service.init_finance_db(self.finance)
        instance_service.add_income(self.finance, "Job", 2000.0)
        instance_service.add_expense(self.finance, "Rent", 900.0)
        instance_service.add_oneoff(self.finance, "2026-04-10", "Big buy", 500.0, txn_type="expense", category="Shopping")

    def tearDown(self):
        self.tmp.cleanup()

    def test_builds_income_and_expense_events(self):
        inst = MagicMock()
        inst.id = 1
        inst.finance_db_path = self.finance
        inst.logic_db_path = self.logic
        user = MagicMock()
        user.id = 1
        user.enable_iefp_mode = False
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
        events = fts.build_timeline_events(db, user, inst, month_filter="2026-04")
        types = {e["type"] for e in events}
        self.assertIn("income", types)
        self.assertTrue(types & {"expense", "large_expense"})

    def test_large_expense_detection(self):
        inst = MagicMock()
        inst.id = 1
        inst.finance_db_path = self.finance
        inst.logic_db_path = self.logic
        user = MagicMock()
        user.id = 1
        user.enable_iefp_mode = False
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
        events = fts.build_timeline_events(db, user, inst, month_filter="2026-04")
        large = [e for e in events if e["type"] == "large_expense"]
        self.assertTrue(large)
        self.assertEqual(large[0]["title"], "Big buy")

    def test_sort_newest_first(self):
        events = [
            {"date": "2026-04-01", "type": "a"},
            {"date": "2026-04-15", "type": "b"},
        ]
        events.sort(key=lambda e: (e.get("date") or "", e.get("type") or ""), reverse=True)
        self.assertEqual(events[0]["date"], "2026-04-15")

    def test_empty_month_filter(self):
        inst = MagicMock()
        inst.id = 1
        inst.finance_db_path = self.finance
        inst.logic_db_path = self.logic
        user = MagicMock()
        user.id = 1
        user.enable_iefp_mode = False
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
        events = fts.build_timeline_events(db, user, inst, month_filter="1999-01")
        txn = [e for e in events if e.get("source") == "transaction"]
        self.assertEqual(len(txn), 0)


if __name__ == "__main__":
    unittest.main()
