from __future__ import annotations

from typing import Protocol, runtime_checkable

import pandas as pd

from .types import BrokerPosition, BrokerRankRecord, OrderInfoPayload, OrderPayload, Quote


@runtime_checkable
class TradingAPI(Protocol):
    """Injected API surface used by the trading engine."""

    def volume_rank(self, kind: str, top_n: int, asof: str) -> list[BrokerRankRecord]:
        ...

    def hts_top_view_rank(self, top_n: int, asof: str) -> list[BrokerRankRecord]:
        ...

    def market_cap_rank(self, top_k: int, asof: str) -> list[BrokerRankRecord]:
        ...

    def daily_bars(self, code: str, end: str, lookback: int) -> pd.DataFrame:
        ...

    def quote(self, code: str) -> Quote:
        ...

    def positions(self) -> list[BrokerPosition]:
        ...

    def cash_available(self) -> int:
        ...

    def place_order(
        self,
        side: str,
        code: str,
        qty: int,
        order_type: str,
        price: int | None,
    ) -> OrderPayload:
        ...

    def open_orders(self) -> list[OrderPayload]:
        ...

    def cancel_order(self, order_id: str) -> OrderPayload:
        ...


@runtime_checkable
class BuyOrderInfoAPI(Protocol):
    """Optional interface for broker-native buyable cash/qty lookup."""

    def buy_order_capacity(
        self,
        code: str,
        order_type: str,
        price: int | None,
    ) -> OrderInfoPayload:
        ...


@runtime_checkable
class SellOrderInfoAPI(Protocol):
    """Optional interface for broker-native sellable quantity lookup."""

    def sell_order_capacity(self, code: str) -> OrderInfoPayload:
        ...


@runtime_checkable
class TradingDayAPI(Protocol):
    """Optional interface for direct exchange holiday lookup."""

    def is_trading_day(self, date: str) -> bool:
        ...


@runtime_checkable
class IndexChartAPI(Protocol):
    """Optional interface for domestic industry/index daily charts."""

    def daily_index_bars(self, index_code: str, end: str, lookback: int) -> pd.DataFrame:
        ...


class TextNotifier(Protocol):
    def __call__(self, text: str) -> bool:
        ...


class FileNotifier(Protocol):
    def __call__(self, path: str, caption: str | None = None) -> bool:
        ...
