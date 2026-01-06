from __future__ import annotations

from datetime import datetime, timedelta
import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..core.auth import verify_api_token
from ..core.db import get_db
from ..core.models import Setting
from ..core.schemas import (
    DividendRecord,
    SettingsRead,
    SettingsUpdate,
    TargetIndexAllocation,
)
from ..services.users import get_or_create_single_user
from ..services.benchmark import compute_calendar_year_total_return, DEFAULT_BENCHMARK_NAME

router = APIRouter(prefix="/api", tags=["portfolio"], dependencies=[Depends(verify_api_token)])
logger = logging.getLogger(__name__)

def _normalize_benchmark_name(name: str) -> str:
    return name.replace(" ", "").upper()


def _is_default_benchmark_name(name: str) -> bool:
    normalized = _normalize_benchmark_name(name)
    base = _normalize_benchmark_name(DEFAULT_BENCHMARK_NAME)
    return normalized.startswith(base)


def _should_refresh_benchmark(setting: Setting) -> bool:
    if setting.benchmark_name and not _is_default_benchmark_name(setting.benchmark_name):
        return False
    if setting.benchmark_return is None:
        return True
    if setting.benchmark_updated_at is None:
        return True
    return setting.benchmark_updated_at.date() != datetime.utcnow().date()


def _refresh_benchmark_if_needed(setting: Setting, db: Session) -> None:
    if not _should_refresh_benchmark(setting):
        return
    try:
        label, benchmark_return, _ = compute_calendar_year_total_return()
    except Exception as exc:
        logger.warning("Benchmark update failed: %s", exc)
        return

    setting.benchmark_name = label
    setting.benchmark_return = benchmark_return
    setting.benchmark_updated_at = datetime.utcnow()
    db.commit()
    db.refresh(setting)


from ..services.settings_service import to_settings_read as _to_settings_read


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

    _refresh_benchmark_if_needed(setting, db)
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
    if "benchmark_name" in payload.model_fields_set:
        setting.benchmark_name = payload.benchmark_name
    if "benchmark_return" in payload.model_fields_set:
        setting.benchmark_return = payload.benchmark_return
    if (
        "benchmark_name" in payload.model_fields_set
        or "benchmark_return" in payload.model_fields_set
    ):
        setting.benchmark_updated_at = datetime.utcnow()

    setting.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(setting)

    return _to_settings_read(setting)
