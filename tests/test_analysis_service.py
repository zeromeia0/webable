"""analysis_service smoke tests."""

import os
import tempfile
import unittest

from app.services import analysis_service, instance_service


class TestAnalysisService(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.finance = os.path.join(self.tmp.name, "f.sqlite")
        self.logic = os.path.join(self.tmp.name, "l.sqlite")
        import sqlite3

        lc = sqlite3.connect(self.logic)
        lc.execute("CREATE TABLE faltas (data TEXT, modulo TEXT, horas REAL, observacao TEXT)")
        lc.execute("CREATE TABLE dias_aula (data TEXT, horas_previstas REAL)")
        lc.commit()
        lc.close()

        conn = sqlite3.connect(self.finance)
        conn.executescript(
            """
            CREATE TABLE rendimentos (id INTEGER PRIMARY KEY, nome TEXT, valor REAL, ativo INTEGER);
            CREATE TABLE gastos (id INTEGER PRIMARY KEY, nome TEXT, valor REAL, ativo INTEGER);
            CREATE TABLE transacoes_unicas (
              id INTEGER PRIMARY KEY,
              data TEXT, nome TEXT, valor REAL, category TEXT, txn_type TEXT
            );
            INSERT INTO rendimentos (nome, valor, ativo) VALUES ('Job', 3000, 1);
            INSERT INTO gastos (nome, valor, ativo) VALUES ('Rent', 1000, 1);
            INSERT INTO transacoes_unicas (data, nome, valor, category, txn_type)
              VALUES ('2026-04-01', 'Side', 200, 'Other', 'income');
            """
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_top_sources_and_keys(self):
        out = analysis_service.build_workspace_analytics(
            self.finance,
            self.logic,
            include_iefp=False,
            current_month="2026-04",
            statement_count=0,
            latest_statement_month=None,
            projection_summary={"available": False},
        )
        self.assertIn("top_income_sources", out)
        self.assertIn("top_expense_sources", out)
        self.assertLessEqual(len(out["top_income_sources"]), 3)
        self.assertLessEqual(len(out["top_expense_sources"]), 3)
        labels = {x["label"] for x in out["top_income_sources"]}
        self.assertTrue("Job" in labels or "Side" in labels)


if __name__ == "__main__":
    unittest.main()
