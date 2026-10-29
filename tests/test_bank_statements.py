import tempfile
import unittest
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import DatabaseInstance, User
from app.services import bank_statement_service


class TestBankStatementValidation(unittest.TestCase):
    def test_rejects_non_pdf(self):
        ok, msg = bank_statement_service.validate_pdf_bytes(b"hello world")
        self.assertFalse(ok)

    def test_accepts_minimal_pdf(self):
        body = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
        ok, msg = bank_statement_service.validate_pdf_bytes(body)
        self.assertTrue(ok)

    def test_rejects_oversize(self):
        orig = bank_statement_service.MAX_FILE_BYTES
        try:
            bank_statement_service.MAX_FILE_BYTES = 50
            ok, _ = bank_statement_service.validate_pdf_bytes(b"%PDF" + b"x" * 80)
            self.assertFalse(ok)
        finally:
            bank_statement_service.MAX_FILE_BYTES = orig

    def test_sanitize_filename(self):
        self.assertTrue(bank_statement_service.sanitize_original_filename("../../etc/passwd").endswith(".pdf"))


class TestStatementPeriodDetection(unittest.TestCase):
    detect = staticmethod(bank_statement_service.detect_statement_period)

    def test_credito_agricola_period_uses_covered_month_not_issue_month(self):
        text = "EXTRACTO Nº 009/2026 - Período de 01-09-2026 a 30-09-2026, respeitante à Conta D.O. DATA EMISSÃO: 01-10-2026"
        d = self.detect(text)
        self.assertEqual(d["month"], "2026-09")
        self.assertEqual((d["start"], d["end"]), (date(2026, 9, 1), date(2026, 9, 30)))

    def test_other_formats(self):
        self.assertEqual(self.detect("Statement period: 01/08/2026 - 31/08/2026")["month"], "2026-08")
        self.assertEqual(self.detect("Period from 2026-07-01 to 2026-07-31")["month"], "2026-07")
        self.assertEqual(self.detect("Periodo: 01.06.2026 a 30.06.2026")["month"], "2026-06")

    def test_cross_month_period_picks_majority_month(self):
        self.assertEqual(self.detect("Período de 25-08-2026 a 24-09-2026")["month"], "2026-09")
        self.assertEqual(self.detect("Período de 05-08-2026 a 04-09-2026")["month"], "2026-08")

    def test_no_period(self):
        self.assertIsNone(self.detect("Saldo disponível 22,02"))
        self.assertIsNone(self.detect(None))
        self.assertIsNone(self.detect("Período de 01-01-2020 a 31-12-2026"))  # not a monthly statement


class TestSaveStatementMonth(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        engine = create_engine(f"sqlite:///{self.root}/app.db")
        Base.metadata.create_all(bind=engine)
        self.db = sessionmaker(bind=engine)()
        user = User(username="u", password_hash="x")
        self.db.add(user)
        self.db.commit()
        self.inst = DatabaseInstance(owner_id=user.id, name="w", finance_db_path="f", logic_db_path="l")
        self.db.add(self.inst)
        self.db.commit()
        self.user = user

    def _save(self, month, text):
        orig = bank_statement_service.optional_text_excerpt
        bank_statement_service.optional_text_excerpt = lambda content, max_chars=8000: text
        try:
            body = b"%PDF-1.4\n" + text.encode() + b"\n%%EOF"
            return bank_statement_service.save_statement(
                self.db, self.root, self.inst, self.user.id,
                content=body, original_filename=f"s{month}{len(text)}.pdf", statement_month=month, bank_name=None,
            )
        finally:
            bank_statement_service.optional_text_excerpt = orig

    def test_pdf_period_overrides_typed_month(self):
        row, err = self._save("2026-10", "Período de 01-09-2026 a 30-09-2026")
        self.assertIsNone(err)
        self.assertEqual(row.statement_month, "2026-09")
        self.assertTrue(row.detection["corrected"])

    def test_month_optional_when_detected(self):
        row, err = self._save("", "Período de 01-08-2026 a 31-08-2026")
        self.assertIsNone(err)
        self.assertEqual(row.statement_month, "2026-08")

    def test_typed_month_used_when_nothing_detected(self):
        row, _ = self._save("2026-05", "no period here")
        self.assertEqual(row.statement_month, "2026-05")
        self.assertFalse(row.detection["detected"])
        _, err = self._save("", "still nothing")
        self.assertIn("pick the month", err)


if __name__ == "__main__":
    unittest.main()
