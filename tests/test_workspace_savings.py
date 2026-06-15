"""Tests for workspace membership, savings balances, and import/export."""

import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import DatabaseInstance, User, WorkspaceMember
from app.services import instance_service, workspace_export_service, workspace_service


class TestWorkspaceAndSavings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.engine = create_engine(f"sqlite:///{self.tmp}/test.db")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.user = User(username="alice@test.com", password_hash="x")
        self.db.add(self.user)
        self.db.commit()
        self.db.refresh(self.user)

        fin = os.path.join(self.tmp, "fin.db")
        logic = os.path.join(self.tmp, "logic.db")
        instance_service.init_finance_db(fin)
        instance_service.init_logic_db(logic)
        self.inst = DatabaseInstance(
            owner_id=self.user.id,
            name="Personal",
            mode="general",
            finance_db_path=fin,
            logic_db_path=logic,
        )
        self.db.add(self.inst)
        self.db.commit()
        self.db.refresh(self.inst)
        workspace_service.add_owner_member(self.db, self.inst.id, self.user.id)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_role_permissions(self):
        self.assertTrue(workspace_service.role_allows("owner", "delete_workspace"))
        self.assertTrue(workspace_service.role_allows("admin", "import"))
        self.assertFalse(workspace_service.role_allows("member", "import"))
        self.assertTrue(workspace_service.role_allows("member", "export"))
        self.assertFalse(workspace_service.role_allows("viewer", "delete"))

    def test_savings_reduce_available_balance(self):
        month = "2026-06"
        instance_service.add_income(self.inst.finance_db_path, "Salary", 1000.0)
        instance_service.add_savings_deposit(self.inst.finance_db_path, "2026-06-10", 200.0)
        summary = instance_service.month_summary(
            self.inst.finance_db_path, self.inst.logic_db_path, month
        )
        self.assertAlmostEqual(summary["estimated_savings"], 1000.0)
        self.assertAlmostEqual(summary["savings_total"], 200.0)
        self.assertAlmostEqual(summary["available_balance"], 800.0)

    def test_soft_delete_savings_restores_available(self):
        month = "2026-06"
        instance_service.add_income(self.inst.finance_db_path, "Salary", 1000.0)
        dep = instance_service.add_savings_deposit(self.inst.finance_db_path, "2026-06-10", 200.0)
        instance_service.delete_savings_deposit(self.inst.finance_db_path, dep["id"], deleted_by=1)
        summary = instance_service.month_summary(
            self.inst.finance_db_path, self.inst.logic_db_path, month
        )
        self.assertAlmostEqual(summary["savings_total"], 0.0)
        self.assertAlmostEqual(summary["available_balance"], 1000.0)

    def test_export_import_roundtrip(self):
        instance_service.add_income(self.inst.finance_db_path, "Salary", 500.0)
        instance_service.add_oneoff(
            self.inst.finance_db_path, "2026-06-01", "Groceries", 50.0, txn_type="expense", category="Food"
        )
        zip_bytes = workspace_export_service.build_export_zip(self.db, self.inst)
        validated = workspace_export_service.validate_import_zip(zip_bytes)
        self.assertEqual(validated["preview"]["income_entries"], 1)
        self.assertEqual(validated["preview"]["transactions"], 1)

        user2 = User(username="bob@test.com", password_hash="x")
        self.db.add(user2)
        self.db.commit()
        new_inst = workspace_export_service.import_as_new_workspace(
            self.db, user2, Path(self.tmp), validated
        )
        items = instance_service.list_finance_items(new_inst.finance_db_path)
        self.assertEqual(len(items["incomes"]), 1)
        self.assertEqual(len(items["oneoffs"]), 1)
        member = workspace_service.get_membership(self.db, user2.id, new_inst.id)
        self.assertIsNotNone(member)
        self.assertEqual(member.role, "owner")

    def test_non_member_denied(self):
        from fastapi import HTTPException

        other = User(username="other@test.com", password_hash="x")
        self.db.add(other)
        self.db.commit()
        with self.assertRaises(HTTPException):
            workspace_service.require_workspace(self.db, other, self.inst.id, "read")


if __name__ == "__main__":
    unittest.main()
