"""Tests for sequential backup folder naming."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.services import db_safety


class TestBackupNaming(unittest.TestCase):
    def test_sequential_ids_same_day(self):
        tmp = tempfile.TemporaryDirectory()
        parent = Path(tmp.name)
        d1 = db_safety.next_backup_destination(parent, date_str="20260518")
        self.assertEqual(d1.name, "webable-data-backup-20260518-001")
        d1.mkdir()
        d2 = db_safety.next_backup_destination(parent, date_str="20260518")
        self.assertEqual(d2.name, "webable-data-backup-20260518-002")
        tmp.cleanup()

    def test_backup_uses_new_format(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name) / "data"
        root.mkdir()
        dest = db_safety.backup_data_directory(root)
        self.assertRegex(dest.name, r"^webable-data-backup-\d{8}-\d{3}$")
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
