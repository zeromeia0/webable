"""Net worth balances/items and spending reports with itemized recurring entries."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date

from app.services import analysis_service, instance_service, net_worth_service, spending_report


class _FinanceCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.fin = os.path.join(self.tmp, "ws_financas.db")
        self.logic = os.path.join(self.tmp, "ws_logic.db")
        instance_service.init_finance_db(self.fin)
        instance_service.init_logic_db(self.logic)


class TestNetWorth(_FinanceCase):
    def test_empty_workspace(self):
        s = net_worth_service.summary(self.fin)
        self.assertEqual(s["totals"]["net_worth"], 0)
        self.assertFalse(s["balances"]["is_set"])
        self.assertIsNone(s["emergency"]["months_covered"])

    def test_balances_and_items_roll_into_net_worth(self):
        net_worth_service.set_balances(self.fin, emergency_fund=3000, invested=10000)
        net_worth_service.add_item(self.fin, "asset", "Car", 5000, category="Vehicle")
        loan = net_worth_service.add_item(self.fin, "liability", "Car loan", 4000, category="Car loan")
        s = net_worth_service.summary(self.fin, with_history=True)
        self.assertEqual(s["totals"]["assets"], 18000)
        self.assertEqual(s["totals"]["liabilities"], 4000)
        self.assertEqual(s["totals"]["net_worth"], 14000)
        self.assertEqual(len(s["history"]), 1)
        self.assertEqual(s["history"][0]["net_worth"], 14000)

        net_worth_service.update_item(self.fin, loan, "liability", "Car loan", 1000, category="Car loan")
        net_worth_service.set_balances(self.fin, emergency_fund=None, invested=12000)
        s = net_worth_service.summary(self.fin)
        self.assertEqual(s["balances"]["emergency_fund"], 3000)  # None leaves it unchanged
        self.assertEqual(s["totals"]["net_worth"], 19000)

        net_worth_service.delete_item(self.fin, loan)
        self.assertEqual(net_worth_service.summary(self.fin)["totals"]["liabilities"], 0)
        with self.assertRaises(LookupError):
            net_worth_service.delete_item(self.fin, loan)

    def test_emergency_coverage_uses_recurring_expenses(self):
        instance_service.add_expense(self.fin, "Rent", 900, "monthly", category="Housing")
        instance_service.add_expense(self.fin, "Insurance", 1200, "yearly", category="Other")
        net_worth_service.set_balances(self.fin, emergency_fund=4000)
        em = net_worth_service.summary(self.fin)["emergency"]
        self.assertEqual(em["monthly_expenses"], 1000)
        self.assertEqual(em["months_covered"], 4.0)
        self.assertEqual(em["target"], 6000)
        self.assertEqual(em["still_needed"], 2000)
        self.assertEqual(em["level"], "building")

    def test_parse_amount(self):
        self.assertEqual(net_worth_service.parse_amount("1 234,56"), 1234.56)
        self.assertEqual(net_worth_service.parse_amount("1,234.56"), 1234.56)
        self.assertEqual(net_worth_service.parse_amount("1.234,5"), 1234.5)
        self.assertIsNone(net_worth_service.parse_amount("", allow_empty=True))
        for bad in ("-1", "abc", ""):
            with self.assertRaises(ValueError):
                net_worth_service.parse_amount(bad)

    def test_item_validation(self):
        with self.assertRaises(ValueError):
            net_worth_service.add_item(self.fin, "asset", "  ", 10)
        with self.assertRaises(ValueError):
            net_worth_service.add_item(self.fin, "thing", "X", 10)
        net_worth_service.add_item(self.fin, "asset", "X", 10, category="Not a category")
        self.assertEqual(net_worth_service.list_items(self.fin)[0]["category"], "Other")

    def test_analysis_uses_balances(self):
        instance_service.add_expense(self.fin, "Rent", 1000, "monthly", category="Housing")
        net_worth_service.set_balances(self.fin, emergency_fund=2000, invested=5000)
        data = analysis_service.build_workspace_analytics(
            self.fin,
            self.logic,
            include_iefp=False,
            current_month=date.today().strftime("%Y-%m"),
            net_worth=net_worth_service.summary(self.fin),
        )
        self.assertEqual(data["emergency_fund_hint"]["current_emergency_fund_eur"], 2000)
        self.assertEqual(data["emergency_fund_hint"]["months_covered"], 2.0)
        self.assertTrue(any("emergency fund" in i.lower() for i in data["insights"]))
        self.assertNotIn("compound_savings", data)


class TestItemizedSpendingReport(unittest.TestCase):
    def setUp(self):
        self.incomes = [{"name": "Salary", "amount": 2000.0, "recurrence": "monthly", "ended": False, "start_date": "2024-01-01", "end_date": None}]
        self.expenses = [
            {"name": "Rent", "amount": 900.0, "recurrence": "monthly", "ended": False, "category": "Housing", "start_date": None, "end_date": None},
            {"name": "Gym", "amount": 30.0, "recurrence": "monthly", "ended": False, "category": "Health", "start_date": "2024-03-01", "end_date": None},
            {"name": "Old", "amount": 50.0, "recurrence": "monthly", "ended": True, "category": "Other", "start_date": None, "end_date": None},
        ]

    def _report(self, start, end, oneoffs=()):
        return spending_report.build_spending_report(
            list(oneoffs), 0, 0, start, end, recurring_incomes=self.incomes, recurring_expenses=self.expenses
        )

    def test_recurring_counted_per_active_month(self):
        r = self._report(date(2024, 1, 1), date(2024, 4, 30))
        by_month = {m["month"]: m for m in r["monthly"]}
        self.assertEqual(by_month["2024-01"]["recurring_expenses"], 900)
        self.assertEqual(by_month["2024-03"]["recurring_expenses"], 930)
        self.assertEqual(r["totals"]["recurring_expenses_in_range"], 900 * 4 + 30 * 2)
        self.assertEqual(r["totals"]["total_income"], 8000)
        self.assertEqual(r["top_categories"][0]["key"], "Housing")
        self.assertIn("Rent (recurring)", [m["key"] for m in r["top_merchants"]])

    def test_partial_month_is_prorated(self):
        r = self._report(date(2024, 4, 1), date(2024, 4, 15))
        self.assertAlmostEqual(r["totals"]["recurring_expenses_in_range"], 930 * 15 / 30, places=2)

    def test_recurring_only_workspace_has_data(self):
        r = self._report(None, None)
        self.assertTrue(r["monthly"])
        self.assertGreater(r["totals"]["total_expenses"], 0)

    def test_report_date_bounds_cover_recurring_and_a_year(self):
        lo, hi = spending_report.report_date_bounds([], self.expenses + self.incomes, today=date(2026, 6, 1))
        self.assertEqual(lo, date(2024, 1, 1))
        self.assertEqual(hi, date(2026, 6, 1))
        lo, _ = spending_report.report_date_bounds([], [], today=date(2026, 6, 1))
        self.assertEqual(lo, date(2025, 6, 1))


if __name__ == "__main__":
    unittest.main()
