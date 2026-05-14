"""market_chart_service validation (no network)."""

import unittest

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import MarketChartCache  # noqa: F401
from app.services import market_chart_service


class TestMarketChartValidation(unittest.TestCase):
    def test_invalid_symbol_returns_empty(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        db = Session()
        try:
            out = market_chart_service.get_series(db, Path("."), "XXX", "1m")
            self.assertEqual(out["points"], [])
            self.assertIn("Invalid", out.get("error", ""))
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
