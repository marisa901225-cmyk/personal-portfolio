from __future__ import annotations

from typing import List
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from sqlalchemy import inspect, text

from ..auth import verify_api_token
from ..db import get_db, engine
from ..models import Base, Asset, Trade, Setting, User, PortfolioSnapshot
from ..schemas import (
    AssetCreate,
    AssetRead,
    AssetUpdate,
    TradeCreate,
    TradeRead,
    SettingsRead,
    SettingsUpdate,
    PortfolioResponse,
    PortfolioSummary,
    DistributionItem,
    TargetIndexAllocation,
    PortfolioSnapshotRead,
    DividendRecord,
)

router = APIRouter(prefix="/api", tags=["portfolio"], dependencies=[Depends(verify_api_token)])


def _migrate_settings_table() -> None:
    """
    기존 SQLite settings 테이블에 누락된 컬럼(dividend_year, dividend_total, dividends)이 있으면 추가한다.

    - 개인 프로젝트용 간단 마이그레이션이므로, ALTER TABLE만 수행.
    """
    inspector = inspect(engine)
    try:
        columns = {col["name"] for col in inspector.get_columns("settings")}
    except Exception:
        return

    statements: list[str] = []
    if "dividend_year" not in columns:
        statements.append("ALTER TABLE settings ADD COLUMN dividend_year INTEGER")
    if "dividend_total" not in columns:
        statements.append("ALTER TABLE settings ADD COLUMN dividend_total FLOAT")
    if "dividends" not in columns:
        statements.append("ALTER TABLE settings ADD COLUMN dividends JSON")

    if not statements:
        return

    with engine.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))


def _migrate_assets_table() -> None:
    """
    기존 SQLite assets 테이블에 누락된 컬럼(cma_config)이 있으면 추가한다.
    """
    inspector = inspect(engine)
    try:
        columns = {col["name"] for col in inspector.get_columns("assets")}
    except Exception:
        return

    statements: list[str] = []
    if "cma_config" not in columns:
        statements.append("ALTER TABLE assets ADD COLUMN cma_config JSON")

    if not statements:
        return

    with engine.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))


# --- 초기 스키마 생성 및 간단한 마이그레이션 ---
Base.metadata.create_all(bind=engine)
_migrate_settings_table()
_migrate_assets_table()


def _get_or_create_single_user(db: Session) -> User:
    user = db.query(User).first()
    if user:
        return user
    user = User(name="default")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _to_asset_read(asset: Asset) -> AssetRead:
    return AssetRead.model_validate(asset)


def _to_trade_read(trade: Trade) -> TradeRead:
    payload = TradeRead.model_validate(trade).model_dump()
    payload["asset_name"] = trade.asset.name if trade.asset else None
    payload["asset_ticker"] = trade.asset.ticker if trade.asset else None
    return TradeRead(**payload)


def _calculate_summary(assets: List[Asset]) -> PortfolioSummary:
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


def _to_snapshot_read(snapshot: PortfolioSnapshot) -> PortfolioSnapshotRead:
    return PortfolioSnapshotRead.model_validate(snapshot)


@router.get("/portfolio", response_model=PortfolioResponse)
def get_portfolio(db: Session = Depends(get_db)) -> PortfolioResponse:
    user = _get_or_create_single_user(db)
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

    summary = _calculate_summary(assets)
    return PortfolioResponse(
        assets=[_to_asset_read(a) for a in assets],
        trades=[_to_trade_read(t) for t in trades],
        summary=summary,
    )


@router.post("/assets", response_model=AssetRead)
def create_asset(payload: AssetCreate, db: Session = Depends(get_db)) -> AssetRead:
    user = _get_or_create_single_user(db)

    asset = Asset(
        user_id=user.id,
        name=payload.name,
        ticker=payload.ticker,
        category=payload.category,
        currency=payload.currency,
        amount=payload.amount,
        current_price=payload.current_price,
        purchase_price=payload.purchase_price,
        realized_profit=payload.realized_profit,
        index_group=payload.index_group,
        cma_config=payload.cma_config.model_dump() if payload.cma_config is not None else None,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return _to_asset_read(asset)


@router.patch("/assets/{asset_id}", response_model=AssetRead)
def update_asset(asset_id: int, payload: AssetUpdate, db: Session = Depends(get_db)) -> AssetRead:
    user = _get_or_create_single_user(db)
    asset = (
        db.query(Asset)
        .filter(Asset.id == asset_id, Asset.user_id == user.id, Asset.deleted_at.is_(None))
        .first()
    )
    if not asset:
        raise HTTPException(status_code=404, detail="asset not found")

    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(asset, field, value)
    asset.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(asset)
    return _to_asset_read(asset)


@router.delete("/assets/{asset_id}")
def delete_asset(asset_id: int, db: Session = Depends(get_db)) -> dict:
    user = _get_or_create_single_user(db)
    asset = (
        db.query(Asset)
        .filter(Asset.id == asset_id, Asset.user_id == user.id, Asset.deleted_at.is_(None))
        .first()
    )
    if not asset:
        raise HTTPException(status_code=404, detail="asset not found")

    # 소프트 삭제
    asset.deleted_at = datetime.utcnow()
    db.commit()
    return {"status": "ok"}


@router.post("/assets/{asset_id}/trades", response_model=TradeRead)
def create_trade_for_asset(
    asset_id: int,
    payload: TradeCreate,
    db: Session = Depends(get_db),
) -> TradeRead:
    user = _get_or_create_single_user(db)
    asset = (
        db.query(Asset)
        .filter(Asset.id == asset_id, Asset.user_id == user.id, Asset.deleted_at.is_(None))
        .with_for_update()
        .first()
    )
    if not asset:
        raise HTTPException(status_code=404, detail="asset not found")

    if payload.quantity <= 0 or payload.price <= 0:
        raise HTTPException(status_code=400, detail="quantity and price must be positive")

    now = datetime.utcnow()
    timestamp = payload.timestamp or now

    realized_delta = None

    if payload.type == "BUY":
        prev_amount = asset.amount
        prev_purchase_price = asset.purchase_price or asset.current_price or payload.price
        new_amount = prev_amount + payload.quantity
        if new_amount <= 0:
            raise HTTPException(status_code=400, detail="invalid resulting amount")
        new_purchase_price = (
            (prev_amount * prev_purchase_price + payload.quantity * payload.price) / new_amount
        )
        asset.amount = new_amount
        asset.purchase_price = new_purchase_price
        asset.current_price = payload.price
    elif payload.type == "SELL":
        if payload.quantity > asset.amount:
            raise HTTPException(
                status_code=400,
                detail="cannot sell more than current amount",
            )
        prev_amount = asset.amount
        avg_cost = asset.purchase_price or asset.current_price or payload.price
        new_amount = prev_amount - payload.quantity
        realized_delta = (payload.price - avg_cost) * payload.quantity
        asset.realized_profit = (asset.realized_profit or 0.0) + realized_delta
        asset.amount = new_amount
        asset.current_price = payload.price
        if new_amount <= 0:
            # 전량 매도 시 자산을 소프트 삭제 처리
            asset.deleted_at = now
    else:
        raise HTTPException(status_code=400, detail="invalid trade type")

    asset.updated_at = now

    trade = Trade(
        user_id=user.id,
        asset_id=asset.id,
        type=payload.type,
        quantity=payload.quantity,
        price=payload.price,
        timestamp=timestamp,
        realized_delta=realized_delta,
        note=payload.note,
    )
    db.add(trade)
    db.commit()
    db.refresh(trade)

    return _to_trade_read(trade)


@router.get("/trades/recent", response_model=List[TradeRead])
def get_recent_trades(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> List[TradeRead]:
    user = _get_or_create_single_user(db)
    trades = (
        db.query(Trade)
        .filter(Trade.user_id == user.id)
        .order_by(Trade.timestamp.desc())
        .limit(limit)
        .all()
    )
    return [_to_trade_read(t) for t in trades]


@router.get("/settings", response_model=SettingsRead)
def get_settings(db: Session = Depends(get_db)) -> SettingsRead:
    user = _get_or_create_single_user(db)
    setting = (
        db.query(Setting)
        .filter(Setting.user_id == user.id)
        .order_by(Setting.id.asc())
        .first()
    )
    if not setting:
        # 기본값 생성
        default_allocations = [
            TargetIndexAllocation(index_group="S&P500", target_weight=6),
            TargetIndexAllocation(index_group="NASDAQ100", target_weight=3),
            TargetIndexAllocation(index_group="BOND+ETC", target_weight=1),
        ]
        setting = Setting(
            user_id=user.id,
            target_index_allocations=[a.model_dump() for a in default_allocations],
            server_url=None,
        )
        db.add(setting)
        db.commit()
        db.refresh(setting)

    # target_index_allocations 는 JSON(dict/list) 형태이므로 Pydantic 모델로 감싸줌
    allocations_raw = setting.target_index_allocations or []
    allocations = [
        TargetIndexAllocation(**item) for item in allocations_raw  # type: ignore[arg-type]
    ]

    dividends_raw = setting.dividends or []
    if not dividends_raw and setting.dividend_year is not None and setting.dividend_total is not None:
        dividends_raw = [{"year": setting.dividend_year, "total": setting.dividend_total}]
    dividends = [
        DividendRecord(**item) for item in dividends_raw  # type: ignore[arg-type]
    ]
    return SettingsRead(
        target_index_allocations=allocations,
        server_url=setting.server_url,
        dividend_year=setting.dividend_year,
        dividend_total=setting.dividend_total,
        dividends=dividends,
    )


@router.put("/settings", response_model=SettingsRead)
def update_settings(
    payload: SettingsUpdate,
    db: Session = Depends(get_db),
) -> SettingsRead:
    user = _get_or_create_single_user(db)
    setting = (
        db.query(Setting)
        .filter(Setting.user_id == user.id)
        .order_by(Setting.id.asc())
        .first()
    )
    if not setting:
        setting = Setting(user_id=user.id)
        db.add(setting)

    if payload.target_index_allocations is not None:
        setting.target_index_allocations = [
            item.model_dump() for item in payload.target_index_allocations
        ]
    if payload.server_url is not None:
        setting.server_url = payload.server_url
    if payload.dividends is not None:
        setting.dividends = [item.model_dump() for item in payload.dividends]
    if payload.dividend_year is not None:
        setting.dividend_year = payload.dividend_year
    if payload.dividend_total is not None:
        setting.dividend_total = payload.dividend_total

    setting.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(setting)

    allocations_raw = setting.target_index_allocations or []
    allocations = [
        TargetIndexAllocation(**item) for item in allocations_raw  # type: ignore[arg-type]
    ]

    dividends_raw = setting.dividends or []
    if not dividends_raw and setting.dividend_year is not None and setting.dividend_total is not None:
        dividends_raw = [{"year": setting.dividend_year, "total": setting.dividend_total}]
    dividends = [
        DividendRecord(**item) for item in dividends_raw  # type: ignore[arg-type]
    ]
    return SettingsRead(
        target_index_allocations=allocations,
        server_url=setting.server_url,
        dividend_year=setting.dividend_year,
        dividend_total=setting.dividend_total,
        dividends=dividends,
    )


@router.post("/portfolio/snapshots", response_model=PortfolioSnapshotRead)
def create_portfolio_snapshot(db: Session = Depends(get_db)) -> PortfolioSnapshotRead:
    """
    현재 포트폴리오 상태(총자산/원금/손익 요약)를 스냅샷으로 저장한다.

    - 용도: cron/systemd timer 등에서 하루 1번 호출하여 히스토리 차트 데이터로 사용.
    """
    user = _get_or_create_single_user(db)
    assets = (
        db.query(Asset)
        .filter(Asset.user_id == user.id, Asset.deleted_at.is_(None))
        .all()
    )
    summary = _calculate_summary(assets)
    now = datetime.utcnow()

    snapshot = PortfolioSnapshot(
        user_id=user.id,
        snapshot_at=now,
        total_value=summary.total_value,
        total_invested=summary.total_invested,
        realized_profit_total=summary.realized_profit_total,
        unrealized_profit_total=summary.unrealized_profit_total,
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)

    return _to_snapshot_read(snapshot)


@router.get("/portfolio/snapshots", response_model=List[PortfolioSnapshotRead])
def get_portfolio_snapshots(
    days: int = Query(180, ge=1, le=3650),
    db: Session = Depends(get_db),
) -> List[PortfolioSnapshotRead]:
    """
    최근 N일 동안의 포트폴리오 스냅샷 목록을 반환한다.

    - 기본값: 180일 (약 6개월)
    - 프론트 히스토리 차트에서 사용.
    """
    user = _get_or_create_single_user(db)
    since = datetime.utcnow() - timedelta(days=days)

    snapshots = (
        db.query(PortfolioSnapshot)
        .filter(
            PortfolioSnapshot.user_id == user.id,
            PortfolioSnapshot.snapshot_at >= since,
        )
        .order_by(PortfolioSnapshot.snapshot_at.asc())
        .all()
    )

    return [_to_snapshot_read(s) for s in snapshots]
