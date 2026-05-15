import os
import tempfile
import unittest

from app.services import emergency_fund_service, instance_service, savings_expenses_service


class TestSavingsExpensesSummary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.finance = os.path.join(self.tmp, "fin.db")
        instance_service.init_finance_db(self.finance)

    def test_empty_state(self):
        s = savings_expenses_service.summarize_saved_expenses(self.finance, "2026-05")
        self.assertFalse(s["has_data"])
        self.assertEqual(s["monthly_total"], 0.0)

    def test_recurring_expenses_included_income_excluded(self):
        instance_service.add_expense(self.finance, "Rent", 1000, recurrence="monthly")
        instance_service.add_income(self.finance, "Salary", 3000, recurrence="monthly")
        s = savings_expenses_service.summarize_saved_expenses(self.finance, "2026-05")
        self.assertTrue(s["has_data"])
        self.assertGreaterEqual(s["categories"]["housing"], 1000.0)
        self.assertEqual(s["monthly_total"], s["categories"]["housing"])

    def test_oneoff_expense_in_month(self):
        instance_service.add_expense(self.finance, "Netflix", 15, recurrence="monthly")
        instance_service.add_oneoff(self.finance, "2026-05-10", "Groceries", 80, txn_type="expense", category="Food")
        s = savings_expenses_service.summarize_saved_expenses(self.finance, "2026-05")
        self.assertGreater(s["categories"]["food"], 0)
        self.assertGreater(s["categories"]["subscriptions"], 0)

    def test_savings_investment_oneoffs_excluded(self):
        instance_service.add_oneoff(
            self.finance, "2026-05-01", "ETF buy", 500, txn_type="expense", category="Investments"
        )
        instance_service.add_oneoff(
            self.finance, "2026-05-02", "Transfer", 200, txn_type="expense", category="Savings"
        )
        s = savings_expenses_service.summarize_saved_expenses(self.finance, "2026-05")
        self.assertEqual(s["monthly_total"], 0.0)

    def test_uncategorized_recurring_goes_other(self):
        instance_service.add_expense(self.finance, "Misc fee", 42, recurrence="monthly")
        s = savings_expenses_service.summarize_saved_expenses(self.finance, "2026-05")
        self.assertEqual(s["categories"]["other"], 42.0)

    def test_emergency_fund_uses_expenses_not_salary(self):
        instance_service.add_expense(self.finance, "Rent", 500, recurrence="monthly")
        instance_service.add_income(self.finance, "Salary", 5000, recurrence="monthly")
        s = savings_expenses_service.summarize_saved_expenses(self.finance, "2026-05")
        cats = s["categories"]
        body = {**cats, "buffer_pct": 0, "current_savings": 0}
        r = emergency_fund_service.compute(body)
        self.assertEqual(r["monthly_essential_base"], 500.0)
        self.assertEqual(r["targets"][3], 1500.0)


if __name__ == "__main__":
    unittest.main()
