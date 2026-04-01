from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from statistics import mean
from typing import Any, Dict, Optional, Protocol

_MIN_WEEKLY_SNAPSHOTS = 5
_EMPTY_WEEK_STATS = {
    "count": 0,
    "avg_pcr": 1.0,
    "avg_bid_pressure": 0.0,
    "avg_oi_pressure": 0.0,
    "sum_call_oi_change": 0,
    "sum_put_oi_change": 0,
    "sum_call_bid": 0,
    "sum_put_bid": 0,
}


class SnapshotLike(Protocol):
    trading_date: str
    put_call_bid_ratio: float
    bid_pressure: float
    oi_pressure: float
    call_oi_change_total: int
    put_oi_change_total: int
    call_bid_total: int
    put_bid_total: int
    call_ask_total: int
    put_ask_total: int


@dataclass(frozen=True)
class WeeklyComparison:
    last_week_key: tuple[int, int]
    prev_week_key: tuple[int, int]
    last_week_snaps: list[SnapshotLike]
    prev_week_snaps: list[SnapshotLike]
    last_week_stats: Dict[str, Any]
    prev_week_stats: Dict[str, Any]
    last_week_score: Dict[str, Any]
    prev_week_score: Dict[str, Any]
    last_window: tuple[str, str]
    prev_window: tuple[str, str]


def _week_key(trading_date: str) -> Optional[tuple[int, int]]:
    if len(trading_date) != 8:
        return None
    try:
        dt = datetime.strptime(trading_date, "%Y%m%d")
    except ValueError:
        return None
    iso = dt.isocalendar()
    return iso.year, iso.week


def _week_label(key: tuple[int, int]) -> str:
    year, week = key
    return f"{year}년 {week}주차"


def _has_activity(snapshot: SnapshotLike) -> bool:
    total = (
        snapshot.call_bid_total
        + snapshot.call_ask_total
        + snapshot.put_bid_total
        + snapshot.put_ask_total
    )
    return total > 0


def _week_stats(snaps: list[SnapshotLike]) -> Dict[str, Any]:
    if not snaps:
        return dict(_EMPTY_WEEK_STATS)

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


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(min(value, upper), lower)


def _score_week(stats: Dict[str, Any]) -> Dict[str, Any]:
    pcr = float(stats.get("avg_pcr", 1.0))
    bid_pressure = float(stats.get("avg_bid_pressure", 0.0))
    oi_pressure = float(stats.get("avg_oi_pressure", 0.0))

    pcr_component = _clamp((1.0 - pcr) * 40.0, -25.0, 25.0)
    bid_component = _clamp(bid_pressure * 30.0, -20.0, 20.0)
    oi_component = _clamp(oi_pressure * 30.0, -20.0, 20.0)
    score = _clamp(pcr_component + bid_component + oi_component, -100.0, 100.0)

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


def _group_snapshots_by_week(
    snapshots: list[SnapshotLike],
) -> dict[tuple[int, int], list[SnapshotLike]]:
    grouped: dict[tuple[int, int], list[SnapshotLike]] = {}
    for snap in snapshots:
        key = _week_key(snap.trading_date)
        if key is None:
            continue
        grouped.setdefault(key, []).append(snap)
    return grouped


def _select_comparison_week_keys(
    grouped: dict[tuple[int, int], list[SnapshotLike]],
    base: datetime,
) -> Optional[tuple[tuple[int, int], tuple[int, int]]]:
    current_key = base.isocalendar()[:2]
    complete_weeks = sorted(key for key in grouped if key != current_key)
    if len(complete_weeks) < 2:
        return None
    return complete_weeks[-1], complete_weeks[-2]


def _sort_snapshots_by_trading_date(snapshots: list[SnapshotLike]) -> list[SnapshotLike]:
    return sorted(snapshots, key=lambda item: item.trading_date)


def _snapshot_window(snapshots: list[SnapshotLike]) -> tuple[str, str]:
    return snapshots[0].trading_date, snapshots[-1].trading_date


def _build_weekly_comparison(
    snapshots: list[SnapshotLike],
    *,
    base: datetime,
) -> Optional[WeeklyComparison]:
    active_snapshots = [snap for snap in snapshots if _has_activity(snap)]
    if len(active_snapshots) < _MIN_WEEKLY_SNAPSHOTS:
        return None

    grouped = _group_snapshots_by_week(active_snapshots)
    if len(grouped) < 2:
        return None

    week_keys = _select_comparison_week_keys(grouped, base)
    if week_keys is None:
        return None

    last_week_key, prev_week_key = week_keys
    last_week_snaps = _sort_snapshots_by_trading_date(grouped[last_week_key])
    prev_week_snaps = _sort_snapshots_by_trading_date(grouped[prev_week_key])
    last_week_stats = _week_stats(last_week_snaps)
    prev_week_stats = _week_stats(prev_week_snaps)

    return WeeklyComparison(
        last_week_key=last_week_key,
        prev_week_key=prev_week_key,
        last_week_snaps=last_week_snaps,
        prev_week_snaps=prev_week_snaps,
        last_week_stats=last_week_stats,
        prev_week_stats=prev_week_stats,
        last_week_score=_score_week(last_week_stats),
        prev_week_score=_score_week(prev_week_stats),
        last_window=_snapshot_window(last_week_snaps),
        prev_window=_snapshot_window(prev_week_snaps),
    )


def _format_weekly_briefing_date(raw: str) -> str:
    if len(raw) != 8:
        return raw
    return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"


def _build_weekly_briefing_lines(
    comparison: WeeklyComparison,
    returns: Dict[tuple[str, str], Optional[float]],
) -> list[str]:
    score_diff = float(comparison.last_week_score["score"]) - float(comparison.prev_week_score["score"])
    pcr_diff = float(comparison.last_week_stats["avg_pcr"]) - float(comparison.prev_week_stats["avg_pcr"])
    oi_gap_last = int(comparison.last_week_stats["sum_put_oi_change"]) - int(comparison.last_week_stats["sum_call_oi_change"])
    oi_gap_prev = int(comparison.prev_week_stats["sum_put_oi_change"]) - int(comparison.prev_week_stats["sum_call_oi_change"])

    lines = [
        "<b>[주간 국내 파생심리 브리핑]</b>",
        (
            f"- 지난주({_week_label(comparison.last_week_key)}): "
            f"점수 {comparison.last_week_score['score']} / {comparison.last_week_score['regime']}"
        ),
        (
            f"- 전주({_week_label(comparison.prev_week_key)}): "
            f"점수 {comparison.prev_week_score['score']} / {comparison.prev_week_score['regime']}"
        ),
        f"- 점수 변화: {score_diff:+.2f}p",
        (
            f"- Put/Call(매수잔량) 평균: {comparison.last_week_stats['avg_pcr']:.2f} "
            f"(전주 대비 {pcr_diff:+.2f})"
        ),
        f"- 풋-콜 OI증감 격차: {oi_gap_last:+,} (전주 {oi_gap_prev:+,})",
        (
            f"- 관측 구간: 지난주 {_format_weekly_briefing_date(comparison.last_window[0])}"
            f"~{_format_weekly_briefing_date(comparison.last_window[1])}, "
            f"전주 {_format_weekly_briefing_date(comparison.prev_window[0])}"
            f"~{_format_weekly_briefing_date(comparison.prev_window[1])}"
        ),
    ]

    ret_last = returns.get(comparison.last_window)
    ret_prev = returns.get(comparison.prev_window)
    if ret_last is not None:
        lines.append(f"- 코스피 수익률: 지난주 {ret_last:+.2f}%")
    if ret_prev is not None:
        lines.append(f"- 코스피 수익률: 전주 {ret_prev:+.2f}%")
    return lines


__all__ = [
    "WeeklyComparison",
    "_build_weekly_briefing_lines",
    "_build_weekly_comparison",
    "_has_activity",
    "_score_week",
]
