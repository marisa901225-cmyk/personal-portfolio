"""
Settings Service

설정 관련 헬퍼 함수들.
라우터 간 의존을 제거하기 위해 서비스 레이어로 분리.
"""

from __future__ import annotations

from ..core.models import Setting
from ..core.schemas import (
    DividendRecord,
    SettingsRead,
    TargetIndexAllocation,
)


def to_settings_read(setting: Setting) -> SettingsRead:
    """Setting 모델을 SettingsRead 스키마로 변환."""
    allocations_raw = setting.target_index_allocations or []
    allocations = [
        TargetIndexAllocation(**item) for item in allocations_raw
    ]

    dividends_raw = setting.dividends or []
    if not dividends_raw and setting.dividend_year is not None and setting.dividend_total is not None:
        dividends_raw = [{"year": setting.dividend_year, "total": setting.dividend_total}]
    dividends = [
        DividendRecord(**item) for item in dividends_raw
    ]
    
    return SettingsRead(
        target_index_allocations=allocations,
        server_url=setting.server_url,
        dividend_year=setting.dividend_year,
        dividend_total=setting.dividend_total,
        dividends=dividends,
        usd_fx_base=setting.usd_fx_base,
        usd_fx_now=setting.usd_fx_now,
        benchmark_name=setting.benchmark_name,
        benchmark_return=setting.benchmark_return,
    )
