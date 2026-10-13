"""Entry editing, username invitations, notifications, workspace isolation, compound growth,
dashboard category breakdown and export naming."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import DatabaseInstance, Notification, User, WorkspaceInvite
from app.services import (
    category_breakdown_service,
    export_naming,
    instance_service,
    notification_service,
    projection_finance,
    workspace_service,
)


class _DbCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        engine = create_engine(f"sqlite:///{self.tmp}/app.db")
        Base.metadata.create_all(bind=engine)
        self.db = sessionmaker(bind=engine)()
        self.alice = self._user("alice")
        self.bob = self._user("bob")

    def tearDown(self):
        self.db.close()

    def _user(self, name: str) -> User:
        u = User(username=name, password_hash="x")
        self.db.add(u)
        self.db.commit()
        self.db.refresh(u)
        return u

    def _workspace(self, owner: User, name: str, currency: str = "EUR") -> DatabaseInstance:
        fin = os.path.join(self.tmp, f"{name}_financas.db")
        logic = os.path.join(self.tmp, f"{name}_logic.db")
        instance_service.init_finance_db(fin)
        instance_service.init_logic_db(logic)
        inst = DatabaseInstance(
            owner_id=owner.id, name=name, mode="general", currency=currency, finance_db_path=fin, logic_db_path=logic
        )
        self.db.add(inst)
        self.db.commit()
        self.db.refresh(inst)
        workspace_service.add_owner_member(self.db, inst.id, owner.id)
        self.db.commit()
        return inst


class TestEntryEditing(_DbCase):
    def setUp(self):
        super().setUp()
        self.ws = self._workspace(self.alice, "Personal")
        self.fin = self.ws.finance_db_path
        self.month = "2026-09"

    def _summary(self, month=None):
        return instance_service.month_summary(self.fin, self.ws.logic_db_path, month or self.month)

    def test_edit_income_updates_totals_in_place(self):
        row = instance_service.add_income(self.fin, "Salary", 2000.0)
        instance_service.update_income(self.fin, row["id"], nome="Salary (raise)", valor=2500.0)
        items = instance_service.list_finance_items(self.fin)
        self.assertEqual(len(items["incomes"]), 1, "editing must not create duplicates")
        self.assertEqual(items["incomes"][0]["id"], row["id"])
        self.assertEqual(items["incomes"][0]["name"], "Salary (raise)")
        self.assertAlmostEqual(self._summary()["extras"], 2500.0)

    def test_edit_expense_updates_category_and_type(self):
        row = instance_service.add_expense(self.fin, "Rent", 500.0, category="Housing")
        instance_service.add_income(self.fin, "Salary", 2000.0)
        instance_service.update_expense(
            self.fin, row["id"], nome="Rent", valor=600.0, category="Housing", expense_type="fixed"
        )
        exp = instance_service.list_finance_items(self.fin)["expenses"]
        self.assertEqual(len(exp), 1)
        self.assertEqual(exp[0]["expense_type"], "fixed")
        self.assertAlmostEqual(self._summary()["expenses"], 600.0)
        self.assertAlmostEqual(self._summary()["estimated_savings"], 1400.0)

    def test_edit_savings_deposit(self):
        instance_service.add_income(self.fin, "Salary", 1000.0)
        dep = instance_service.add_savings_deposit(self.fin, "2026-09-10", 100.0)
        instance_service.update_savings_deposit(self.fin, dep["id"], data="2026-09-11", valor=250.0, nome="Fund")
        s = self._summary()
        self.assertAlmostEqual(s["savings_deposits_month"], 250.0)
        self.assertAlmostEqual(s["available_balance"], 750.0)

    def test_edit_oneoff_moves_month_and_type(self):
        row = instance_service.add_oneoff(self.fin, "2026-09-03", "Groceries", 80.0, category="Food")
        instance_service.update_oneoff(
            self.fin, row["id"], data="2026-10-01", nome="Groceries", valor=95.0, txn_type="expense", category="Food"
        )
        self.assertAlmostEqual(self._summary("2026-09")["oneoff_expense_total"], 0.0)
        self.assertAlmostEqual(self._summary("2026-10")["oneoff_expense_total"], 95.0)
        self.assertEqual(len(instance_service.list_finance_items(self.fin)["oneoffs"]), 1)

    def test_edit_persists_across_reads(self):
        row = instance_service.add_expense(self.fin, "Gym", 30.0, category="Health")
        instance_service.update_expense(self.fin, row["id"], nome="Gym", valor=35.0, category="Health")
        fresh = instance_service.get_entry(self.fin, "expense", row["id"])
        self.assertAlmostEqual(fresh["amount"], 35.0)

    def test_invalid_values_rejected(self):
        row = instance_service.add_income(self.fin, "Salary", 1000.0)
        with self.assertRaises(ValueError):
            instance_service.update_income(self.fin, row["id"], nome="Salary", valor=0)
        with self.assertRaises(ValueError):
            instance_service.update_income(self.fin, row["id"], nome="Salary", valor=-3)
        with self.assertRaises(ValueError):
            instance_service.update_income(
                self.fin, row["id"], nome="Salary", valor=10, start_date="2026-05-01", end_date="2026-01-01"
            )
        o = instance_service.add_oneoff(self.fin, "2026-09-03", "X", 5.0, category="Food")
        with self.assertRaises(ValueError):
            instance_service.update_oneoff(self.fin, o["id"], data="2026-13-45", nome="X", valor=5, category="Food")
        self.assertAlmostEqual(instance_service.list_finance_items(self.fin)["incomes"][0]["amount"], 1000.0)

    def test_recurring_window_updates_future_projection(self):
        row = instance_service.add_expense(self.fin, "Car loan", 200.0, category="Transport")
        rows = instance_service.long_range(self.fin, self.ws.logic_db_path, "2026-09", 4)
        self.assertEqual([r["expenses"] for r in rows], [200.0] * 4)
        instance_service.update_expense(
            self.fin, row["id"], nome="Car loan", valor=200.0, category="Transport", end_date="2026-10-31"
        )
        rows = instance_service.long_range(self.fin, self.ws.logic_db_path, "2026-09", 4)
        self.assertEqual([r["expenses"] for r in rows], [200.0, 200.0, 0.0, 0.0])

    def test_move_entry_between_workspaces_without_duplicates(self):
        other = self._workspace(self.alice, "Household")
        row = instance_service.add_expense(self.fin, "Internet", 40.0, category="Subscriptions")
        instance_service.move_entry(self.fin, other.finance_db_path, "expense", row["id"])
        self.assertEqual(instance_service.list_finance_items(self.fin)["expenses"], [])
        moved = instance_service.list_finance_items(other.finance_db_path)["expenses"]
        self.assertEqual(len(moved), 1)
        self.assertEqual(moved[0]["name"], "Internet")

    def test_missing_entry_returns_none(self):
        self.assertIsNone(instance_service.update_income(self.fin, 999, nome="x", valor=1))


class TestInvitations(_DbCase):
    def setUp(self):
        super().setUp()
        self.ws = self._workspace(self.alice, "Household Finances")

    def test_invite_accept_creates_shared_membership(self):
        inv = workspace_service.create_username_invite(self.db, self.ws.id, "bob", "member", self.alice)
        self.db.commit()
        self.assertEqual(inv.invitee_user_id, self.bob.id)
        self.assertEqual(notification_service.unread_count(self.db, self.bob), 1)
        inst = workspace_service.respond_to_invite(self.db, self.bob, inv.id, accept=True)
        self.db.commit()
        self.assertEqual(inst.id, self.ws.id)
        self.assertEqual(workspace_service.get_membership(self.db, self.bob.id, self.ws.id).role, "member")
        # Same workspace record -> same finance file: one source of truth.
        visible = workspace_service.list_user_workspaces(self.db, self.bob)
        self.assertEqual([w.finance_db_path for w in visible], [self.ws.finance_db_path])
        kinds = [n.kind for n in notification_service.list_for_user(self.db, self.alice)]
        self.assertIn(notification_service.KIND_INVITE_ACCEPTED, kinds)

    def test_shared_data_visible_to_both(self):
        inv = workspace_service.create_username_invite(self.db, self.ws.id, "bob", "member", self.alice)
        workspace_service.respond_to_invite(self.db, self.bob, inv.id, accept=True)
        self.db.commit()
        row = instance_service.add_expense(self.ws.finance_db_path, "Groceries", 500.0, category="Food")
        bob_ws, _ = workspace_service.require_workspace(self.db, self.bob, self.ws.id, "edit")
        instance_service.update_expense(bob_ws.finance_db_path, row["id"], nome="Groceries", valor=600.0, category="Food")
        alice_ws, _ = workspace_service.require_workspace(self.db, self.alice, self.ws.id, "read")
        self.assertAlmostEqual(instance_service.list_finance_items(alice_ws.finance_db_path)["expenses"][0]["amount"], 600.0)

    def test_decline(self):
        inv = workspace_service.create_username_invite(self.db, self.ws.id, "bob", "member", self.alice)
        workspace_service.respond_to_invite(self.db, self.bob, inv.id, accept=False)
        self.db.commit()
        self.assertIsNone(workspace_service.get_membership(self.db, self.bob.id, self.ws.id))
        self.assertEqual(self.db.get(WorkspaceInvite, inv.id).status, "declined")
        kinds = [n.kind for n in notification_service.list_for_user(self.db, self.alice)]
        self.assertIn(notification_service.KIND_INVITE_DECLINED, kinds)

    def test_validation_errors(self):
        with self.assertRaises(HTTPException) as ctx:
            workspace_service.create_username_invite(self.db, self.ws.id, "nobody", "member", self.alice)
        self.assertEqual(ctx.exception.status_code, 404)
        with self.assertRaises(HTTPException):
            workspace_service.create_username_invite(self.db, self.ws.id, "alice", "member", self.alice)
        inv = workspace_service.create_username_invite(self.db, self.ws.id, "bob", "member", self.alice)
        self.db.commit()
        with self.assertRaises(HTTPException) as dup:
            workspace_service.create_username_invite(self.db, self.ws.id, "bob", "member", self.alice)
        self.assertEqual(dup.exception.status_code, 409)
        workspace_service.respond_to_invite(self.db, self.bob, inv.id, accept=True)
        self.db.commit()
        with self.assertRaises(HTTPException):
            workspace_service.respond_to_invite(self.db, self.bob, inv.id, accept=True)
        with self.assertRaises(HTTPException):
            workspace_service.create_username_invite(self.db, self.ws.id, "bob", "member", self.alice)

    def test_only_invitee_can_respond_and_members_cannot_invite(self):
        carol = self._user("carol")
        inv = workspace_service.create_username_invite(self.db, self.ws.id, "bob", "member", self.alice)
        self.db.commit()
        with self.assertRaises(HTTPException):
            workspace_service.respond_to_invite(self.db, carol, inv.id, accept=True)
        workspace_service.respond_to_invite(self.db, self.bob, inv.id, accept=True)
        self.db.commit()
        with self.assertRaises(HTTPException) as ctx:
            workspace_service.create_username_invite(self.db, self.ws.id, "carol", "member", self.bob)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_unauthorized_access_blocked_and_member_limits(self):
        with self.assertRaises(HTTPException):
            workspace_service.require_workspace(self.db, self.bob, self.ws.id, "read")
        inv = workspace_service.create_username_invite(self.db, self.ws.id, "bob", "member", self.alice)
        workspace_service.respond_to_invite(self.db, self.bob, inv.id, accept=True)
        self.db.commit()
        with self.assertRaises(HTTPException):
            workspace_service.require_workspace(self.db, self.bob, self.ws.id, "delete_workspace")
        with self.assertRaises(HTTPException):
            workspace_service.remove_member(self.db, self.ws.id, self.alice.id, self.bob)

    def test_remove_member_notifies(self):
        inv = workspace_service.create_username_invite(self.db, self.ws.id, "bob", "member", self.alice)
        workspace_service.respond_to_invite(self.db, self.bob, inv.id, accept=True)
        self.db.commit()
        workspace_service.remove_member(self.db, self.ws.id, self.bob.id, self.alice)
        self.assertIsNone(workspace_service.get_membership(self.db, self.bob.id, self.ws.id))
        kinds = [n.kind for n in notification_service.list_for_user(self.db, self.bob)]
        self.assertIn(notification_service.KIND_MEMBER_REMOVED, kinds)

    def test_notifications_persist_and_mark_read(self):
        workspace_service.create_username_invite(self.db, self.ws.id, "bob", "member", self.alice)
        self.db.commit()
        self.db.expire_all()
        rows = notification_service.list_for_user(self.db, self.bob)
        self.assertEqual(len(rows), 1)
        self.assertTrue(notification_service.serialize(self.db, rows[0])["actionable"])
        notification_service.mark_read(self.db, self.bob, rows[0].id)
        self.db.commit()
        self.assertEqual(notification_service.unread_count(self.db, self.bob), 0)
        self.assertEqual(self.db.query(Notification).count(), 1)


class TestWorkspaceIsolation(_DbCase):
    def test_currency_workspaces_keep_separate_totals(self):
        eur = self._workspace(self.alice, "Portugal", "EUR")
        usd = self._workspace(self.alice, "United States", "USD")
        instance_service.add_income(eur.finance_db_path, "Salary", 2500.0)
        instance_service.add_expense(eur.finance_db_path, "Rent", 1700.0, category="Housing")
        instance_service.add_income(usd.finance_db_path, "Salary", 4000.0)
        instance_service.add_expense(usd.finance_db_path, "Rent", 2800.0, category="Housing")
        m = "2026-09"
        se = instance_service.month_summary(eur.finance_db_path, eur.logic_db_path, m)
        su = instance_service.month_summary(usd.finance_db_path, usd.logic_db_path, m)
        self.assertEqual((se["extras"], se["expenses"]), (2500.0, 1700.0))
        self.assertEqual((su["extras"], su["expenses"]), (4000.0, 2800.0))
        self.assertEqual(eur.currency, "EUR")
        self.assertEqual(usd.currency, "USD")
        be = category_breakdown_service.build_category_breakdown(eur.finance_db_path, "this_month")
        bu = category_breakdown_service.build_category_breakdown(usd.finance_db_path, "this_month")
        self.assertAlmostEqual(be["total"], 1700.0)
        self.assertAlmostEqual(bu["total"], 2800.0)

    def test_non_member_cannot_read_other_users_workspace(self):
        ws = self._workspace(self.alice, "Private", "USD")
        with self.assertRaises(HTTPException):
            workspace_service.require_workspace(self.db, self.bob, ws.id, "read")
        self.assertEqual(workspace_service.list_user_workspaces(self.db, self.bob), [])


class TestCompoundGrowth(unittest.TestCase):
    def calc(self, **kw):
        base = dict(initial_balance=1000.0, monthly_contribution=250.0, annual_rate_pct=7.0, years=10,
                    compounding_per_year=0, contribution_timing="end")
        base.update(kw)
        return projection_finance.run_investment_calculator(**base)

    def test_zero_interest(self):
        s = self.calc(annual_rate_pct=0)["summary"]
        self.assertEqual(s["total_contributions"], 31000.0)
        self.assertEqual(s["compound_growth"], 0.0)
        self.assertEqual(s["final_balance"], 31000.0)

    def test_positive_interest_matches_closed_form(self):
        r = (1.07) ** (1 / 12) - 1
        n = 120
        expected = 1000 * (1 + r) ** n + 250 * (((1 + r) ** n - 1) / r)
        s = self.calc()["summary"]
        self.assertAlmostEqual(s["final_balance"], round(expected, 2), places=2)
        self.assertGreater(s["compound_growth"], 0)

    def test_beginning_timing_grows_more(self):
        end = self.calc()["summary"]["final_balance"]
        beg = self.calc(contribution_timing="beginning")["summary"]["final_balance"]
        self.assertGreater(beg, end)

    def test_negative_return(self):
        s = self.calc(monthly_contribution=0, annual_rate_pct=-10, years=2)["summary"]
        self.assertAlmostEqual(s["final_balance"], 810.0, places=2)
        self.assertAlmostEqual(s["compound_growth"], -190.0, places=2)

    def test_zero_monthly_contribution(self):
        s = self.calc(monthly_contribution=0)["summary"]
        self.assertEqual(s["total_contributions"], 1000.0)
        self.assertAlmostEqual(s["final_balance"], round(1000 * 1.07 ** 10, 2), places=2)

    def test_contribution_change_recalculates(self):
        a = self.calc(monthly_contribution=250)["summary"]["final_balance"]
        b = self.calc(monthly_contribution=300)["summary"]["final_balance"]
        self.assertGreater(b, a)

    def test_final_balance_reconciles_every_month(self):
        res = self.calc(years=0.5)
        ser = res["series"]
        for c, g, b in zip(ser["cumulative_contributed"], ser["interest_earned"], ser["balance"]):
            self.assertAlmostEqual(c + g, b, places=9)
        s = res["summary"]
        self.assertEqual(round(s["total_contributions"] + s["compound_growth"], 2), s["final_balance"])
        self.assertEqual(len(ser["balance"]), 6)

    def test_projection_linked_simulation_with_initial_amount(self):
        rows = [{"month": f"2026-{m:02d}", "accumulated": 100.0 * m, "estimated_savings": 1000.0} for m in range(1, 13)]
        sim = projection_finance.run_monthly_simulation(
            rows, 10.0, 0.0, 1.0, initial_amount=500.0, contribution_timing="end"
        )
        self.assertAlmostEqual(sim["summary"]["final_cumulative_contributed"], 500.0 + 12 * 100.0)
        self.assertAlmostEqual(sim["summary"]["final_investment_balance"], 1700.0)
        self.assertAlmostEqual(sim["summary"]["final_compounded_profit"], 0.0)


class TestCategoryBreakdown(unittest.TestCase):
    def setUp(self):
        self.fin = os.path.join(tempfile.mkdtemp(), "b_financas.db")
        instance_service.init_finance_db(self.fin)
        self.today = date(2026, 10, 12)

    def test_totals_shares_and_fixed_variable(self):
        instance_service.add_expense(self.fin, "Rent", 850.0, category="Housing", expense_type="fixed")
        instance_service.add_oneoff(self.fin, "2026-10-02", "Market", 400.0, category="Food", expense_type="variable")
        instance_service.add_oneoff(self.fin, "2026-10-03", "Cinema", 150.0, category="Entertainment")
        instance_service.add_oneoff(self.fin, "2026-10-04", "Refund", 999.0, txn_type="income")
        b = category_breakdown_service.build_category_breakdown(self.fin, "this_month", today=self.today)
        self.assertAlmostEqual(b["total"], 1400.0)
        self.assertEqual([c["category"] for c in b["categories"]], ["Housing", "Food", "Entertainment"])
        self.assertAlmostEqual(sum(c["share_pct"] for c in b["categories"]), 100.0)
        fv = {t["type"]: t["total"] for t in b["fixed_variable"]}
        self.assertEqual(fv, {"fixed": 850.0, "variable": 400.0, "unclassified": 150.0})

    def test_time_ranges(self):
        instance_service.add_expense(self.fin, "Phone", 20.0, category="Subscriptions", start_date="2026-08-01")
        instance_service.add_oneoff(self.fin, "2026-09-15", "Shoes", 60.0, category="Shopping")
        tm = category_breakdown_service.build_category_breakdown(self.fin, "this_month", today=self.today)
        lm = category_breakdown_service.build_category_breakdown(self.fin, "last_month", today=self.today)
        q3 = category_breakdown_service.build_category_breakdown(self.fin, "3_months", today=self.today)
        al = category_breakdown_service.build_category_breakdown(self.fin, "all", today=self.today)
        self.assertAlmostEqual(tm["total"], 20.0)
        self.assertAlmostEqual(lm["total"], 80.0)
        self.assertAlmostEqual(q3["total"], 20.0 * 3 + 60.0)
        self.assertEqual(al["months"], ["2026-08", "2026-09", "2026-10"])

    def test_edit_updates_breakdown_and_empty_state(self):
        empty = category_breakdown_service.build_category_breakdown(self.fin, "this_month", today=self.today)
        self.assertEqual(empty["categories"], [])
        self.assertEqual(empty["total"], 0)
        row = instance_service.add_oneoff(self.fin, "2026-10-02", "Fuel", 50.0, category="Transport")
        instance_service.update_oneoff(self.fin, row["id"], data="2026-10-02", nome="Fuel", valor=70.0, category="Health")
        b = category_breakdown_service.build_category_breakdown(self.fin, "this_month", today=self.today)
        self.assertEqual([(c["category"], c["total"]) for c in b["categories"]], [("Health", 70.0)])


class TestExportNaming(unittest.TestCase):
    def test_full_convention(self):
        name = export_naming.build_filename(
            "Expenses", "csv", workspace_name="Personal", currency="EUR", start=date(2026, 1, 1), end=date(2026, 9, 30)
        )
        self.assertEqual(name, "Webable_Personal-EUR_Expenses_2026-01-01_to_2026-09-30.csv")

    def test_month_and_single_day(self):
        self.assertEqual(
            export_naming.build_filename("Monthly Report", ".PDF", workspace_name="Personal", currency="usd", month="2026-09"),
            "Webable_Personal-USD_Monthly-Report_2026-09.pdf",
        )
        self.assertEqual(
            export_naming.build_filename("Investment Projection", "csv", on=date(2026, 10, 12)),
            "Webable_Investment-Projection_2026-10-12.csv",
        )

    def test_sanitizes_and_limits_length(self):
        name = export_naming.build_filename(
            "Report", "pdf", workspace_name='Família / "Casa" <€> ' + "x" * 200, currency="EUR", on="2026-10-12"
        )
        self.assertTrue(name.endswith(".pdf"))
        for ch in '/\\:*?"<> ':
            self.assertNotIn(ch, name)
        self.assertTrue(name.startswith("Webable_Familia-Casa-"))
        self.assertLessEqual(len(name), export_naming.MAX_FILENAME_LEN)
        self.assertIn("-EUR_Report_2026-10-12", name)


if __name__ == "__main__":
    unittest.main()
