import unittest

from app.services import emergency_fund_service


class TestEmergencyFund(unittest.TestCase):
    def test_monthly_total_and_targets(self):
        r = emergency_fund_service.compute(
            {
                "housing": 1000,
                "food": 200,
                "transport": 0,
                "utilities": 100,
                "subscriptions": 50,
                "insurance": 0,
                "debt": 0,
                "other": 0,
                "buffer_pct": 10,
                "current_savings": 0,
            }
        )
        self.assertEqual(r["monthly_essential_base"], 1350.0)
        self.assertEqual(r["buffer_pct"], 10.0)
        self.assertEqual(r["monthly_with_buffer"], 1485.0)
        self.assertEqual(r["targets"][3], round(1485.0 * 3, 2))
        self.assertEqual(r["targets"][6], round(1485.0 * 6, 2))
        self.assertEqual(r["targets"][9], round(1485.0 * 9, 2))

    def test_progress_not_based_on_salary(self):
        r = emergency_fund_service.compute(
            {
                "housing": 500,
                "food": 300,
                "transport": 100,
                "utilities": 100,
                "subscriptions": 0,
                "insurance": 0,
                "debt": 0,
                "other": 0,
                "buffer_pct": 0,
                "current_savings": 2000,
            }
        )
        self.assertEqual(r["monthly_with_buffer"], 1000.0)
        p3 = r["progress"]["3"]
        self.assertEqual(p3["target"], 3000.0)
        self.assertAlmostEqual(p3["progress_pct"], 2000 / 3000 * 100, places=1)
        self.assertEqual(p3["still_needed"], 1000.0)

    def test_save_projection_rounds_up(self):
        r = emergency_fund_service.compute(
            {
                "housing": 1000,
                "food": 0,
                "transport": 0,
                "utilities": 0,
                "subscriptions": 0,
                "insurance": 0,
                "debt": 0,
                "other": 0,
                "buffer_pct": 0,
                "current_savings": 0,
                "monthly_save_willing": 250,
            }
        )
        # 3-month target = 3000, 3000/250 = 12 months exactly
        self.assertEqual(r["save_projection_months"]["3"], 12)
        # 6-month = 6000, 6000/250 = 24
        self.assertEqual(r["save_projection_months"]["6"], 24)

    def test_save_projection_ceil_partial_month(self):
        r = emergency_fund_service.compute(
            {
                "housing": 1000,
                "food": 0,
                "transport": 0,
                "utilities": 0,
                "subscriptions": 0,
                "insurance": 0,
                "debt": 0,
                "other": 0,
                "buffer_pct": 0,
                "current_savings": 0,
                "monthly_save_willing": 700,
            }
        )
        # 3-month target 3000, 3000/700 = 4.28... -> 5 months
        self.assertEqual(r["save_projection_months"]["3"], 5)

    def test_save_projection_zero_when_funded(self):
        r = emergency_fund_service.compute(
            {
                "housing": 500,
                "food": 0,
                "transport": 0,
                "utilities": 0,
                "subscriptions": 0,
                "insurance": 0,
                "debt": 0,
                "other": 0,
                "buffer_pct": 0,
                "current_savings": 5000,
                "monthly_save_willing": 100,
            }
        )
        self.assertEqual(r["save_projection_months"]["3"], 0)


if __name__ == "__main__":
    unittest.main()
