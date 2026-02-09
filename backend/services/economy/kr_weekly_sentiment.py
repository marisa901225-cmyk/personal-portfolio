from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta
from statistics import mean
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        cleaned = str(value).replace(",", "").strip()
        if cleaned == "":
            return None
        return float(cleaned)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int:
    parsed = _to_float(value)
    if parsed is None:
        return 0
    return int(parsed)


def _pick_number(row: Dict[str, Any], keys: tuple[str, ...]) -> Optional[float]:
    for key in keys:
        value = _to_float(row.get(key))
        if value is not None:
            return value
    return None


def _normalize_daily_rows(payload: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return []

    rows = payload.get("output2")
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list):
        return []

    normalized: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue

        close = _pick_number(row, ("futs_prpr", "stck_clpr", "close", "bstp_nmix_prpr"))
        if close is None:
            continue

        normalized.append(
            {
                "date": str(row.get("stck_bsop_date") or ""),
                "close": close,
                "volume": _pick_number(row, ("futs_trqu", "acml_vol", "acml_tr_pbmn")) or 0.0,
                "raw": row,
            }
        )

    normalized.sort(key=lambda item: item["date"], reverse=True)
    return normalized


def _compute_futures_weekly_features(
    rows: List[Dict[str, Any]],
    lookback_bars: int = 5,
) -> Dict[str, Any]:
    window_size = max(2, lookback_bars)
    window = rows[:window_size]
    if len(window) < 2:
        raise ValueError("at least 2 bars are required for weekly sentiment")

    latest = window[0]
    oldest = window[-1]
    latest_close = float(latest["close"])
    oldest_close = float(oldest["close"])

    weekly_return_pct = 0.0
    if oldest_close != 0:
        weekly_return_pct = ((latest_close - oldest_close) / oldest_close) * 100

    up_days = 0
    down_days = 0
    for idx in range(len(window) - 1):
        newer = float(window[idx]["close"])
        older = float(window[idx + 1]["close"])
        if newer > older:
            up_days += 1
        elif newer < older:
            down_days += 1

    direction_total = up_days + down_days
    trend_balance = 0.0 if direction_total == 0 else (up_days - down_days) / direction_total

    volumes = [float(item.get("volume") or 0.0) for item in window]
    avg_volume = mean(volumes) if volumes else 0.0
    latest_volume = volumes[0] if volumes else 0.0
    volume_ratio = 1.0 if avg_volume <= 0 else latest_volume / avg_volume

    return {
        "bars_used": len(window),
        "latest_date": latest["date"],
        "latest_close": latest_close,
        "oldest_date": oldest["date"],
        "oldest_close": oldest_close,
        "weekly_return_pct": weekly_return_pct,
        "up_days": up_days,
        "down_days": down_days,
        "trend_balance": trend_balance,
        "latest_volume": latest_volume,
        "avg_volume": avg_volume,
        "volume_ratio": volume_ratio,
    }


def _compute_options_features(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "available": False,
            "call_bid_total": 0,
            "call_ask_total": 0,
            "put_bid_total": 0,
            "put_ask_total": 0,
            "call_oi_change_total": 0,
            "put_oi_change_total": 0,
            "bid_pressure": 0.0,
            "oi_pressure": 0.0,
            "put_call_bid_ratio": 1.0,
        }

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

    oi_denom = abs(call_oi_change_total) + abs(put_oi_change_total)
    oi_pressure = 0.0 if oi_denom == 0 else (call_oi_change_total - put_oi_change_total) / oi_denom

    if call_bid_total > 0:
        put_call_bid_ratio = put_bid_total / call_bid_total
    else:
        put_call_bid_ratio = math.inf if put_bid_total > 0 else 1.0

    return {
        "available": True,
        "call_bid_total": call_bid_total,
        "call_ask_total": call_ask_total,
        "put_bid_total": put_bid_total,
        "put_ask_total": put_ask_total,
        "call_oi_change_total": call_oi_change_total,
        "put_oi_change_total": put_oi_change_total,
        "bid_pressure": bid_pressure,
        "oi_pressure": oi_pressure,
        "put_call_bid_ratio": put_call_bid_ratio,
    }


def _extract_latest_index_close(payload: Optional[Dict[str, Any]]) -> Optional[float]:
    if not isinstance(payload, dict):
        return None
    rows = payload.get("output2")
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list):
        return None

    latest_row: Optional[Dict[str, Any]] = None
    latest_date = ""
    for row in rows:
        if not isinstance(row, dict):
            continue
        date = str(row.get("stck_bsop_date") or "")
        if date >= latest_date:
            latest_date = date
            latest_row = row

    if latest_row is None:
        return None
    return _pick_number(latest_row, ("bstp_nmix_prpr", "stck_clpr", "close"))


def compute_weekly_sentiment_score(
    futures_features: Dict[str, Any],
    options_features: Dict[str, Any],
    basis_pct: Optional[float] = None,
) -> Dict[str, Any]:
    momentum_component = max(min(float(futures_features.get("weekly_return_pct", 0.0)) * 4.0, 35.0), -35.0)
    trend_component = max(min(float(futures_features.get("trend_balance", 0.0)) * 15.0, 15.0), -15.0)

    options_component = 0.0
    if options_features.get("available"):
        options_component = (
            float(options_features.get("bid_pressure", 0.0)) * 25.0
            + float(options_features.get("oi_pressure", 0.0)) * 25.0
        )

    volume_component = 0.0
    weekly_return_pct = float(futures_features.get("weekly_return_pct", 0.0))
    volume_ratio = float(futures_features.get("volume_ratio", 1.0))
    if volume_ratio >= 1.1:
        if weekly_return_pct > 0:
            volume_component = 8.0
        elif weekly_return_pct < 0:
            volume_component = -8.0

    basis_component = 0.0
    if basis_pct is not None:
        if basis_pct < -0.2:
            basis_component -= 8.0
        elif basis_pct > 0.2:
            basis_component += 4.0
        if abs(basis_pct) > 2.5:
            basis_component -= 4.0

    score = momentum_component + trend_component + options_component + volume_component + basis_component
    score = max(min(score, 100.0), -100.0)

    if score >= 35:
        regime = "strong_bullish"
    elif score >= 15:
        regime = "bullish"
    elif score <= -35:
        regime = "strong_bearish"
    elif score <= -15:
        regime = "bearish"
    else:
        regime = "neutral"

    return {
        "score": round(score, 2),
        "regime": regime,
        "components": {
            "momentum": round(momentum_component, 2),
            "trend": round(trend_component, 2),
            "options": round(options_component, 2),
            "volume": round(volume_component, 2),
            "basis": round(basis_component, 2),
        },
    }


def _build_reasons(
    futures_features: Dict[str, Any],
    options_features: Dict[str, Any],
    basis_pct: Optional[float],
) -> List[str]:
    reasons: List[str] = []
    weekly_return = float(futures_features.get("weekly_return_pct", 0.0))
    if weekly_return >= 1.0:
        reasons.append(f"최근 {futures_features.get('bars_used')}거래일 선물이 +{weekly_return:.2f}% 상승했습니다.")
    elif weekly_return <= -1.0:
        reasons.append(f"최근 {futures_features.get('bars_used')}거래일 선물이 {weekly_return:.2f}% 하락했습니다.")

    ratio = float(options_features.get("put_call_bid_ratio", 1.0))
    if math.isfinite(ratio):
        if ratio >= 1.2:
            reasons.append(f"옵션 매수잔량 기준 Put/Call 비율이 {ratio:.2f}로 방어 심리가 우세합니다.")
        elif ratio <= 0.85:
            reasons.append(f"옵션 매수잔량 기준 Put/Call 비율이 {ratio:.2f}로 위험선호 심리가 우세합니다.")

    put_oi = int(options_features.get("put_oi_change_total", 0))
    call_oi = int(options_features.get("call_oi_change_total", 0))
    if put_oi > call_oi:
        reasons.append("풋 OI 증가 폭이 콜보다 커서 하방 헤지 포지션이 강화되었습니다.")
    elif call_oi > put_oi:
        reasons.append("콜 OI 증가 폭이 풋보다 커서 상방 베팅이 강화되었습니다.")

    if basis_pct is not None:
        reasons.append(f"선물-현물(코스피200) 괴리율은 {basis_pct:+.2f}% 입니다.")

    if not reasons:
        reasons.append("핵심 지표 변화가 제한적이라 중립 구간으로 판단됩니다.")
    return reasons


async def analyze_kr_weekly_sentiment(
    futures_symbol: str = "101000",
    lookback_days: int = 45,
    lookback_bars: int = 5,
    maturity_month: Optional[str] = None,
) -> Dict[str, Any]:
    from backend.integrations.kis.kis_client import (
        get_futures_daily_chart,
        get_options_display_board,
    )

    now = datetime.now(KST)
    end_date = now.strftime("%Y%m%d")
    start_date = (now - timedelta(days=max(lookback_days, 10))).strftime("%Y%m%d")
    target_maturity = maturity_month or now.strftime("%Y%m")

    async def _fetch_kospi200_daily() -> Optional[Dict[str, Any]]:
        try:
            from backend.integrations.kis.kis_index import fetch_index_daily_prices

            return await asyncio.to_thread(fetch_index_daily_prices, "2001", end_date, "D")
        except Exception:
            return None

    futures_task = get_futures_daily_chart(
        futures_symbol,
        start_date,
        end_date,
        period_div="D",
    )
    options_task = get_options_display_board(target_maturity)
    spot_task = _fetch_kospi200_daily()

    futures_payload, options_payload, spot_payload = await asyncio.gather(
        futures_task,
        options_task,
        spot_task,
        return_exceptions=True,
    )

    errors: List[str] = []
    if isinstance(futures_payload, Exception):
        errors.append(f"선물 데이터 조회 실패: {futures_payload}")
        futures_payload = None
    if isinstance(options_payload, Exception):
        errors.append(f"옵션 전광판 조회 실패: {options_payload}")
        options_payload = None
    if isinstance(spot_payload, Exception):
        errors.append(f"코스피200 지수 조회 실패: {spot_payload}")
        spot_payload = None

    rows = _normalize_daily_rows(futures_payload if isinstance(futures_payload, dict) else None)
    if len(rows) < 2:
        errors.append("선물 일봉 데이터가 부족합니다. (최소 2개 이상 필요)")
        return {
            "status": "error",
            "timestamp": now.isoformat(),
            "symbol": futures_symbol,
            "errors": errors,
        }

    futures_features = _compute_futures_weekly_features(rows, lookback_bars=lookback_bars)

    options_features = _compute_options_features(
        options_payload if isinstance(options_payload, dict) else None
    )

    spot_close = _extract_latest_index_close(spot_payload if isinstance(spot_payload, dict) else None)
    futures_close = float(futures_features["latest_close"])
    basis = None
    basis_pct = None
    if spot_close and spot_close != 0:
        basis = futures_close - spot_close
        basis_pct = (basis / spot_close) * 100

    score_result = compute_weekly_sentiment_score(
        futures_features=futures_features,
        options_features=options_features,
        basis_pct=basis_pct,
    )
    reasons = _build_reasons(futures_features, options_features, basis_pct)

    return {
        "status": "ok",
        "timestamp": now.isoformat(),
        "symbol": futures_symbol,
        "date_range": {"start": start_date, "end": end_date},
        "futures": futures_features,
        "options": options_features,
        "basis": {
            "spot_close": spot_close,
            "futures_close": futures_close,
            "basis": basis,
            "basis_pct": basis_pct,
        },
        "sentiment": score_result,
        "reasons": reasons,
        "errors": errors,
    }


def format_kr_weekly_sentiment_report(result: Dict[str, Any]) -> str:
    if result.get("status") != "ok":
        errors = result.get("errors") or ["알 수 없는 오류"]
        joined = "\n".join(f"- {err}" for err in errors)
        return f"[국내 주간 심리 리포트]\n상태: 실패\n{joined}"

    sentiment = result.get("sentiment", {})
    futures = result.get("futures", {})
    options = result.get("options", {})
    basis = result.get("basis", {})

    regime = sentiment.get("regime", "neutral")
    regime_ko = {
        "strong_bullish": "강한 상승",
        "bullish": "상승 우위",
        "neutral": "중립",
        "bearish": "하락 우위",
        "strong_bearish": "강한 하락",
    }.get(regime, regime)

    lines = [
        "[국내 주간 심리 리포트]",
        f"- 심리 점수: {sentiment.get('score', 0)} ({regime_ko})",
        (
            f"- 선물 {futures.get('bars_used')}거래일 수익률: "
            f"{float(futures.get('weekly_return_pct', 0.0)):+.2f}%"
        ),
        (
            f"- 상승일/하락일: {futures.get('up_days', 0)}/{futures.get('down_days', 0)}"
            f", 거래량비: {float(futures.get('volume_ratio', 1.0)):.2f}"
        ),
        (
            f"- 옵션 Put/Call(매수잔량): "
            f"{float(options.get('put_call_bid_ratio', 1.0)):.2f}"
        ),
        (
            f"- 옵션 OI 증감(콜/풋): "
            f"{int(options.get('call_oi_change_total', 0)):+,} / "
            f"{int(options.get('put_oi_change_total', 0)):+,}"
        ),
    ]

    basis_pct = basis.get("basis_pct")
    if isinstance(basis_pct, (float, int)):
        lines.append(f"- 선물-현물 괴리율: {float(basis_pct):+.2f}%")

    reasons = result.get("reasons") or []
    if reasons:
        lines.append("- 해석:")
        lines.extend(f"  {idx}. {reason}" for idx, reason in enumerate(reasons, start=1))

    errors = result.get("errors") or []
    if errors:
        lines.append("- 참고(비치명):")
        lines.extend(f"  - {err}" for err in errors)

    return "\n".join(lines)


__all__ = [
    "analyze_kr_weekly_sentiment",
    "compute_weekly_sentiment_score",
    "format_kr_weekly_sentiment_report",
]
