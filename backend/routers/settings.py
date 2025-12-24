from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import verify_api_token
from ..db import get_db
from ..models import Setting
from ..schemas import (
    DividendRecord,
    SettingsRead,
    SettingsUpdate,
    TargetIndexAllocation,
)
from ..services.users import get_or_create_single_user

router = APIRouter(prefix="/api", tags=["portfolio"], dependencies=[Depends(verify_api_token)])


def _to_settings_read(setting: Setting) -> SettingsRead:
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
        usd_fx_base=setting.usd_fx_base,
        usd_fx_now=setting.usd_fx_now,
    )


@router.get("/settings", response_model=SettingsRead)
def get_settings(db: Session = Depends(get_db)) -> SettingsRead:
    user = get_or_create_single_user(db)
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

    return _to_settings_read(setting)


@router.put("/settings", response_model=SettingsRead)
def update_settings(
    payload: SettingsUpdate,
    db: Session = Depends(get_db),
) -> SettingsRead:
    user = get_or_create_single_user(db)
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
    if "usd_fx_base" in payload.model_fields_set:
        setting.usd_fx_base = payload.usd_fx_base
    if "usd_fx_now" in payload.model_fields_set:
        setting.usd_fx_now = payload.usd_fx_now

    setting.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(setting)

    return _to_settings_read(setting)

