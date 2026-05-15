import unittest
from pathlib import Path


class TestGlobalFabPartial(unittest.TestCase):
    def test_partial_has_calculator_and_ai(self):
        p = Path(__file__).resolve().parents[1] / "app" / "templates" / "partials" / "global_fab_stack.html"
        html = p.read_text(encoding="utf-8")
        self.assertIn('id="globalCalcFab"', html)
        self.assertIn('id="globalAiFab"', html)
        self.assertIn("webable-calculator.js", html)


if __name__ == "__main__":
    unittest.main()
