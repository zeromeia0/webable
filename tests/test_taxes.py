"""User-defined taxes assigned per income, and their effect on month summaries and investment gains."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest

from app.services import instance_service, tax_service


class TestTaxes(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp()
        self.fin = os.path.join(tmp, "ws_financas.db")
        self.logic = os.path.join(tmp, "ws_logic.db")
        instance_service.init_finance_db(self.fin)
        instance_service.init_logic_db(self.logic)
        self.salary = instance_service.add_income(self.fin, "Salary", 1500, "monthly")["id"]
        self.side = instance_service.add_income(self.fin, "Side gig", 500, "monthly")["id"]
        instance_service.add_expense(self.fin, "Rent", 600, "monthly", category="Housing")

    def _month(self):
        return instance_service.month_summary(self.fin, self.logic, "2026-10")

    def test_unassigned_taxes_do_nothing(self):
        tax_service.add_rule(self.fin, "Income tax", rate_pct=20)
        sm = self._month()
        self.assertEqual(sm["taxes_total"], 0)
        self.assertEqual(sm["estimated_savings"], 1400)

    def test_taxes_only_hit_assigned_incomes(self):
        irs = tax_service.add_rule(self.fin, "IRS", rate_pct=20)
        fee = tax_service.add_rule(self.fin, "Flat fee", fixed_monthly=15)
        tax_service.set_income_taxes(self.fin, "recurring", self.salary, [irs, fee])
        sm = self._month()
        self.assertEqual(sm["income_pre_tax"], 2000)
        self.assertEqual(sm["taxes_total"], 315)  # 20% of 1500 + 15; the side gig is untaxed
        self.assertEqual(sm["income_after_tax"], 1685)
        self.assertEqual(sm["estimated_savings_pre_tax"], 1400)
        self.assertEqual(sm["estimated_savings"], 1085)
        line = next(l for l in sm["taxes"]["lines"] if l["name"] == "IRS")
        self.assertEqual(line["incomes"], ["Salary"])
        self.assertEqual(line["base"], 1500)

    def test_same_tax_on_two_incomes(self):
        irs = tax_service.add_rule(self.fin, "IRS", rate_pct=10)
        tax_service.set_income_taxes(self.fin, "recurring", self.salary, [irs])
        tax_service.set_income_taxes(self.fin, "recurring", self.side, [irs])
        self.assertEqual(self._month()["taxes_total"], 200)

    def test_oneoff_income_taxes(self):
        bonus = instance_service.add_oneoff(self.fin, "2026-10-05", "Bonus", 500, txn_type="income")["id"]
        t = tax_service.add_rule(self.fin, "Bonus tax", rate_pct=10)
        tax_service.set_income_taxes(self.fin, "oneoff", bonus, [t])
        self.assertEqual(self._month()["taxes_total"], 50)
        # A different month doesn't include the bonus.
        self.assertEqual(instance_service.month_summary(self.fin, self.logic, "2026-11")["taxes_total"], 0)

    def test_inactive_and_deleted(self):
        irs = tax_service.add_rule(self.fin, "IRS", rate_pct=20)
        tax_service.set_income_taxes(self.fin, "recurring", self.salary, [irs])
        tax_service.set_active(self.fin, irs, False)
        self.assertEqual(self._month()["taxes_total"], 0)
        tax_service.set_active(self.fin, irs, True)
        self.assertEqual(self._month()["taxes_total"], 300)
        tax_service.delete_rule(self.fin, irs)
        self.assertEqual(tax_service.assignments(self.fin), {})

    def test_tax_never_exceeds_income(self):
        huge = tax_service.add_rule(self.fin, "Huge", rate_pct=100, fixed_monthly=500)
        tax_service.set_income_taxes(self.fin, "recurring", self.salary, [huge])
        self.assertEqual(self._month()["taxes_total"], 1500)

    def test_list_rules_shows_assigned_incomes(self):
        irs = tax_service.add_rule(self.fin, "IRS", rate_pct=13)
        tax_service.set_income_taxes(self.fin, "recurring", self.salary, [irs, 999])  # unknown ids ignored
        rule = tax_service.list_rules(self.fin)[0]
        self.assertEqual([i["name"] for i in rule["incomes"]], ["Salary"])
        self.assertEqual(tax_service.assignments(self.fin), {f"recurring:{self.salary}": [irs]})

    def test_investment_rate(self):
        tax_service.add_rule(self.fin, "CGT", rate_pct=28, on_investments=True)
        tax_service.add_rule(self.fin, "IRS", rate_pct=13)
        self.assertEqual(tax_service.investment_tax_rate(self.fin), 28)
        t = tax_service.apply_investment_tax(1000, 28)
        self.assertEqual((t["tax"], t["gains_after_tax"]), (280, 720))

    def test_long_range_accumulates_after_tax(self):
        irs = tax_service.add_rule(self.fin, "IRS", rate_pct=20)
        tax_service.set_income_taxes(self.fin, "recurring", self.salary, [irs])
        rows = instance_service.long_range(self.fin, self.logic, "2026-10", 3)
        self.assertEqual(rows[-1]["accumulated"], 3 * 1100)

    def test_validation(self):
        for args in (("", 10, 0), ("X", 0, 0), ("X", 101, 0), ("X", 5, -1)):
            with self.assertRaises(ValueError):
                tax_service.add_rule(self.fin, *args)
        with self.assertRaises(ValueError):
            tax_service.add_rule(self.fin, "X", 0, 10, on_investments=True)

    def test_legacy_category_rules_are_migrated_to_links(self):
        bonus = instance_service.add_oneoff(self.fin, "2026-10-05", "Bonus", 500, txn_type="income")["id"]
        conn = sqlite3.connect(self.fin)
        conn.execute(
            "CREATE TABLE tax_rules (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, applies_to TEXT NOT NULL DEFAULT 'salary', "
            "rate_pct REAL NOT NULL DEFAULT 0, fixed_monthly REAL NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1, "
            "note TEXT NOT NULL DEFAULT '', created_at TEXT, updated_at TEXT)"
        )
        conn.executemany(
            "INSERT INTO tax_rules (name, applies_to, rate_pct) VALUES (?, ?, ?)",
            [("IRS", "salary", 10), ("Bonus tax", "oneoff_income", 20), ("CGT", "investments", 28)],
        )
        conn.commit()
        conn.close()
        rules = {r["name"]: r for r in tax_service.list_rules(self.fin)}
        self.assertEqual({i["name"] for i in rules["IRS"]["incomes"]}, {"Salary", "Side gig"})
        self.assertEqual([i["id"] for i in rules["Bonus tax"]["incomes"]], [bonus])
        self.assertTrue(rules["CGT"]["on_investments"])
        self.assertEqual(rules["CGT"]["incomes"], [])
        # Same totals as before the migration: 10% of 2000 + 20% of the 500 bonus.
        self.assertEqual(self._month()["taxes_total"], 300)


if __name__ == "__main__":
    unittest.main()
