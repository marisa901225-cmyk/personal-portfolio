from __future__ import annotations

from typing import TypeAlias

BrokerPosition: TypeAlias = dict[str, object]
BrokerRankRecord: TypeAlias = dict[str, object]
OrderInfoPayload: TypeAlias = dict[str, object]
OrderPayload: TypeAlias = dict[str, object]
PendingExitOrder: TypeAlias = dict[str, object]
Quote: TypeAlias = dict[str, object]
QuoteMap: TypeAlias = dict[str, Quote]
