from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from ...core.db import SessionLocal
from ...core.models_misc import KrOptionBoardSnapshot
from .kr_derivatives_weekly_analysis import (
    _build_weekly_briefing_lines,
    _build_weekly_comparison,
    _has_activity,
    _score_week,
)

logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")

SNAPSHOT_DIR = Path(__file__).resolve().parents[2] / "storage" / "market_sentiment"
SNAPSHOT_FILE = SNAPSHOT_DIR / "kr_option_board_snapshots.jsonl"
_LEGACY_MIGRATION_DONE = False
_WEEKLY_BRIEFING_LOOKBACK_DAYS = 45


def _to_int(value: Any) -> int:
    if value is None:
        return 0
    try:
        return int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return 0


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _next_month_yyyymm(yyyymm: str) -> str:
    """YYYYMM 문자열의 다음 달(YYYYMM)을 반환한다."""
    if len(yyyymm) != 6 or not yyyymm.isdigit():
        now = datetime.now(KST)
        yyyymm = now.strftime("%Y%m")
    year = int(yyyymm[:4])
    month = int(yyyymm[4:6])
    if month == 12:
        return f"{year + 1}01"
    return f"{year}{month + 1:02d}"


@dataclass
class OptionBoardSnapshot:
    collected_at: str
    trading_date: str
    maturity_month: str
    market_cls: str
    call_bid_total: int
    call_ask_total: int
    put_bid_total: int
    put_ask_total: int
    call_oi_change_total: int
    put_oi_change_total: int
    bid_pressure: float
    oi_pressure: float
    put_call_bid_ratio: float

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "OptionBoardSnapshot":
        return cls(
            collected_at=str(payload.get("collected_at") or ""),
            trading_date=str(payload.get("trading_date") or ""),
            maturity_month=str(payload.get("maturity_month") or ""),
            market_cls=str(payload.get("market_cls") or ""),
            call_bid_total=_to_int(payload.get("call_bid_total")),
            call_ask_total=_to_int(payload.get("call_ask_total")),
            put_bid_total=_to_int(payload.get("put_bid_total")),
            put_ask_total=_to_int(payload.get("put_ask_total")),
            call_oi_change_total=_to_int(payload.get("call_oi_change_total")),
            put_oi_change_total=_to_int(payload.get("put_oi_change_total")),
            bid_pressure=float(_to_float(payload.get("bid_pressure")) or 0.0),
            oi_pressure=float(_to_float(payload.get("oi_pressure")) or 0.0),
            put_call_bid_ratio=float(_to_float(payload.get("put_call_bid_ratio")) or 1.0),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)



def _ensure_snapshot_dir() -> None:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)


def _as_kst(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=KST)
    return dt.astimezone(KST)


def _normalize_reference_time(value: Optional[datetime] = None) -> datetime:
    base = value or datetime.now(KST)
    return _as_kst(base)


def _to_kst_naive(dt: datetime) -> datetime:
    """datetime을 KST naive로 정규화한다."""
    return _as_kst(dt).replace(tzinfo=None)


def _parse_snapshot_collected_at(value: str) -> datetime:
    """스냅샷 문자열 시각을 KST naive datetime으로 변환한다."""
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return _normalize_reference_time().replace(tzinfo=None)
    return _as_kst(dt).replace(tzinfo=None)


def _snapshot_collected_at_for_compare(snapshot: OptionBoardSnapshot) -> Optional[datetime]:
    try:
        return _as_kst(datetime.fromisoformat(snapshot.collected_at))
    except ValueError:
        return None


def _row_to_snapshot(row: KrOptionBoardSnapshot) -> OptionBoardSnapshot:
    collected_at = _as_kst(row.collected_at)

    return OptionBoardSnapshot(
        collected_at=collected_at.isoformat(),
        trading_date=row.trading_date,
        maturity_month=row.maturity_month,
        market_cls=row.market_cls,
        call_bid_total=row.call_bid_total,
        call_ask_total=row.call_ask_total,
        put_bid_total=row.put_bid_total,
        put_ask_total=row.put_ask_total,
        call_oi_change_total=row.call_oi_change_total,
        put_oi_change_total=row.put_oi_change_total,
        bid_pressure=row.bid_pressure,
        oi_pressure=row.oi_pressure,
        put_call_bid_ratio=row.put_call_bid_ratio,
    )


def _upsert_snapshot_row(db: Session, snapshot: OptionBoardSnapshot) -> None:
    row = (
        db.query(KrOptionBoardSnapshot)
        .filter(KrOptionBoardSnapshot.trading_date == snapshot.trading_date)
        .first()
    )
    collected_at = _parse_snapshot_collected_at(snapshot.collected_at)
    values = {
        "collected_at": collected_at,
        "maturity_month": snapshot.maturity_month,
        "market_cls": snapshot.market_cls,
        "call_bid_total": snapshot.call_bid_total,
        "call_ask_total": snapshot.call_ask_total,
        "put_bid_total": snapshot.put_bid_total,
        "put_ask_total": snapshot.put_ask_total,
        "call_oi_change_total": snapshot.call_oi_change_total,
        "put_oi_change_total": snapshot.put_oi_change_total,
        "bid_pressure": snapshot.bid_pressure,
        "oi_pressure": snapshot.oi_pressure,
        "put_call_bid_ratio": snapshot.put_call_bid_ratio,
    }

    if row is None:
        db.add(
            KrOptionBoardSnapshot(
                trading_date=snapshot.trading_date,
                **values,
            )
        )
        return

    for key, value in values.items():
        setattr(row, key, value)


def _load_legacy_file_snapshots() -> list[OptionBoardSnapshot]:
    """기존 JSONL 파일 스냅샷을 로드한다 (DB 이관용)."""
    if not SNAPSHOT_FILE.exists():
        return []

    snapshots: list[OptionBoardSnapshot] = []
    with open(SNAPSHOT_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
                snapshots.append(OptionBoardSnapshot.from_dict(raw))
            except Exception:
                continue
    return snapshots


def _migrate_legacy_file_cache_to_db_if_needed() -> None:
    """
    JSONL 기반 구형 스냅샷 캐시를 DB로 1회 이관한다.

    - DB에 데이터가 이미 있으면 이관하지 않는다.
    - 프로세스 수명 동안 한 번만 체크한다.
    """
    global _LEGACY_MIGRATION_DONE
    if _LEGACY_MIGRATION_DONE:
        return
    _LEGACY_MIGRATION_DONE = True

    if not SNAPSHOT_FILE.exists():
        return

    legacy = _load_legacy_file_snapshots()
    if not legacy:
        return

    try:
        with SessionLocal() as db:
            exists = db.query(KrOptionBoardSnapshot.id).first()
            if exists:
                return
            for snap in legacy:
                _upsert_snapshot_row(db, snap)
            db.commit()
            logger.info("Migrated %s KR option snapshots from legacy JSONL cache into DB.", len(legacy))
    except Exception as e:
        logger.error("Failed to migrate legacy option snapshot cache: %s", e)


def _normalize_option_rows(rows: Any) -> list[Dict[str, Any]]:
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list):
        return []
    return [item for item in rows if isinstance(item, dict)]


def _sum_option_value(rows: list[Dict[str, Any]], field: str) -> int:
    return sum(_to_int(item.get(field)) for item in rows)


def _calculate_bid_pressure(call_bid_total: int, put_bid_total: int) -> float:
    bid_total = call_bid_total + put_bid_total
    if bid_total == 0:
        return 0.0
    return (call_bid_total - put_bid_total) / bid_total


def _calculate_oi_pressure(call_oi_change_total: int, put_oi_change_total: int) -> float:
    oi_total = abs(call_oi_change_total) + abs(put_oi_change_total)
    if oi_total == 0:
        return 0.0
    return (call_oi_change_total - put_oi_change_total) / oi_total


def _calculate_put_call_bid_ratio(call_bid_total: int, put_bid_total: int) -> float:
    if call_bid_total > 0:
        return put_bid_total / call_bid_total
    return 999.0 if put_bid_total > 0 else 1.0


def _aggregate_option_board(payload: Dict[str, Any], *, maturity_month: str, market_cls: str) -> OptionBoardSnapshot:
    calls = _normalize_option_rows(payload.get("output1"))
    puts = _normalize_option_rows(payload.get("output2"))

    call_bid_total = _sum_option_value(calls, "total_bidp_rsqn")
    call_ask_total = _sum_option_value(calls, "total_askp_rsqn")
    put_bid_total = _sum_option_value(puts, "total_bidp_rsqn")
    put_ask_total = _sum_option_value(puts, "total_askp_rsqn")
    call_oi_change_total = _sum_option_value(calls, "otst_stpl_qty_icdc")
    put_oi_change_total = _sum_option_value(puts, "otst_stpl_qty_icdc")

    now = _normalize_reference_time()
    return OptionBoardSnapshot(
        collected_at=now.isoformat(),
        trading_date=now.strftime("%Y%m%d"),
        maturity_month=maturity_month,
        market_cls=market_cls,
        call_bid_total=call_bid_total,
        call_ask_total=call_ask_total,
        put_bid_total=put_bid_total,
        put_ask_total=put_ask_total,
        call_oi_change_total=call_oi_change_total,
        put_oi_change_total=put_oi_change_total,
        bid_pressure=_calculate_bid_pressure(call_bid_total, put_bid_total),
        oi_pressure=_calculate_oi_pressure(call_oi_change_total, put_oi_change_total),
        put_call_bid_ratio=_calculate_put_call_bid_ratio(call_bid_total, put_bid_total),
    )


def _append_snapshot(snapshot: OptionBoardSnapshot) -> None:
    _migrate_legacy_file_cache_to_db_if_needed()
    with SessionLocal() as db:
        _upsert_snapshot_row(db, snapshot)
        db.commit()


def _load_snapshots(
    days: int = 35,
    *,
    reference_time: Optional[datetime] = None,
) -> list[OptionBoardSnapshot]:
    _migrate_legacy_file_cache_to_db_if_needed()
    cutoff = _to_kst_naive(_normalize_reference_time(reference_time)) - timedelta(days=max(days, 1))

    try:
        with SessionLocal() as db:
            rows = (
                db.query(KrOptionBoardSnapshot)
                .filter(KrOptionBoardSnapshot.collected_at >= cutoff)
                .order_by(KrOptionBoardSnapshot.trading_date.asc())
                .all()
            )
            return [_row_to_snapshot(row) for row in rows]
    except Exception as e:
        logger.error("Failed to load KR option snapshots from DB: %s", e)
        return []


def _select_latest_snapshot_before(
    snapshots: list[OptionBoardSnapshot],
    base: datetime,
) -> Optional[OptionBoardSnapshot]:
    candidates: list[tuple[datetime, OptionBoardSnapshot]] = []
    for snap in snapshots:
        collected_at = _snapshot_collected_at_for_compare(snap)
        if collected_at is None:
            continue
        if collected_at <= base:
            candidates.append((collected_at, snap))

    if not candidates:
        return None

    active_candidates = [
        (collected_at, snap) for collected_at, snap in candidates if _has_activity(snap)
    ]
    selection_pool = active_candidates or candidates
    _, latest = max(selection_pool, key=lambda item: item[0])
    return latest


def _snapshot_summary_payload(snapshot: OptionBoardSnapshot) -> Dict[str, Any]:
    return {
        "source": "snapshot_db",
        "trading_date": snapshot.trading_date,
        "maturity_month": snapshot.maturity_month,
        "call_bid_total": snapshot.call_bid_total,
        "call_ask_total": snapshot.call_ask_total,
        "put_bid_total": snapshot.put_bid_total,
        "put_ask_total": snapshot.put_ask_total,
        "call_oi_change_total": snapshot.call_oi_change_total,
        "put_oi_change_total": snapshot.put_oi_change_total,
        "put_call_bid_ratio": snapshot.put_call_bid_ratio,
        "bid_pressure": snapshot.bid_pressure,
        "oi_pressure": snapshot.oi_pressure,
    }


def get_latest_option_snapshot_summary(
    now: Optional[datetime] = None,
    *,
    days: int = 14,
) -> Optional[Dict[str, Any]]:
    """
    최근 옵션 전광판 스냅샷(장마감 수집본) 1건을 요약 형태로 반환한다.

    모닝 브리핑(07:00)에서 실시간 전광판 대신 전일 장마감 수치를 쓰기 위한 용도.
    """
    base = _normalize_reference_time(now)

    snapshots = _load_snapshots(days=max(days, 1), reference_time=base)
    if not snapshots:
        return None

    latest = _select_latest_snapshot_before(snapshots, base)
    if latest is None:
        return None
    return _snapshot_summary_payload(latest)


async def collect_option_board_snapshot(
    maturity_month: Optional[str] = None,
    market_cls: str = "",
) -> Optional[OptionBoardSnapshot]:
    from backend.integrations.kis.kis_client import get_options_display_board

    async def _fetch_snapshot(target_maturity: str) -> Optional[OptionBoardSnapshot]:
        payload = await get_options_display_board(
            maturity_month=target_maturity,
            market_cls=market_cls,
            call_put_cls="CO",
        )
        if not payload or payload.get("rt_cd") != "0":
            logger.warning("Option board snapshot collection failed: %s", (payload or {}).get("msg1"))
            return None
        return _aggregate_option_board(
            payload,
            maturity_month=target_maturity,
            market_cls=market_cls,
        )

    target_maturity = maturity_month or _normalize_reference_time().strftime("%Y%m")
    snapshot = await _fetch_snapshot(target_maturity)
    if snapshot is None:
        return None

    # 만기 지난 월(예: 2월 만기 후 202602) 조회 시 0행 데이터가 내려올 수 있어
    # 기본값(당월) 조회가 비어 있으면 다음 달 만기월로 1회 재조회한다.
    if maturity_month is None and not _has_activity(snapshot):
        next_maturity = _next_month_yyyymm(target_maturity)
        if next_maturity != target_maturity:
            fallback_snapshot = await _fetch_snapshot(next_maturity)
            if fallback_snapshot and _has_activity(fallback_snapshot):
                logger.info(
                    "Option board snapshot switched maturity: %s -> %s (primary empty)",
                    target_maturity,
                    next_maturity,
                )
                snapshot = fallback_snapshot

    if not _has_activity(snapshot):
        logger.warning(
            "Option board snapshot skipped (empty totals): date=%s maturity=%s",
            snapshot.trading_date,
            snapshot.maturity_month,
        )
        return None

    _append_snapshot(snapshot)
    logger.info("Option board snapshot saved: date=%s pcr=%.3f", snapshot.trading_date, snapshot.put_call_bid_ratio)
    return snapshot


def _parse_kospi_close(row: Dict[str, Any]) -> Optional[float]:
    for key in ("bstp_nmix_prpr", "stck_clpr", "close"):
        val = _to_float(row.get(key))
        if val is not None:
            return val
    return None


async def _fetch_kospi_week_returns(week_windows: list[tuple[str, str]]) -> Dict[tuple[str, str], Optional[float]]:
    from backend.integrations.kis.kis_index import fetch_index_daily_prices

    if not week_windows:
        return {}
    latest_end = max(end for _, end in week_windows)
    payload = await asyncio.to_thread(fetch_index_daily_prices, "0001", latest_end, "D")
    rows = (payload or {}).get("output2") or []
    if isinstance(rows, dict):
        rows = [rows]

    result: Dict[tuple[str, str], Optional[float]] = {}
    for start, end in week_windows:
        closes: list[tuple[str, float]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            date = str(row.get("stck_bsop_date") or "")
            if start <= date <= end:
                close = _parse_kospi_close(row)
                if close is not None:
                    closes.append((date, close))
        closes.sort(key=lambda item: item[0])
        if len(closes) < 2 or closes[0][1] == 0:
            result[(start, end)] = None
            continue
        first = closes[0][1]
        last = closes[-1][1]
        result[(start, end)] = ((last - first) / first) * 100.0
    return result


async def build_weekly_derivatives_briefing(now: Optional[datetime] = None) -> Optional[str]:
    base = _normalize_reference_time(now)
    snapshots = _load_snapshots(days=_WEEKLY_BRIEFING_LOOKBACK_DAYS, reference_time=base)
    comparison = _build_weekly_comparison(snapshots, base=base)
    if comparison is None:
        return None

    returns = await _fetch_kospi_week_returns([comparison.last_window, comparison.prev_window])
    lines = _build_weekly_briefing_lines(comparison, returns)
    return "\n".join(lines)


__all__ = [
    "collect_option_board_snapshot",
    "build_weekly_derivatives_briefing",
    "get_latest_option_snapshot_summary",
]
