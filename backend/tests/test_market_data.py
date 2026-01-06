
import unittest
from unittest.mock import patch, MagicMock
import asyncio

from sqlalchemy import create_mock_engine
from sqlalchemy.orm import Session

from backend.services.market_data_service import (
    get_kis_prices_krw,
    search_tickers_by_name,
    get_usdkrw_rate,
    KisConfigurationError,
)

class MarketDataServiceTests(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock(spec=Session)

    @patch("backend.kis_client.fetch_kis_prices_krw")
    def test_get_kis_prices_krw_success(self, mock_fetch):
        # Mocking
        mock_fetch.return_value = {"005930": 70000.0}
        
        # execution
        result = asyncio.run(get_kis_prices_krw(["005930"], self.db, sync_to_assets=False))
        
        # verification
        self.assertEqual(result["005930"], 70000.0)
        mock_fetch.assert_called_once()

    @patch("backend.kis_client.fetch_kis_prices_krw")
    def test_get_kis_prices_configuration_error(self, mock_fetch):
        # Mocking RuntimeError (simulating KIS_ENABLED=disabled or missing keys)
        mock_fetch.side_effect = RuntimeError("KIS disabled")
        
        with self.assertRaises(KisConfigurationError):
            asyncio.run(get_kis_prices_krw(["005930"], self.db))

    @patch("backend.kis_client.search_tickers_by_name")
    def test_search_tickers_by_name(self, mock_search):
        mock_search.return_value = [{"symbol": "005930", "name": "삼성전자"}]
        
        result = asyncio.run(search_tickers_by_name("삼성"))
        
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["symbol"], "005930")

    @patch("backend.kis_client.fetch_usdkrw_rate")
    def test_get_usdkrw_rate(self, mock_fetch):
        mock_fetch.return_value = 1300.0
        
        result = asyncio.run(get_usdkrw_rate())
        
        self.assertEqual(result, 1300.0)
