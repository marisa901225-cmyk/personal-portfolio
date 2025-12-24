from __future__ import annotations

from typing import List

from ..models import Asset, FxTransaction, PortfolioSnapshot, Trade
from ..schemas import (
    AssetRead,
    DistributionItem,
    FxTransactionRead,
    PortfolioSnapshotRead,
    PortfolioSummary,
    TradeRead,
)


def to_asset_read(asset: Asset) -> AssetRead:
    return AssetRead.model_validate(asset)


def to_trade_read(trade: Trade) -> TradeRead:
    payload = TradeRead.model_validate(trade).model_dump()
    payload["asset_name"] = trade.asset.name if trade.asset else None
    payload["asset_ticker"] = trade.asset.ticker if trade.asset else None
    return TradeRead(**payload)


def to_fx_transaction_read(record: FxTransaction) -> FxTransactionRead:
    return FxTransactionRead.model_validate(record)


def to_snapshot_read(snapshot: PortfolioSnapshot) -> PortfolioSnapshotRead:
    return PortfolioSnapshotRead.model_validate(snapshot)


def calculate_summary(assets: List[Asset]) -> PortfolioSummary:
    total_value = 0.0
    total_invested = 0.0
    realized_profit_total = 0.0

    category_map: dict[str, float] = {}
    index_map: dict[str, float] = {}

    for asset in assets:
        if asset.deleted_at is not None:
            continue

        value = asset.amount * asset.current_price
        invested = asset.amount * (asset.purchase_price or asset.current_price)
        realized = asset.realized_profit or 0.0

        total_value += value
        total_invested += invested
        realized_profit_total += realized

        category_map[asset.category] = category_map.get(asset.category, 0.0) + value

        if asset.index_group:
            index_map[asset.index_group] = index_map.get(asset.index_group, 0.0) + value

    unrealized_profit_total = total_value - total_invested

    category_distribution = [
        DistributionItem(name=name, value=value) for name, value in category_map.items()
    ]
    index_distribution = [
        DistributionItem(name=name, value=value) for name, value in index_map.items()
    ]

    return PortfolioSummary(
        total_value=total_value,
        total_invested=total_invested,
        realized_profit_total=realized_profit_total,
        unrealized_profit_total=unrealized_profit_total,
        category_distribution=category_distribution,
        index_distribution=index_distribution,
    )

