import logging
from typing import Optional, Tuple, Dict, Any

from backend.integrations.fred.fred_client import fred_client
from backend.integrations.telegram import send_telegram_message
from backend.core.db import SessionLocal
from backend.core.models import EconRateState
from backend.core.time_utils import utcnow
from .ecos_client import ecos_client

logger = logging.getLogger(__name__)

_STATE_NAME = "default"


def _load_state(db) -> Optional[EconRateState]:
    return (
        db.query(EconRateState)
        .filter(EconRateState.name == _STATE_NAME)
        .first()
    )


def _get_fed_funds_latest() -> Tuple[Optional[float], Optional[str]]:
    if not fred_client.is_available:
        return None, None
    series = fred_client.get_series("FEDFUNDS")
    if series is None or series.empty:
        return None, None
    series = series.dropna()
    if series.empty:
        return None, None
    value = float(series.iloc[-1])
    idx = series.index[-1]
    date_str = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)
    return value, date_str


def _parse_bok_date(row: Dict[str, Any]) -> Optional[str]:
    for key in ("TIME", "STAT_DATE", "DATE", "TIME_PERIOD"):
        value = row.get(key)
        if value:
            return str(value)
    return None


async def _get_bok_base_rate_latest() -> Tuple[Optional[float], Optional[str]]:
    row = await ecos_client.get_base_rate_row()
    if not row or "DATA_VALUE" not in row:
        return None, None
    try:
        value = float(row["DATA_VALUE"])
    except (TypeError, ValueError):
        return None, None
    date_str = _parse_bok_date(row)
    return value, date_str


def _is_changed(prev: Optional[float], curr: Optional[float]) -> bool:
    if prev is None or curr is None:
        return False
    return abs(prev - curr) > 1e-9


def _format_change(name: str, prev: float, curr: float, date_str: Optional[str]) -> str:
    delta = curr - prev
    date_line = f"\n- 기준일: {date_str}" if date_str else ""
    return (
        f"📌 <b>{name} 변동</b>\n"
        f"- {prev:.2f}% → {curr:.2f}% ({delta:+.2f}%p)"
        f"{date_line}"
    )


def _merge_values(
    prev: Optional[EconRateState],
    fed_rate: Optional[float],
    fed_date: Optional[str],
    bok_rate: Optional[float],
    bok_date: Optional[str],
) -> tuple[Optional[float], Optional[str], Optional[float], Optional[str]]:
    if prev is None:
        return fed_rate, fed_date, bok_rate, bok_date

    if fed_rate is None:
        fed_rate = prev.fed_funds_rate
        fed_date = prev.fed_funds_date
    if bok_rate is None:
        bok_rate = prev.bok_base_rate
        bok_date = prev.bok_base_date

    return fed_rate, fed_date, bok_rate, bok_date


async def check_rate_changes_and_notify(send_on_init: bool = False) -> bool:
    """
    한국은행 기준금리/미국 기준금리 변경 여부를 체크하고 변동 시 텔레그램 알림을 전송합니다.

    Args:
        send_on_init: 최초 실행 시에도 알림을 보낼지 여부 (기본 False)

    Returns:
        알림을 전송했으면 True, 아니면 False
    """
    fed_rate, fed_date = _get_fed_funds_latest()
    bok_rate, bok_date = await _get_bok_base_rate_latest()

    if fed_rate is None and bok_rate is None:
        logger.warning("Rate check skipped: no data available (FRED/ECOS).")
        return False

    messages: list[str] = []

    with SessionLocal() as db:
        prev = _load_state(db)

        if prev is None:
            if send_on_init:
                if bok_rate is not None:
                    messages.append(
                        _format_change("한국은행 기준금리", bok_rate, bok_rate, bok_date)
                    )
                if fed_rate is not None:
                    messages.append(
                        _format_change("미국 기준금리(Fed Funds)", fed_rate, fed_rate, fed_date)
                    )

            merged_fed, merged_fed_date, merged_bok, merged_bok_date = _merge_values(
                prev, fed_rate, fed_date, bok_rate, bok_date
            )

            state = EconRateState(
                name=_STATE_NAME,
                fed_funds_rate=merged_fed,
                fed_funds_date=merged_fed_date,
                bok_base_rate=merged_bok,
                bok_base_date=merged_bok_date,
                updated_at=utcnow(),
                created_at=utcnow(),
            )
            db.add(state)
            db.commit()

            if messages:
                await send_telegram_message("\n\n".join(messages))
                return True
            return False

        if _is_changed(prev.bok_base_rate, bok_rate):
            messages.append(
                _format_change(
                    "한국은행 기준금리",
                    prev.bok_base_rate,  # type: ignore[arg-type]
                    bok_rate,  # type: ignore[arg-type]
                    bok_date,
                )
            )

        if _is_changed(prev.fed_funds_rate, fed_rate):
            messages.append(
                _format_change(
                    "미국 기준금리(Fed Funds)",
                    prev.fed_funds_rate,  # type: ignore[arg-type]
                    fed_rate,  # type: ignore[arg-type]
                    fed_date,
                )
            )

        merged_fed, merged_fed_date, merged_bok, merged_bok_date = _merge_values(
            prev, fed_rate, fed_date, bok_rate, bok_date
        )

        prev.fed_funds_rate = merged_fed
        prev.fed_funds_date = merged_fed_date
        prev.bok_base_rate = merged_bok
        prev.bok_base_date = merged_bok_date
        prev.updated_at = utcnow()
        db.commit()

    if not messages:
        return False

    await send_telegram_message("\n\n".join(messages))
    return True


__all__ = ["check_rate_changes_and_notify"]
