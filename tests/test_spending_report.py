"""Tests for spending report aggregation and date filtering."""

from __future__ import annotations

import unittest
from datetime import date, timedelta

from app.services import spending_report


class TestSpendingReport(unittest.TestCase):
    def setUp(self):
        self.oneoffs = [
            {"date": "2024-01-05", "name": "Rent", "amount": 500.0, "txn_type": "expense", "category": "Housing"},
            {"date": "2024-01-10", "name": "Groceries", "amount": 80.0, "txn_type": "expense", "category": "Food"},
            {"date": "2024-02-01", "name": "Groceries", "amount": 120.0, "txn_type": "expense", "category": "Food"},
            {"date": "2024-02-15", "name": "Salary bonus", "amount": 200.0, "txn_type": "income", "category": "Other"},
            {"date": "2024-03-01", "name": "Unknown", "amount": 50.0, "txn_type": "expense", "category": "InvalidCat"},
        ]

    def test_uncategorized_defaults_to_other_in_normalization_path(self):
        r = spending_report.build_spending_report(self.oneoffs, 0, 0, date(2024, 1, 1), date(2024, 12, 31))
        cats = {x["key"]: x["total"] for x in r["top_categories"]}
        self.assertIn("Other", cats)
        self.assertGreaterEqual(cats.get("Other", 0), 50.0)

    def test_top_categories_limited_to_seven_and_sorted(self):
        from app.services import instance_service

        valid = list(instance_service.ONEOFF_CATEGORIES)
        many = []
        for i in range(10):
            many.append(
                {
                    "date": "2024-04-01",
                    "name": f"Item{i}",
                    "amount": float(100 - i),
                    "txn_type": "expense",
                    "category": valid[i % len(valid)],
                }
            )
        r = spending_report.build_spending_report(many, 0, 0, None, None)
        self.assertLessEqual(len(r["top_categories"]), 7)
        if len(r["top_categories"]) >= 2:
            self.assertGreaterEqual(r["top_categories"][0]["total"], r["top_categories"][1]["total"])

    def test_date_range_filters_transactions(self):
        r = spending_report.build_spending_report(self.oneoffs, 0, 0, date(2024, 1, 1), date(2024, 1, 31))
        self.assertEqual(r["totals"]["transaction_count_expenses"], 2)
        self.assertAlmostEqual(r["totals"]["oneoff_expenses"], 580.0, places=1)

    def test_slider_equivalent_custom_range(self):
        r_full = spending_report.build_spending_report(self.oneoffs, 0, 0, date(2024, 1, 1), date(2024, 3, 31))
        r_slider = spending_report.build_spending_report(self.oneoffs, 0, 0, date(2024, 2, 1), date(2024, 2, 29))
        self.assertLess(r_slider["totals"]["oneoff_expenses"], r_full["totals"]["oneoff_expenses"])

    def test_top_merchants(self):
        r = spending_report.build_spending_report(self.oneoffs, 0, 0, None, None)
        names = [m["key"] for m in r["top_merchants"]]
        self.assertIn("Groceries", names)

    def test_preset_last_7_days(self):
        today = date(2024, 6, 15)
        s, e = spending_report.preset_range("last_7_days", today)
        self.assertEqual(e, today)
        self.assertEqual((today - s).days, 7)


class TestInvestmentCalculator(unittest.TestCase):
    def test_beginning_vs_end_ordering(self):
        from app.services import projection_finance

        beg = projection_finance.run_investment_calculator(
            initial_balance=1000,
            monthly_contribution=100,
            annual_rate_pct=12,
            years=1,
            compounding_per_year=12,
            contribution_timing="beginning",
        )
        endm = projection_finance.run_investment_calculator(
            initial_balance=1000,
            monthly_contribution=100,
            annual_rate_pct=12,
            years=1,
            compounding_per_year=12,
            contribution_timing="end",
        )
        self.assertNotAlmostEqual(beg["summary"]["final_balance"], endm["summary"]["final_balance"], places=1)

    def test_zero_rate_accumulates_contributions(self):
        from app.services import projection_finance

        r = projection_finance.run_investment_calculator(
            initial_balance=0,
            monthly_contribution=50,
            annual_rate_pct=0,
            years=2,
            compounding_per_year=12,
            contribution_timing="beginning",
        )
        self.assertAlmostEqual(r["summary"]["total_contributions"], 50 * 24, places=1)
        self.assertAlmostEqual(r["summary"]["final_balance"], 50 * 24, places=1)


class TestOneoffCategoryDB(unittest.TestCase):
    def test_expense_requires_category(self):
        import tempfile
        from app.services import instance_service

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        try:
            instance_service.init_finance_db(path)
            with self.assertRaises(ValueError):
                instance_service.add_oneoff(path, "2024-01-01", "X", 10.0, txn_type="expense", category=None)
            instance_service.add_oneoff(path, "2024-01-01", "X", 10.0, txn_type="expense", category="Food")
            items = instance_service.list_finance_items(path)
            self.assertEqual(items["oneoffs"][0]["category"], "Food")
            instance_service.add_oneoff(path, "2024-01-02", "Y", 5.0, txn_type="income", category="")
            items2 = instance_service.list_finance_items(path)
            self.assertEqual(len(items2["oneoffs"]), 2)
            self.assertEqual(items2["oneoffs"][-1]["category"], "Other")
        finally:
            import os

            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
