from __future__ import annotations

from datetime import datetime, date
from typing import List

from ..models import Asset, FxTransaction, PortfolioSnapshot, Trade, ExternalCashflow
from ..schemas import (
    AssetRead,
    DividendRecord,
    DistributionItem,
    FxTransactionRead,
    PortfolioSnapshotRead,
    PortfolioSummary,
    TradeRead,
    ExternalCashflowRead,
)
from .performance import xirr


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


def calculate_summary(assets: List[Asset], external_cashflows: List[ExternalCashflow] = None) -> PortfolioSummary:
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

    total_dividends = 0.0
    dividend_yearly: list[DividendRecord] = []
    if external_cashflows:
        # Sum negative amounts (inflows) that have dividend-related descriptions
        dividend_map: dict[int, float] = {}
        for cf in external_cashflows:
            if cf.amount < 0 and any(k in (cf.description or "") for k in ["배당", "분배금", "DIV"]):
                amount = abs(cf.amount)
                total_dividends += amount
                year = cf.date.year
                dividend_map[year] = dividend_map.get(year, 0.0) + amount
        if dividend_map:
            dividend_yearly = [
                DividendRecord(year=year, total=total)
                for year, total in sorted(dividend_map.items())
            ]

    unrealized_profit_total = total_value - total_invested

    # --- XIRR Calculation ---
    xirr_rate = None
    if external_cashflows and len(external_cashflows) > 0:
        # XIRR expects:
        # - Deposits into portfolio: Negative (outflow from user perspective)
        # - Withdrawals from portfolio: Positive (inflow to user perspective)
        # - Current Value: Positive (treated as a withdrawal if sold today)
        
        investable_total_value = sum(
            a.amount * a.current_price
            for a in assets if a.category != "부동산"
        )
        
        txs = []
        for cf in external_cashflows:
            # Dividends, interests, and tax refunds are "Internal Returns"
            # In DB, inflows to brokerage are stored as < 0.
            # For XIRR:
            # - If it's a dividend/interest: Treat as a POSITIVE cashflow (withdrawal/profit)
            #   since the 'total_value' below only includes stock assets, not the cash account.
            # - If it's a transfer in: Stay NEGATIVE (investment cost)
            
            desc = (cf.description or "").upper()
            is_internal_return = any(k in desc for k in ["배당", "분배금", "DIV", "이자", "이용료", "환급"])
            
            if is_internal_return:
                txs.append((cf.date, abs(cf.amount))) # To Positive (Profit)
            else:
                txs.append((cf.date, cf.amount))      # Stay as is (Investment/Withdrawal)

        # Add Terminal Value (Investable Only)
        txs.append((date.today(), investable_total_value))
        
        # Sort by date
        txs.sort(key=lambda x: x[0])
        
        try:
            xirr_rate = xirr(txs)
        except Exception:
            xirr_rate = None

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
        total_dividends=total_dividends,
        dividend_yearly=dividend_yearly,
        category_distribution=category_distribution,
        index_distribution=index_distribution,
        xirr_rate=xirr_rate,
    )
