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
    def get_portfolio_data(db: Session, user_id: int) -> dict:
        """포트폴리오 자산, 최근 거래, 요약 정보를 한꺼번에 조회합니다."""
        # 목록/편집 대상은 활성(미삭제) 자산만 반환한다.
        assets = (
            db.query(Asset)
            .filter(
                Asset.user_id == user_id,
                Asset.deleted_at.is_(None),
            )
            .order_by(Asset.id.asc())
            .all()
        )
        # 요약의 실현손익은 누적 추적을 위해 삭제 자산도 포함한다.
        assets_for_summary = (
            db.query(Asset)
            .filter(Asset.user_id == user_id)
            .all()
        )
        trades = (
            db.query(Trade)
            .filter(Trade.user_id == user_id)
            .order_by(Trade.timestamp.desc())
            .limit(50)
            .all()
        )
        external_cashflows = (
            db.query(ExternalCashflow)
            .filter(ExternalCashflow.user_id == user_id)
            .all()
        )

        summary = calculate_summary(assets_for_summary, external_cashflows)
        return {
            "assets": [to_asset_read(a) for a in assets],
            "trades": [to_trade_read(t) for t in trades],
            "summary": summary,
        }

    @staticmethod
    def restore_assets(db: Session, user_id: int, asset_items: list) -> dict:
        """기존 자산을 모두 삭제(소프트)하고 새로운 자산 목록으로 복원합니다."""
        from ..core.time_utils import utcnow
        now = utcnow()

        existing_assets = (
            db.query(Asset)
            .filter(Asset.user_id == user_id, Asset.deleted_at.is_(None))
            .all()
        )
        for asset in existing_assets:
            asset.deleted_at = now
            asset.updated_at = now

        for item in asset_items:
            asset = Asset(
                user_id=user_id,
                name=item.name,
                ticker=item.ticker,
                category=item.category,
                currency=item.currency,
                amount=item.amount,
                current_price=item.current_price,
                purchase_price=item.purchase_price,
                realized_profit=item.realized_profit,
                index_group=item.index_group,
                cma_config=item.cma_config.model_dump()
                if item.cma_config is not None
                else None,
            )
            db.add(asset)

        try:
            db.commit()
        except Exception:
            db.rollback()
            raise

        return {
            "restored": len(asset_items),
            "deleted": len(existing_assets),
        }

    @staticmethod
    def create_snapshot(db: Session, user_id: int) -> PortfolioSnapshot:
        """
        현재 전체 자산의 가치를 합산하여 PortfolioSnapshot을 생성합니다.
        """
        from ..core.time_utils import utcnow
        
        assets = db.query(Asset).filter(Asset.user_id == user_id).all()
        external_cashflows = db.query(ExternalCashflow).filter(ExternalCashflow.user_id == user_id).all()
        summary = calculate_summary(assets, external_cashflows)

        snapshot = PortfolioSnapshot(
            user_id=user_id,
            snapshot_at=utcnow(),
            total_value=summary.total_value,
            total_invested=summary.total_invested,
            realized_profit_total=summary.realized_profit_total,
            unrealized_profit_total=summary.unrealized_profit_total,
        )
        db.add(snapshot)
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise
        db.refresh(snapshot)
        return snapshot
