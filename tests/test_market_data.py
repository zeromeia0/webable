import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import (  # noqa: F401
    BankStatement,
    CategoryBudget,
    DatabaseInstance,
    FinanceAuditLog,
    JobRun,
    MarketChartCache,
    MarketQuote,
    MotherInsightEvent,
    User,
)
from app.services import market_data_service


class TestMarketPublicDict(unittest.TestCase):
    def test_empty_db_returns_placeholders(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        db = Session()
        try:
            d = market_data_service.public_dict(db)
            self.assertIn("items", d)
            self.assertEqual(len(d["items"]), 3)
            symbols = {x["symbol"] for x in d["items"]}
            self.assertEqual(symbols, {"SP500", "BTC", "ETH"})
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
