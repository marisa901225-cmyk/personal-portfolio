from __future__ import annotations

from datetime import datetime, date
from typing import List

from ..core.models import Asset, FxTransaction, PortfolioSnapshot, Trade, ExternalCashflow
from ..core.schemas import (
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

# Keywords for XIRR classification
# Income: dividends, interest, refunds - should be POSITIVE in XIRR (inflow to user)
_INCOME_KEYWORDS = ["배당", "분배금", "DIV", "이자", "이용료", "환급"]
# Costs: tax, fees - should be NEGATIVE in XIRR (outflow from user's return)
_COST_KEYWORDS = ["세금", "TAX", "WITHHOLD", "원천징수", "수수료", "FEE"]


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
        # 실현손익은 삭제 여부와 상관없이 항상 합산 (누적 손익 추적용)
        realized = asset.realized_profit or 0.0
        realized_profit_total += realized

        # 현재 보유 중인 자산에 대해서만 가치와 투자금 계산
        if asset.deleted_at is not None:
            continue

        value = asset.amount * asset.current_price
        invested = asset.amount * (asset.purchase_price or asset.current_price)

        total_value += value
        total_invested += invested

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
            desc = (cf.description or "").upper()
            
            # Check for cost keywords first (tax, fees) - they should reduce returns
            is_internal_cost = any(k.upper() in desc for k in _COST_KEYWORDS)
            # Check for income keywords (dividends, interest)
            is_internal_return = any(k.upper() in desc for k in _INCOME_KEYWORDS)
            
            if is_internal_cost:
                # Costs should be negative (outflow from portfolio returns)
                # Even if stored as negative in DB, ensure it's negative in XIRR
                txs.append((cf.date, -abs(cf.amount)))
            elif is_internal_return:
                # Income should be positive (inflow to user)
                txs.append((cf.date, abs(cf.amount)))
            else:
                # Regular deposits/withdrawals: keep original sign
                # In DB, deposits are stored as negative (outflow from bank to portfolio)
                txs.append((cf.date, cf.amount))

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


class PortfolioService:
    @staticmethod
    def create_snapshot(db: Session) -> PortfolioSnapshot:
        """
        현재 전체 자산의 가치를 합산하여 PortfolioSnapshot을 생성합니다.
        """
        assets = db.query(Asset).all()
        external_cashflows = db.query(ExternalCashflow).all()
        summary = calculate_summary(assets, external_cashflows)

        snapshot = PortfolioSnapshot(
            total_value=summary.total_value,
            total_invested=summary.total_invested,
            realized_profit=summary.realized_profit_total,
            unrealized_profit=summary.unrealized_profit_total,
            timestamp=datetime.now()
        )
        db.add(snapshot)
        db.commit()
        db.refresh(snapshot)
        return snapshot
