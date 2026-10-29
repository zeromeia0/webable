"""Tests for shared workspace copies: income summing, optional expenses, combined savings expenses."""

import os
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import DatabaseInstance, User
from app.services import instance_service, shared_workspace_service, workspace_service


class TestSharedWorkspace(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        engine = create_engine(f"sqlite:///{self.tmp}/app.db")
        Base.metadata.create_all(bind=engine)
        self.db = sessionmaker(bind=engine)()
        self.alice = self._user("alice")
        self.bob = self._user("bob")
        self.alice_ws = self._workspace(self.alice, "Alice home")
        self.bob_ws = self._workspace(self.bob, "Bob home")

        instance_service.add_income(self.alice_ws.finance_db_path, "Salary", 2000.0)
        instance_service.add_expense(self.alice_ws.finance_db_path, "Rent", 800.0, category="Housing")
        instance_service.add_income(self.bob_ws.finance_db_path, "Salary", 1500.0)
        instance_service.add_expense(self.bob_ws.finance_db_path, "Gym", 40.0, category="Health")

    def tearDown(self):
        self.db.close()

    def _user(self, name):
        u = User(username=name, password_hash="x")
        self.db.add(u)
        self.db.commit()
        return u

    def _workspace(self, user, name):
        fin = os.path.join(self.tmp, f"{name}_fin.db")
        logic = os.path.join(self.tmp, f"{name}_logic.db")
        instance_service.init_finance_db(fin)
        instance_service.init_logic_db(logic)
        inst = DatabaseInstance(owner_id=user.id, name=name, finance_db_path=fin, logic_db_path=logic)
        self.db.add(inst)
        self.db.commit()
        workspace_service.add_owner_member(self.db, inst.id, user.id)
        self.db.commit()
        return inst

    def _invite_and_accept(self):
        invite = workspace_service.create_username_invite(
            self.db, self.alice_ws.id, "bob", "member", self.alice, root=self.root
        )
        self.db.commit()
        shared = self.db.query(DatabaseInstance).filter(DatabaseInstance.id == invite.workspace_id).one()
        workspace_service.respond_to_invite(self.db, self.bob, invite.id, accept=True)
        self.db.commit()
        return invite, shared

    def _items(self, inst):
        return instance_service.list_finance_items(inst.finance_db_path)

    def test_invite_creates_shared_copy_and_keeps_personal_private(self):
        invite, shared = self._invite_and_accept()
        self.assertNotEqual(invite.workspace_id, self.alice_ws.id)
        self.assertEqual(shared.kind, "shared")
        self.assertEqual(shared.source_workspace_id, self.alice_ws.id)
        self.assertIsNone(workspace_service.get_membership(self.db, self.bob.id, self.alice_ws.id))
        self.assertIsNotNone(workspace_service.get_membership(self.db, self.bob.id, shared.id))
        # A second invite reuses the same copy.
        carol = self._user("carol")
        again = workspace_service.create_username_invite(self.db, self.alice_ws.id, carol.username, "member", self.alice, root=self.root)
        self.assertEqual(again.workspace_id, shared.id)

    def test_incomes_are_summed_and_read_only(self):
        _invite, shared = self._invite_and_accept()
        incomes = self._items(shared)["incomes"]
        self.assertEqual(sorted(i["amount"] for i in incomes), [1500.0, 2000.0])
        self.assertTrue(all(i["linked_source"] for i in incomes))
        self.assertIsNone(instance_service.delete_income(shared.finance_db_path, incomes[0]["id"]))
        self.assertIsNone(
            instance_service.update_income(shared.finance_db_path, incomes[0]["id"], nome="x", valor=1.0)
        )
        summary = instance_service.month_summary(shared.finance_db_path, shared.logic_db_path, "2026-10")
        self.assertEqual(summary["extras"], 3500.0)

    def test_income_changes_propagate(self):
        _invite, shared = self._invite_and_accept()
        bob_salary = self._items(self.bob_ws)["incomes"][0]
        instance_service.update_income(self.bob_ws.finance_db_path, bob_salary["id"], nome="Salary", valor=1600.0)
        shared_workspace_service.sync_shared_workspace(self.db, shared)
        self.assertEqual(sorted(i["amount"] for i in self._items(shared)["incomes"]), [1600.0, 2000.0])
        # Unlinking removes the member's income.
        shared_workspace_service.set_member_link(self.db, shared, self.bob, None)
        shared_workspace_service.sync_shared_workspace(self.db, shared)
        self.assertEqual([i["amount"] for i in self._items(shared)["incomes"]], [2000.0])

    def test_expenses_only_included_when_enabled(self):
        _invite, shared = self._invite_and_accept()
        # Copied from Alice's workspace; Bob's are not included by default.
        self.assertEqual([e["name"] for e in self._items(shared)["expenses"]], ["Rent"])
        shared.include_member_expenses = True
        self.db.commit()
        shared_workspace_service.sync_shared_workspace(self.db, shared)
        names = sorted(e["name"] for e in self._items(shared)["expenses"])
        self.assertEqual(names, ["Rent", "bob · Gym"])  # Alice's not duplicated
        shared.include_member_expenses = False
        self.db.commit()
        shared_workspace_service.sync_shared_workspace(self.db, shared)
        self.assertEqual([e["name"] for e in self._items(shared)["expenses"]], ["Rent"])

    def test_savings_saved_expenses_combine_members(self):
        _invite, shared = self._invite_and_accept()
        instance_service.add_expense(shared.finance_db_path, "Groceries", 300.0, category="Food")
        summary = shared_workspace_service.combined_saved_expenses(self.db, shared)
        self.assertTrue(summary["shared"])
        self.assertEqual(summary["monthly_total"], 800.0 + 300.0 + 40.0)
        # Same totals with mirroring on: nothing is counted twice.
        shared.include_member_expenses = True
        self.db.commit()
        shared_workspace_service.sync_shared_workspace(self.db, shared)
        again = shared_workspace_service.combined_saved_expenses(self.db, shared)
        self.assertEqual(again["monthly_total"], summary["monthly_total"])

    def test_shared_workspaces_only_listed_separately(self):
        _invite, shared = self._invite_and_accept()
        for user in (self.alice, self.bob):
            listed = workspace_service.list_user_workspaces(self.db, user)
            self.assertNotIn(shared.id, [w.id for w in listed])
            self.assertEqual([w.id for w in workspace_service.list_shared_workspaces(self.db, user)], [shared.id])
        # Even if the shared workspace was last active, the dashboard falls back to a personal one.
        self.bob.active_workspace_id = shared.id
        self.db.commit()
        _instances, active = workspace_service.resolve_active_workspace(self.db, self.bob)
        self.assertEqual(active.id, self.bob_ws.id)

    def test_only_owner_can_share_personal_workspace(self):
        _invite, shared = self._invite_and_accept()
        carol = self._user("carol")
        with self.assertRaises(Exception):
            workspace_service.create_username_invite(self.db, shared.id, carol.username, "member", self.bob, root=self.root)


if __name__ == "__main__":
    unittest.main()
