from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..core.auth import verify_api_token
from ..core.db import get_db
from ..core.schemas import PortfolioResponse, PortfolioRestoreRequest, PortfolioRestoreResponse
from ..services.portfolio import PortfolioService
from ..services.users import get_or_create_single_user

router = APIRouter(prefix="/api", tags=["portfolio"], dependencies=[Depends(verify_api_token)])


@router.get("/portfolio", response_model=PortfolioResponse)
def get_portfolio(db: Session = Depends(get_db)) -> PortfolioResponse:
    user = get_or_create_single_user(db)
    return PortfolioService.get_portfolio_data(db, user.id)


@router.post("/portfolio/restore", response_model=PortfolioRestoreResponse)
def restore_portfolio(
    payload: PortfolioRestoreRequest, db: Session = Depends(get_db)
) -> PortfolioRestoreResponse:
    user = get_or_create_single_user(db)
    return PortfolioService.restore_assets(db, user.id, payload.assets)
