import unittest

from app.services import calculator_eval


class TestCalculatorEval(unittest.TestCase):
    def test_basic_arithmetic(self):
        self.assertEqual(calculator_eval.safe_eval("2+3")["value"], 5.0)
        self.assertEqual(calculator_eval.safe_eval("10-4")["value"], 6.0)
        self.assertEqual(calculator_eval.safe_eval("3*4")["value"], 12.0)
        self.assertEqual(calculator_eval.safe_eval("15/3")["value"], 5.0)
        self.assertEqual(calculator_eval.safe_eval("2.5+1.5")["value"], 4.0)

    def test_parentheses(self):
        self.assertEqual(calculator_eval.safe_eval("(2+3)*4")["value"], 20.0)

    def test_invalid_does_not_crash(self):
        self.assertFalse(calculator_eval.safe_eval("2++")["ok"])
        self.assertFalse(calculator_eval.safe_eval("alert(1)")["ok"])
        self.assertFalse(calculator_eval.safe_eval("1/0")["ok"])
        self.assertEqual(calculator_eval.safe_eval("1/0")["error"], "division by zero")


if __name__ == "__main__":
    unittest.main()
