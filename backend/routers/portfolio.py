from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import verify_api_token
from ..db import get_db
from ..models import Asset, Trade
from ..schemas import PortfolioResponse
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

    summary = calculate_summary(assets)
    return PortfolioResponse(
        assets=[to_asset_read(a) for a in assets],
        trades=[to_trade_read(t) for t in trades],
        summary=summary,
    )

