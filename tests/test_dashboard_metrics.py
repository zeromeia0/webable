"""Tests for dashboard_metrics helpers."""

import unittest

from app.services import dashboard_metrics as dm


class TestDashboardMetrics(unittest.TestCase):
    def test_safe_to_spend_zero_when_no_savings(self):
        self.assertEqual(dm.safe_to_spend_amount(0, 25), 0.0)
        self.assertEqual(dm.safe_to_spend_amount(-100, 50), 0.0)

    def test_safe_to_spend_percentage(self):
        self.assertAlmostEqual(dm.safe_to_spend_amount(1000, 25), 250.0)
        self.assertAlmostEqual(dm.safe_to_spend_amount(200, 10), 20.0)

    def test_current_month_balance(self):
        self.assertAlmostEqual(dm.current_month_balance(3000, 850), 2150.0)

    def test_expense_pct_labels(self):
        row = dm.enrich_expense_entry({"name": "Rent", "amount_eur": 700}, 1260, 1500)
        self.assertEqual(row["pct_of_expenses"], "55.6")
        self.assertEqual(row["pct_of_income"], "46.7")
        self.assertIn("55.6% of expenses", row["pct_expenses_label"])

    def test_zero_income(self):
        row = dm.enrich_expense_entry({"name": "X", "amount_eur": 10}, 100, 0)
        self.assertEqual(row["pct_income_label"], "income unavailable")

    def test_zero_expenses(self):
        row = dm.enrich_expense_entry({"name": "X", "amount_eur": 10}, 0, 100)
        self.assertEqual(row["pct_expenses_label"], "expenses unavailable")

    def test_fixed_expenses_summary(self):
        s = dm.fixed_expenses_summary(850, 1500)
        self.assertAlmostEqual(s["amount_eur"], 850.0)
        self.assertEqual(s["pct_of_income"], "56.7")

    def test_wishlist_affordability(self):
        self.assertEqual(dm.wishlist_affordability(50, 200)["label"], "Affordable now")
        self.assertEqual(dm.wishlist_affordability(300, 100)["tone"], "negative")

    def test_validate_quick_oneoff(self):
        self.assertEqual(len(dm.validate_quick_oneoff(10, "Coffee", "expense")), 0)
        self.assertTrue(len(dm.validate_quick_oneoff(0, "x", "expense")) > 0)
        self.assertTrue(len(dm.validate_quick_oneoff(10, "", "expense")) > 0)
        self.assertTrue(len(dm.validate_quick_oneoff(10, "ok", "bad")) > 0)


if __name__ == "__main__":
    unittest.main()
