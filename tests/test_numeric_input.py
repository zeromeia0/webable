"""Tests for strict decimal parsing."""

from __future__ import annotations

import unittest

from app.services import numeric_input


class TestNumericInput(unittest.TestCase):
    def test_rejects_scientific_notation(self):
        with self.assertRaises(ValueError):
            numeric_input.parse_decimal("2e8")
        with self.assertRaises(ValueError):
            numeric_input.parse_decimal("1E10")
        self.assertFalse(numeric_input.is_valid_decimal_string("2e8"))

    def test_rejects_letters(self):
        with self.assertRaises(ValueError):
            numeric_input.parse_decimal("12abc")
        self.assertFalse(numeric_input.is_valid_decimal_string("abc"))

    def test_accepts_standard_decimals(self):
        self.assertAlmostEqual(numeric_input.parse_decimal("123.45"), 123.45)
        self.assertAlmostEqual(numeric_input.parse_decimal("1,5", allow_negative=False), 1.5)
        self.assertAlmostEqual(numeric_input.parse_positive_decimal("0.01"), 0.01)

    def test_positive_requires_above_zero(self):
        with self.assertRaises(ValueError):
            numeric_input.parse_positive_decimal("0")


if __name__ == "__main__":
    unittest.main()
