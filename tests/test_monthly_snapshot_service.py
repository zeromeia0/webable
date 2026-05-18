"""Monthly snapshot calculation tests."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from datetime import date

from app.services import instance_service, monthly_snapshot_service as mss


class TestMonthlySnapshotService(unittest.TestCase):
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
        instance_service.add_income(self.finance, "Salary", 3000.0)
        instance_service.add_expense(self.finance, "Rent", 1000.0)
        instance_service.add_expense(self.finance, "Food", 400.0)
        instance_service.add_oneoff(self.finance, "2026-04-15", "Bonus", 200.0, txn_type="income")
        instance_service.add_oneoff(self.finance, "2026-04-20", "Repair", 150.0, txn_type="expense", category="Other")

    def tearDown(self):
        self.tmp.cleanup()

    def test_compute_snapshot_totals(self):
        payload = mss.compute_snapshot_payload(self.finance, self.logic, "2026-04", include_iefp=False)
        self.assertEqual(payload["year"], 2026)
        self.assertEqual(payload["month"], 4)
        self.assertGreater(payload["total_income"], 0)
        self.assertGreater(payload["total_expenses"], 0)
        self.assertIn("summary_lines", payload)
        self.assertTrue(payload["top_expenses"])

    def test_comparison_with_previous_month(self):
        cur = mss.compute_snapshot_payload(self.finance, self.logic, "2026-04", include_iefp=False)
        prev = mss.compute_snapshot_payload(self.finance, self.logic, "2026-03", include_iefp=False)
        with_prev = mss.compute_snapshot_payload(
            self.finance, self.logic, "2026-04", include_iefp=False, prev_payload=prev
        )
        self.assertIn("income_change", with_prev["comparison"])
        self.assertIn("expenses_change", with_prev["comparison"])
        self.assertTrue(with_prev["summary_lines"])

    def test_is_completed_month(self):
        self.assertTrue(mss.is_completed_month(2026, 3, date(2026, 5, 10)))
        self.assertFalse(mss.is_completed_month(2026, 5, date(2026, 5, 10)))

    def test_zero_income_fixed_pct(self):
        f2 = os.path.join(self.tmp.name, "f2.sqlite")
        instance_service.init_finance_db(f2)
        instance_service.add_expense(f2, "Rent", 500.0)
        payload = mss.compute_snapshot_payload(f2, self.logic, "2026-05", include_iefp=False)
        self.assertIsNone(payload.get("fixed_expenses_percent_income"))


if __name__ == "__main__":
    unittest.main()
