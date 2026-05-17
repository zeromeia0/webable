"""Tests for lightweight results summary PDF."""

from __future__ import annotations

import unittest

from app.services.projection_pdf import build_results_summary_pdf


class TestResultsSummaryPdf(unittest.TestCase):
    def test_builds_pdf_bytes(self):
        details = {
            "cards": [
                {"label": "Projected Accumulated Savings", "value": "EUR 1,200.00"},
                {"label": "Best Month", "value": "2026-01 (EUR 400.00)"},
                {"label": "Worst Month", "value": "2026-02 (EUR -50.00)"},
            ],
            "sections": [
                {
                    "title": "Projection Highlights",
                    "items": ["Months analyzed: 3", "Positive months: 2", "Negative months: 1"],
                }
            ],
            "bars": [
                {"label": "2026-01", "value_eur": 400.0},
                {"label": "2026-02", "value_eur": -50.0},
            ],
            "recommendation": "Your long-term trend is positive.",
        }
        try:
            raw = build_results_summary_pdf(
                workspace_name="Test",
                result_title="Long-range projection completed",
                result_subtitle="3 months",
                output_details=details,
            )
        except ImportError:
            self.skipTest("reportlab not installed")
        self.assertTrue(raw.startswith(b"%PDF"))
        self.assertGreater(len(raw), 500)


if __name__ == "__main__":
    unittest.main()
