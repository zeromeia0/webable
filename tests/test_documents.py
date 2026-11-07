import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import BankStatement, DatabaseInstance, Document, User
from app.services import bank_statement_service, document_service


def _pdf(tag: str) -> bytes:
    return b"%PDF-1.4\n" + tag.encode() + b"\n%%EOF"


class _DbCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        engine = create_engine(f"sqlite:///{self.root}/app.db")
        Base.metadata.create_all(bind=engine)
        self.db = sessionmaker(bind=engine)()
        self.user = User(username="u", password_hash="x")
        self.db.add(self.user)
        self.db.commit()
        self.inst = DatabaseInstance(owner_id=self.user.id, name="w", finance_db_path="f", logic_db_path="l")
        self.db.add(self.inst)
        self.db.commit()


class TestDisplayFilename(unittest.TestCase):
    clean = staticmethod(bank_statement_service.sanitize_display_filename)

    def test_keeps_spaces_and_accents_adds_pdf(self):
        self.assertEqual(self.clean("  Extrato Setembro  "), "Extrato Setembro.pdf")
        self.assertEqual(self.clean("Declaração IRS.PDF"), "Declaração IRS.pdf")

    def test_strips_path_and_reserved_chars(self):
        self.assertEqual(self.clean("../a/b"), "_a_b.pdf")
        self.assertEqual(self.clean('x:y*"z'), "x_y__z.pdf")

    def test_empty(self):
        self.assertIsNone(self.clean("   "))
        self.assertIsNone(self.clean(".pdf"))


class TestRenameStatement(_DbCase):
    def _stmt(self, name):
        row = BankStatement(
            instance_id=self.inst.id, owner_id=self.user.id, original_filename=name, stored_filename="s.pdf",
            statement_month="2026-09", file_size=1, sha256=name, storage_rel_path="statements/x/s.pdf",
        )
        self.db.add(row)
        self.db.commit()
        return row

    def test_rename_changes_only_name(self):
        row = self._stmt("a.pdf")
        self.assertIsNone(bank_statement_service.rename_statement(self.db, row, "Setembro 2026"))
        self.assertEqual(row.original_filename, "Setembro 2026.pdf")
        self.assertEqual(row.stored_filename, "s.pdf")
        self.assertEqual(row.storage_rel_path, "statements/x/s.pdf")

    def test_rename_rejects_clash_and_empty(self):
        self._stmt("a.pdf")
        row = self._stmt("b.pdf")
        self.assertIn("already", bank_statement_service.rename_statement(self.db, row, "a"))
        self.assertIsNotNone(bank_statement_service.rename_statement(self.db, row, "  "))
        self.assertEqual(row.original_filename, "b.pdf")


class TestDocuments(_DbCase):
    def test_category_create_rules(self):
        cat, err = document_service.create_category(self.db, self.inst.id, "  Tax   documents ")
        self.assertIsNone(err)
        self.assertEqual(cat.name, "Tax documents")
        self.assertIsNotNone(document_service.create_category(self.db, self.inst.id, "tax DOCUMENTS")[1])
        self.assertIsNotNone(document_service.create_category(self.db, self.inst.id, "")[1])
        self.assertIsNotNone(document_service.create_category(self.db, self.inst.id, "Bank statements")[1])

    def test_upload_duplicates_rename_and_delete(self):
        cat, _ = document_service.create_category(self.db, self.inst.id, "Reports")
        save = lambda content, name, month="": document_service.save_document(  # noqa: E731
            self.db, self.root, self.inst, cat, self.user.id,
            content=content, original_filename=name, doc_month=month, source=None,
        )
        row, err = save(_pdf("one"), "r1.pdf", "2026-03")
        self.assertIsNone(err)
        self.assertEqual(row.doc_month, "2026-03")
        stored = self.root / row.storage_rel_path
        self.assertTrue(stored.is_file())
        self.assertIn("same content", save(_pdf("one"), "other.pdf")[1])
        self.assertIn("same name", save(_pdf("two"), "r1.pdf")[1])
        self.assertIn("YYYY-MM", save(_pdf("three"), "r3.pdf", "march")[1])
        self.assertIsNotNone(save(b"not a pdf", "x.pdf")[1])

        before = stored.read_bytes()
        self.assertIsNone(document_service.rename_document(self.db, row, "Annual report"))
        self.assertEqual(row.original_filename, "Annual report.pdf")
        self.assertEqual(stored.read_bytes(), before)

        document_service.delete_category(self.db, self.root, cat)
        self.assertFalse(stored.exists())
        self.assertEqual(self.db.query(Document).count(), 0)


if __name__ == "__main__":
    unittest.main()
