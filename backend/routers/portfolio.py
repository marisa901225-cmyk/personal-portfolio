from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import verify_api_token
from ..db import get_db
from ..models import Asset, Trade, ExternalCashflow
from ..schemas import PortfolioResponse, PortfolioRestoreRequest, PortfolioRestoreResponse
from ..services.portfolio import calculate_summary, to_asset_read, to_trade_read
from ..services.users import get_or_create_single_user

router = APIRouter(prefix="/api", tags=["portfolio"], dependencies=[Depends(verify_api_token)])


@router.get("/portfolio", response_model=PortfolioResponse)
def get_portfolio(db: Session = Depends(get_db)) -> PortfolioResponse:
    user = get_or_create_single_user(db)
    assets = (
        db.query(Asset)
        .filter(Asset.user_id == user.id, Asset.deleted_at.is_(None))
        .order_by(Asset.id.asc())
        .all()
    )
    trades = (
        db.query(Trade)
        .filter(Trade.user_id == user.id)
        .order_by(Trade.timestamp.desc())
        .limit(50)
        .all()
    )

    external_cashflows = (
        db.query(ExternalCashflow)
        .filter(ExternalCashflow.user_id == user.id)
        .all()
    )

    summary = calculate_summary(assets, external_cashflows)
    return PortfolioResponse(
        assets=[to_asset_read(a) for a in assets],
        trades=[to_trade_read(t) for t in trades],
        summary=summary,
    )


@router.post("/portfolio/restore", response_model=PortfolioRestoreResponse)
def restore_portfolio(
    payload: PortfolioRestoreRequest, db: Session = Depends(get_db)
) -> PortfolioRestoreResponse:
    user = get_or_create_single_user(db)
    now = datetime.utcnow()

    existing_assets = (
        db.query(Asset)
        .filter(Asset.user_id == user.id, Asset.deleted_at.is_(None))
        .all()
    )
    for asset in existing_assets:
        asset.deleted_at = now
        asset.updated_at = now

    for item in payload.assets:
        asset = Asset(
            user_id=user.id,
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

    return PortfolioRestoreResponse(
        restored=len(payload.assets),
        deleted=len(existing_assets),
    )
