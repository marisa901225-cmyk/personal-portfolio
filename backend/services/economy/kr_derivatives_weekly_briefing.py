from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")

SNAPSHOT_DIR = Path(__file__).resolve().parents[2] / "storage" / "market_sentiment"
SNAPSHOT_FILE = SNAPSHOT_DIR / "kr_option_board_snapshots.jsonl"


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


def _week_key(trading_date: str) -> Optional[tuple[int, int]]:
    if len(trading_date) != 8:
        return None
    try:
        dt = datetime.strptime(trading_date, "%Y%m%d").replace(tzinfo=KST)
    except ValueError:
        return None
    iso = dt.isocalendar()
    return (iso.year, iso.week)


def _week_label(key: tuple[int, int]) -> str:
    year, week = key
    return f"{year}년 {week}주차"


def _aggregate_option_board(payload: Dict[str, Any], *, maturity_month: str, market_cls: str) -> OptionBoardSnapshot:
    calls = payload.get("output1")
    puts = payload.get("output2")
    if isinstance(calls, dict):
        calls = [calls]
    if isinstance(puts, dict):
        puts = [puts]
    if not isinstance(calls, list):
        calls = []
    if not isinstance(puts, list):
        puts = []

    call_bid_total = sum(_to_int(item.get("total_bidp_rsqn")) for item in calls if isinstance(item, dict))
    call_ask_total = sum(_to_int(item.get("total_askp_rsqn")) for item in calls if isinstance(item, dict))
    put_bid_total = sum(_to_int(item.get("total_bidp_rsqn")) for item in puts if isinstance(item, dict))
    put_ask_total = sum(_to_int(item.get("total_askp_rsqn")) for item in puts if isinstance(item, dict))
    call_oi_change_total = sum(_to_int(item.get("otst_stpl_qty_icdc")) for item in calls if isinstance(item, dict))
    put_oi_change_total = sum(_to_int(item.get("otst_stpl_qty_icdc")) for item in puts if isinstance(item, dict))

    bid_total = call_bid_total + put_bid_total
    bid_pressure = 0.0 if bid_total == 0 else (call_bid_total - put_bid_total) / bid_total
    oi_total = abs(call_oi_change_total) + abs(put_oi_change_total)
    oi_pressure = 0.0 if oi_total == 0 else (call_oi_change_total - put_oi_change_total) / oi_total
    put_call_bid_ratio = (put_bid_total / call_bid_total) if call_bid_total > 0 else (999.0 if put_bid_total > 0 else 1.0)

    now = datetime.now(KST)
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
        bid_pressure=bid_pressure,
        oi_pressure=oi_pressure,
        put_call_bid_ratio=put_call_bid_ratio,
    )


def _append_snapshot(snapshot: OptionBoardSnapshot) -> None:
    _ensure_snapshot_dir()
    with open(SNAPSHOT_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(snapshot.to_dict(), ensure_ascii=False) + "\n")


def _load_snapshots(days: int = 35) -> list[OptionBoardSnapshot]:
    if not SNAPSHOT_FILE.exists():
        return []

    cutoff = datetime.now(KST) - timedelta(days=max(days, 1))
    snapshots: list[OptionBoardSnapshot] = []
    with open(SNAPSHOT_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
                snap = OptionBoardSnapshot.from_dict(raw)
                collected_at = datetime.fromisoformat(snap.collected_at)
                if collected_at.tzinfo is None:
                    collected_at = collected_at.replace(tzinfo=KST)
                else:
                    collected_at = collected_at.astimezone(KST)
                if collected_at < cutoff:
                    continue
                snapshots.append(snap)
            except Exception:
                continue

    dedup: dict[str, OptionBoardSnapshot] = {}
    for snap in snapshots:
        dedup[snap.trading_date] = snap
    ordered = list(dedup.values())
    ordered.sort(key=lambda item: item.trading_date)
    return ordered


async def collect_option_board_snapshot(
    maturity_month: Optional[str] = None,
    market_cls: str = "",
) -> Optional[OptionBoardSnapshot]:
    from backend.integrations.kis.kis_client import get_options_display_board

    now = datetime.now(KST)
    target_maturity = maturity_month or now.strftime("%Y%m")
    payload = await get_options_display_board(
        maturity_month=target_maturity,
        market_cls=market_cls,
        call_put_cls="CO",
    )
    if not payload or payload.get("rt_cd") != "0":
        logger.warning("Option board snapshot collection failed: %s", (payload or {}).get("msg1"))
        return None

    snapshot = _aggregate_option_board(
        payload,
        maturity_month=target_maturity,
        market_cls=market_cls,
    )
    _append_snapshot(snapshot)
    logger.info("Option board snapshot saved: date=%s pcr=%.3f", snapshot.trading_date, snapshot.put_call_bid_ratio)
    return snapshot


def _week_stats(snaps: list[OptionBoardSnapshot]) -> Dict[str, Any]:
    if not snaps:
        return {
            "count": 0,
            "avg_pcr": 1.0,
            "avg_bid_pressure": 0.0,
            "avg_oi_pressure": 0.0,
            "sum_call_oi_change": 0,
            "sum_put_oi_change": 0,
            "sum_call_bid": 0,
            "sum_put_bid": 0,
        }

    return {
        "count": len(snaps),
        "avg_pcr": mean(s.put_call_bid_ratio for s in snaps),
        "avg_bid_pressure": mean(s.bid_pressure for s in snaps),
        "avg_oi_pressure": mean(s.oi_pressure for s in snaps),
        "sum_call_oi_change": sum(s.call_oi_change_total for s in snaps),
        "sum_put_oi_change": sum(s.put_oi_change_total for s in snaps),
        "sum_call_bid": sum(s.call_bid_total for s in snaps),
        "sum_put_bid": sum(s.put_bid_total for s in snaps),
    }


def _score_week(stats: Dict[str, Any]) -> Dict[str, Any]:
    pcr = float(stats.get("avg_pcr", 1.0))
    bid_pressure = float(stats.get("avg_bid_pressure", 0.0))
    oi_pressure = float(stats.get("avg_oi_pressure", 0.0))

    pcr_component = max(min((1.0 - pcr) * 40.0, 25.0), -25.0)
    bid_component = max(min(bid_pressure * 30.0, 20.0), -20.0)
    oi_component = max(min(oi_pressure * 30.0, 20.0), -20.0)
    score = max(min(pcr_component + bid_component + oi_component, 100.0), -100.0)

    if score >= 25:
        regime = "상승 우위"
    elif score <= -25:
        regime = "하락 우위"
    else:
        regime = "중립"

    return {
        "score": round(score, 2),
        "regime": regime,
        "components": {
            "pcr": round(pcr_component, 2),
            "bid": round(bid_component, 2),
            "oi": round(oi_component, 2),
        },
    }


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
    base = now or datetime.now(KST)
    if base.tzinfo is None:
        base = base.replace(tzinfo=KST)
    else:
        base = base.astimezone(KST)

    snapshots = _load_snapshots(days=45)
    if len(snapshots) < 5:
        return None

    grouped: dict[tuple[int, int], list[OptionBoardSnapshot]] = {}
    for snap in snapshots:
        key = _week_key(snap.trading_date)
        if key is None:
            continue
        grouped.setdefault(key, []).append(snap)

    if len(grouped) < 2:
        return None

    current_key = base.isocalendar()[:2]
    complete_weeks = sorted(k for k in grouped.keys() if k != current_key)
    if len(complete_weeks) < 2:
        return None

    last_week_key = complete_weeks[-1]
    prev_week_key = complete_weeks[-2]
    last_week_snaps = sorted(grouped[last_week_key], key=lambda item: item.trading_date)
    prev_week_snaps = sorted(grouped[prev_week_key], key=lambda item: item.trading_date)

    last_week_stats = _week_stats(last_week_snaps)
    prev_week_stats = _week_stats(prev_week_snaps)
    last_week_score = _score_week(last_week_stats)
    prev_week_score = _score_week(prev_week_stats)

    last_window = (last_week_snaps[0].trading_date, last_week_snaps[-1].trading_date)
    prev_window = (prev_week_snaps[0].trading_date, prev_week_snaps[-1].trading_date)
    returns = await _fetch_kospi_week_returns([last_window, prev_window])

    score_diff = float(last_week_score["score"]) - float(prev_week_score["score"])
    pcr_diff = float(last_week_stats["avg_pcr"]) - float(prev_week_stats["avg_pcr"])
    oi_gap_last = int(last_week_stats["sum_put_oi_change"]) - int(last_week_stats["sum_call_oi_change"])
    oi_gap_prev = int(prev_week_stats["sum_put_oi_change"]) - int(prev_week_stats["sum_call_oi_change"])

    def _fmt_date(raw: str) -> str:
        if len(raw) != 8:
            return raw
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"

    lines = [
        "<b>[주간 국내 파생심리 브리핑]</b>",
        f"- 지난주({ _week_label(last_week_key) }): 점수 {last_week_score['score']} / {last_week_score['regime']}",
        f"- 전주({ _week_label(prev_week_key) }): 점수 {prev_week_score['score']} / {prev_week_score['regime']}",
        f"- 점수 변화: {score_diff:+.2f}p",
        (
            f"- Put/Call(매수잔량) 평균: {last_week_stats['avg_pcr']:.2f} "
            f"(전주 대비 {pcr_diff:+.2f})"
        ),
        (
            f"- 풋-콜 OI증감 격차: {oi_gap_last:+,} "
            f"(전주 {oi_gap_prev:+,})"
        ),
        (
            f"- 관측 구간: 지난주 {_fmt_date(last_window[0])}~{_fmt_date(last_window[1])}, "
            f"전주 {_fmt_date(prev_window[0])}~{_fmt_date(prev_window[1])}"
        ),
    ]

    ret_last = returns.get(last_window)
    ret_prev = returns.get(prev_window)
    if ret_last is not None:
        lines.append(f"- 코스피 수익률: 지난주 {ret_last:+.2f}%")
    if ret_prev is not None:
        lines.append(f"- 코스피 수익률: 전주 {ret_prev:+.2f}%")

    return "\n".join(lines)


__all__ = [
    "collect_option_board_snapshot",
    "build_weekly_derivatives_briefing",
]
