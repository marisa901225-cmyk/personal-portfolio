import logging
from sqlalchemy.orm import Session
from fastapi import HTTPException

from ..core.models import Setting
from ..core.time_utils import utcnow
from ..core.schemas import (
    SettingsRead,
    SettingsUpdate,
    TargetIndexAllocation,
    DividendRecord,
)
from .users import get_or_create_single_user
from .benchmark import compute_calendar_year_total_return, DEFAULT_BENCHMARK_NAME
from .kis_secret_store import (
    KIS_SECRET_FIELDS,
    decrypt_kis_secret,
    encrypt_kis_secret,
    is_kis_secret_encrypted,
)

logger = logging.getLogger(__name__)

def _normalize_benchmark_name(name: str) -> str:
    return name.replace(" ", "").upper()

def _mask_secret(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 4:
        return "***"
    return f"{value[:2]}***{value[-2:]}"

def _safe_decrypt_secret(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return decrypt_kis_secret(value)
    except Exception as exc:
        logger.warning("KIS secret decrypt failed: %s", exc)
        return None

def _encrypt_secret_or_raise(value: str | None) -> str | None:
    if value is None:
        return None
    value_str = str(value).strip()
    if not value_str:
        return None
    try:
        return encrypt_kis_secret(value_str)
    except Exception as exc:
        logger.warning("KIS secret encryption failed: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="KIS token key not configured or invalid",
        ) from exc

def _maybe_encrypt_legacy_kis_secrets(setting: Setting, db: Session) -> None:
    changed = False
    for field in KIS_SECRET_FIELDS:
        value = getattr(setting, field, None)
        if not value or is_kis_secret_encrypted(value):
            continue
        try:
            encrypted = encrypt_kis_secret(value)
        except Exception as exc:
            logger.warning("KIS secret migration skipped: %s", exc)
            return
        if encrypted and encrypted != value:
            setattr(setting, field, encrypted)
            changed = True
    if changed:
        setting.updated_at = utcnow()
        db.commit()
        db.refresh(setting)


def _is_default_benchmark_name(name: str) -> bool:
    normalized = _normalize_benchmark_name(name)
    base = _normalize_benchmark_name(DEFAULT_BENCHMARK_NAME)
    return normalized.startswith(base)


def _should_refresh_benchmark(setting: Setting) -> bool:
    """연간 벤치마크 갱신 필요 여부 판단 (연 1회만)"""
    if setting.benchmark_name and not _is_default_benchmark_name(setting.benchmark_name):
        return False
    if setting.benchmark_return is None:
        return True
    if setting.benchmark_updated_at is None:
        return True
    # 연도가 바뀌었을 때만 갱신 (연 1회)
    return setting.benchmark_updated_at.year != utcnow().year


def refresh_benchmark_if_needed(setting: Setting, db: Session) -> None:
    if not _should_refresh_benchmark(setting):
        return
    try:
        label, benchmark_return, _ = compute_calendar_year_total_return()
    except Exception as exc:
        logger.warning("Benchmark update failed: %s", exc)
        benchmark_return = None
        label = None

    # 성공/실패 상관없이 updated_at 갱신 (오늘은 더 이상 시도 안 함)
    setting.benchmark_updated_at = utcnow()
    if label:
        setting.benchmark_name = label
    if benchmark_return is not None:
        setting.benchmark_return = benchmark_return
    db.commit()
    db.refresh(setting)


def get_settings(db: Session, user_id: int) -> Setting:
    setting = (
        db.query(Setting)
        .filter(Setting.user_id == user_id)
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
            user_id=user_id,
            target_index_allocations=[a.model_dump() for a in default_allocations],
            server_url=None,
        )
        db.add(setting)
        db.commit()
        db.refresh(setting)
    
    refresh_benchmark_if_needed(setting, db)
    _maybe_encrypt_legacy_kis_secrets(setting, db)
    return setting


def update_settings(db: Session, user_id: int, payload: SettingsUpdate) -> Setting:
    setting = (
        db.query(Setting)
        .filter(Setting.user_id == user_id)
        .order_by(Setting.id.asc())
        .first()
    )
    if not setting:
        setting = Setting(user_id=user_id)
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
        setting.benchmark_updated_at = utcnow()

    if "kis_app" in payload.model_fields_set:
        setting.kis_app = _encrypt_secret_or_raise(payload.kis_app)
    if "kis_sec" in payload.model_fields_set:
        setting.kis_sec = _encrypt_secret_or_raise(payload.kis_sec)
    if "kis_acct_stock" in payload.model_fields_set:
        setting.kis_acct_stock = _encrypt_secret_or_raise(payload.kis_acct_stock)
    if "kis_prod" in payload.model_fields_set:
        setting.kis_prod = _encrypt_secret_or_raise(payload.kis_prod)
    if "kis_htsid" in payload.model_fields_set:
        setting.kis_htsid = _encrypt_secret_or_raise(payload.kis_htsid)
    if "kis_agent" in payload.model_fields_set:
        setting.kis_agent = _encrypt_secret_or_raise(payload.kis_agent)
    if "kis_prod_url" in payload.model_fields_set:
        setting.kis_prod_url = payload.kis_prod_url
    if "kis_ops_url" in payload.model_fields_set:
        setting.kis_ops_url = payload.kis_ops_url
    if "kis_vps_url" in payload.model_fields_set:
        setting.kis_vps_url = payload.kis_vps_url
    if "kis_vops_url" in payload.model_fields_set:
        setting.kis_vops_url = payload.kis_vops_url

    setting.updated_at = utcnow()
    db.commit()
    db.refresh(setting)
    return setting


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
        kis_app=_mask_secret(_safe_decrypt_secret(setting.kis_app)),
        kis_sec=_mask_secret(_safe_decrypt_secret(setting.kis_sec)),
        kis_acct_stock=_mask_secret(_safe_decrypt_secret(setting.kis_acct_stock)),
        kis_prod=_mask_secret(_safe_decrypt_secret(setting.kis_prod)),
        kis_htsid=_mask_secret(_safe_decrypt_secret(setting.kis_htsid)),
        kis_prod_url=setting.kis_prod_url,
        kis_ops_url=setting.kis_ops_url,
        kis_vps_url=setting.kis_vps_url,
        kis_vops_url=setting.kis_vops_url,
        kis_agent=_mask_secret(_safe_decrypt_secret(setting.kis_agent)),
    )
