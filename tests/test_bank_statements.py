import unittest

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


if __name__ == "__main__":
    unittest.main()
