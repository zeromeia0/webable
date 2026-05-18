"""Tests for safe backup and migration helpers."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from app.services import db_safety, instance_service


class TestDbSafety(unittest.TestCase):
    def test_backup_copies_sqlite_without_deleting_source(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name) / "data"
        root.mkdir()
        finance = root / "user_1" / "1_test_financas.db"
        finance.parent.mkdir(parents=True)
        instance_service.init_finance_db(str(finance))
        instance_service.add_income(str(finance), "Job", 100.0)

        dest = db_safety.backup_data_directory(root)
        self.assertRegex(dest.name, r"^webable-data-backup-\d{8}-\d{3}$")
        self.assertTrue((dest / "user_1" / "1_test_financas.db").is_file())
        self.assertTrue(finance.is_file())
        items = instance_service.list_finance_items(str(finance))
        self.assertEqual(len(items["incomes"]), 1)
        tmp.cleanup()

    def test_migrate_workspace_adds_columns_idempotent(self):
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "legacy.db")
        instance_service.init_finance_db(path)
        db_safety.migrate_workspace_sqlite(path)
        db_safety.migrate_workspace_sqlite(path)
        instance_service.add_oneoff(path, "2026-01-01", "Coffee", 3.5, txn_type="expense", category="Food")
        items = instance_service.list_finance_items(path)
        self.assertEqual(len(items["oneoffs"]), 1)
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
