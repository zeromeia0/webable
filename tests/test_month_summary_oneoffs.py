"""month_summary one-off income vs expense handling."""

import os
import tempfile
import unittest

from app.services import instance_service


class TestMonthSummaryOneoffs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.finance = os.path.join(self.tmp.name, "f.sqlite")
        self.logic = os.path.join(self.tmp.name, "l.sqlite")
        # minimal logic db for month_summary without iefp
        import sqlite3

        lc = sqlite3.connect(self.logic)
        lc.execute("CREATE TABLE faltas (data TEXT, modulo TEXT, horas REAL, observacao TEXT)")
        lc.execute("CREATE TABLE dias_aula (data TEXT, horas_previstas REAL)")
        lc.commit()
        lc.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_oneoff_income_and_expense_net_in_savings(self):
        import sqlite3

        conn = sqlite3.connect(self.finance)
        conn.executescript(
            """
            CREATE TABLE rendimentos (id INTEGER PRIMARY KEY, nome TEXT, valor REAL, ativo INTEGER);
            CREATE TABLE gastos (id INTEGER PRIMARY KEY, nome TEXT, valor REAL, ativo INTEGER);
            CREATE TABLE transacoes_unicas (
              id INTEGER PRIMARY KEY,
              data TEXT, nome TEXT, valor REAL, category TEXT, txn_type TEXT
            );
            INSERT INTO rendimentos (nome, valor, ativo) VALUES ('Salary', 2000, 1);
            INSERT INTO gastos (nome, valor, ativo) VALUES ('Rent', 800, 1);
            INSERT INTO transacoes_unicas (data, nome, valor, category, txn_type)
              VALUES ('2026-05-10', 'Bonus', 100, 'Other', 'income');
            INSERT INTO transacoes_unicas (data, nome, valor, category, txn_type)
              VALUES ('2026-05-15', 'Gift', 50, 'Gifts', 'expense');
            """
        )
        conn.commit()
        conn.close()

        m = instance_service.month_summary(self.finance, self.logic, "2026-05", include_iefp=False)
        self.assertEqual(m["oneoff_income_total"], 100.0)
        self.assertEqual(m["oneoff_expense_total"], 50.0)
        self.assertEqual(m["oneoff_net"], 50.0)
        # inflow 2000+100, outflow 800+50, net 1250
        self.assertAlmostEqual(m["estimated_savings"], 1250.0, places=2)


if __name__ == "__main__":
    unittest.main()
