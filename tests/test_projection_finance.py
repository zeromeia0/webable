"""Tests for investment compounding (reference calculator parity)."""

from __future__ import annotations

import unittest
from datetime import datetime

from dateutil.relativedelta import relativedelta

from app.services import projection_finance


class TestCompoundReference(unittest.TestCase):
    """Scenario from standard compound calculator (beginning-of-month, monthly steps)."""

    def test_fixed_monthly_contribution_seven_years_eight_percent(self):
        # Reference calculator: starting 0, beginning-of-month contribution, 8% effective annual,
        # monthly equivalent (1.08)^(1/12)-1, 84 periods.
        end, cum, profit = projection_finance.compound_investment_monthly_beginning(
            starting_balance=0.0,
            monthly_contribution=884.40,
            annual_rate_pct=8.0,
            total_months=84,
        )
        self.assertAlmostEqual(cum, 74289.60, places=2, msg="total contributions")
        self.assertAlmostEqual(end, 98751.17, places=2, msg="end balance")
        self.assertAlmostEqual(profit, 24461.57, places=2, msg="interest / profit")

    def test_monthly_rate_formula(self):
        im = projection_finance.monthly_rate_from_annual_percent(8.0)
        self.assertAlmostEqual(im, (1.08) ** (1 / 12) - 1, places=12)


class TestHorizonExtendsPastProjection(unittest.TestCase):
    def test_contributions_full_horizon_not_truncated_to_projection_length(self):
        start = datetime(2022, 1, 1)
        rows = []
        for i in range(24):
            d = start + relativedelta(months=i)
            rows.append(
                {
                    "month": d.strftime("%Y-%m"),
                    "accumulated": float(i + 1) * 200.0,
                    "estimated_savings": 1474.0,
                }
            )
        sim = projection_finance.run_monthly_simulation(rows, invest_pct=60.0, annual_rate_pct=8.0, horizon_years=7.0)
        self.assertEqual(sim["meta"]["horizon_months"], 84)
        self.assertEqual(sim["meta"]["projection_months"], 24)
        self.assertAlmostEqual(sim["summary"]["final_cumulative_contributed"], 74289.60, places=2)
        self.assertAlmostEqual(sim["summary"]["final_investment_balance"], 98751.17, places=2)
        for r in sim["rows"]:
            self.assertAlmostEqual(r["contribution"], 884.40, places=2)
        self.assertEqual(len(sim["rows"]), 84)

    def test_extension_when_final_projection_month_has_zero_savings(self):
        """Last in-chart month can be €0 savings (no contribution that month); extension still invests."""
        start = datetime(2022, 1, 1)
        rows = []
        for i in range(24):
            d = start + relativedelta(months=i)
            sav = 1474.0 if i < 23 else 0.0
            rows.append(
                {
                    "month": d.strftime("%Y-%m"),
                    "accumulated": 1000.0 + float(i),
                    "estimated_savings": sav,
                }
            )
        sim = projection_finance.run_monthly_simulation(rows, 60.0, 8.0, 7.0)
        self.assertEqual(sim["rows"][23]["contribution"], 0.0)
        self.assertAlmostEqual(sim["rows"][24]["contribution"], 884.40, places=2)
        self.assertEqual(sim["meta"]["extended_monthly_savings_base"], 1474.0)
        self.assertAlmostEqual(sim["summary"]["final_cumulative_contributed"], 73405.20, places=2)
        self.assertAlmostEqual(sim["summary"]["final_investment_balance"], 97443.34, places=2)


if __name__ == "__main__":
    unittest.main()
