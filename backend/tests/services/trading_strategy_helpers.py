from __future__ import annotations

import unittest

import pandas as pd

from backend.services.trading_engine.strategy import Candidates


class TradingStrategyTestCase(unittest.TestCase):
    def _candidates_with_popular(self, popular: pd.DataFrame) -> Candidates:
        return Candidates(
            asof="20260227",
            popular=popular,
            model=pd.DataFrame(),
            etf=pd.DataFrame(),
            merged=pd.DataFrame(),
            quote_codes=[],
        )

    def _candidates_with_swing(
        self,
        model: pd.DataFrame,
        etf: pd.DataFrame,
        popular: pd.DataFrame | None = None,
    ) -> Candidates:
        return Candidates(
            asof="20260227",
            popular=popular if popular is not None else pd.DataFrame(),
            model=model,
            etf=etf,
            merged=pd.DataFrame(),
            quote_codes=[],
        )
