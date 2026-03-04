import unittest
from datetime import datetime
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core.models import Asset, User
from backend.services.market_data import MarketDataService


class MarketDataSyncScopeTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:", future=True)
        User.__table__.create(self.engine)
        Asset.__table__.create(self.engine)
        self.SessionLocal = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            future=True,
        )
        self.db = self.SessionLocal()

        user = User(name="tester")
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        self.user_id = user.id

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _add_asset(
        self,
        *,
        name: str,
        ticker: str | None,
        amount: float,
        price: float,
        deleted_at=None,
        currency: str = "KRW",
    ) -> Asset:
        asset = Asset(
            user_id=self.user_id,
            name=name,
            ticker=ticker,
            category="주식",
            currency=currency,
            amount=amount,
            current_price=price,
            purchase_price=price,
            deleted_at=deleted_at,
        )
        self.db.add(asset)
        self.db.commit()
        self.db.refresh(asset)
        return asset

    @patch("backend.services.market_data.fetch_usdkrw_rate", return_value=None)
    @patch("backend.services.market_data.fetch_kis_prices_krw")
    def test_sync_all_prices_targets_only_active_holdings(self, mock_fetch_prices, _mock_fx):
        active_kr = self._add_asset(name="삼성전자", ticker="005930", amount=2.0, price=100.0)
        active_us_1 = self._add_asset(name="엔비디아1", ticker="NVDA", amount=1.0, price=200.0, currency="USD")
        active_us_2 = self._add_asset(name="엔비디아2", ticker="NVDA", amount=3.0, price=300.0, currency="USD")
        zero_qty = self._add_asset(name="제로수량", ticker="TSLA", amount=0.0, price=400.0, currency="USD")
        deleted_asset = self._add_asset(
            name="삭제자산",
            ticker="AAPL",
            amount=1.0,
            price=500.0,
            deleted_at=datetime.utcnow(),
            currency="USD",
        )
        no_ticker = self._add_asset(name="티커없음", ticker=None, amount=1.0, price=600.0)

        mock_fetch_prices.return_value = {
            "005930": 71000.0,
            "NVDA": 180000.0,
        }

        synced_count = MarketDataService.sync_all_prices(self.db)

        self.assertEqual(synced_count, 2)
        mock_fetch_prices.assert_called_once()
        self.assertEqual(mock_fetch_prices.call_args[0][0], ["005930", "NVDA"])

        self.db.refresh(active_kr)
        self.db.refresh(active_us_1)
        self.db.refresh(active_us_2)
        self.db.refresh(zero_qty)
        self.db.refresh(deleted_asset)
        self.db.refresh(no_ticker)

        self.assertEqual(active_kr.current_price, 71000.0)
        self.assertEqual(active_us_1.current_price, 180000.0)
        self.assertEqual(active_us_2.current_price, 180000.0)
        self.assertEqual(zero_qty.current_price, 400.0)
        self.assertEqual(deleted_asset.current_price, 500.0)
        self.assertEqual(no_ticker.current_price, 600.0)

    @patch("backend.services.market_data.fetch_kis_prices_krw")
    def test_sync_all_prices_returns_zero_when_no_active_holding(self, mock_fetch_prices):
        self._add_asset(name="제로수량", ticker="TSLA", amount=0.0, price=400.0, currency="USD")
        self._add_asset(
            name="삭제자산",
            ticker="AAPL",
            amount=1.0,
            price=500.0,
            deleted_at=datetime.utcnow(),
            currency="USD",
        )
        self._add_asset(name="티커없음", ticker=None, amount=1.0, price=600.0)

        synced_count = MarketDataService.sync_all_prices(self.db)

        self.assertEqual(synced_count, 0)
        mock_fetch_prices.assert_not_called()

