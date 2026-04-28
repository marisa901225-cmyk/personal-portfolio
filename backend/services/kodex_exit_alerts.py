from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from tempfile import NamedTemporaryFile
from typing import Any

import pandas as pd

from backend.core.time_utils import now_kst

logger = logging.getLogger(__name__)
_MARKET_PROXY_CODE = "069500"

_DEFAULT_STATE_PATH = os.path.abspath(
    os.getenv(
        "KODEX_EXIT_ALERT_STATE_PATH",
        os.path.join(os.path.dirname(__file__), "..", "data", "kodex_kospi100_exit_alert_state.json"),
    )
)


@dataclass(frozen=True, slots=True)
class KodexExitAlertConfig:
    code: str = "237350"
    name: str = "KODEX 코스피100"
    average_cost: float | None = 66_731.0
    daily_high_lookback: int = 20
    daily_peak_fresh_bars: int = 10
    daily_retrace_pct: float = 3.0
    daily_ma_period: int = 8
    weekly_high_lookback: int = 12
    weekly_retrace_pct: float = 6.0
    weekly_ma_period: int = 12
    monthly_ma_period: int = 12
    history_lookback: int = 260
    state_path: str = _DEFAULT_STATE_PATH


def _safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(number):
        return None
    return number


def _to_frame(rows: pd.DataFrame) -> pd.DataFrame:
    if rows is None or rows.empty:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

    frame = rows.copy()
    frame["date"] = pd.to_datetime(frame["date"], format="%Y%m%d", errors="coerce")
    frame = frame.dropna(subset=["date"])
    for col in ("open", "high", "low", "close", "volume"):
        if col in frame.columns:
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
        else:
            frame[col] = pd.NA
    frame = frame.sort_values("date").reset_index(drop=True)
    return frame


def _upsert_today_bar(bars: pd.DataFrame, quote: dict[str, Any], today: str) -> pd.DataFrame:
    frame = _to_frame(bars)
    today_dt = pd.to_datetime(today, format="%Y%m%d", errors="coerce")
    if pd.isna(today_dt):
        return frame

    payload = {
        "date": today_dt,
        "open": _safe_float(quote.get("open")),
        "high": _safe_float(quote.get("high")),
        "low": _safe_float(quote.get("low")),
        "close": _safe_float(quote.get("price")),
        "volume": _safe_float(quote.get("volume")) or 0.0,
    }

    mask = frame["date"] == today_dt
    if mask.any():
        idx = frame.index[mask][-1]
        for key, value in payload.items():
            if key == "date" or value is None:
                continue
            if key == "high":
                base = _safe_float(frame.at[idx, key]) or value
                frame.at[idx, key] = max(base, value)
            elif key == "low":
                base = _safe_float(frame.at[idx, key]) or value
                frame.at[idx, key] = min(base, value)
            else:
                frame.at[idx, key] = value
        return frame.sort_values("date").reset_index(drop=True)

    if payload["close"] is None:
        return frame

    appended = pd.concat([frame, pd.DataFrame([payload])], ignore_index=True)
    return appended.sort_values("date").reset_index(drop=True)


def _aggregate_ohlcv(bars: pd.DataFrame, rule: str) -> pd.DataFrame:
    frame = _to_frame(bars)
    if frame.empty:
        return frame

    grouped = (
        frame.set_index("date")
        .resample(rule)
        .agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        )
        .dropna(subset=["close"])
        .reset_index()
    )
    return grouped


def evaluate_daily_warning(
    bars: pd.DataFrame,
    quote: dict[str, Any],
    *,
    today: str,
    config: KodexExitAlertConfig | None = None,
) -> dict[str, Any] | None:
    cfg = config or KodexExitAlertConfig()
    frame = _upsert_today_bar(bars, quote, today)
    if len(frame) < max(cfg.daily_high_lookback, cfg.daily_ma_period):
        return None

    recent = frame.tail(cfg.daily_high_lookback).reset_index(drop=True)
    current_price = _safe_float(recent.iloc[-1]["close"])
    recent_high = _safe_float(recent["high"].max())
    if current_price is None or recent_high is None or recent_high <= 0:
        return None

    high_idx = int(recent["high"].astype(float).idxmax())
    recent_high_date = recent.iloc[high_idx]["date"]
    days_since_peak = len(recent) - 1 - high_idx
    ma_value = float(recent["close"].tail(cfg.daily_ma_period).mean())
    retrace_pct = ((current_price / recent_high) - 1.0) * 100.0

    triggered = (
        retrace_pct <= (-abs(cfg.daily_retrace_pct))
        and current_price < ma_value
        and days_since_peak <= cfg.daily_peak_fresh_bars
    )
    return {
        "triggered": triggered,
        "current_price": current_price,
        "recent_high": recent_high,
        "recent_high_date": pd.Timestamp(recent_high_date).strftime("%Y-%m-%d"),
        "retrace_pct": retrace_pct,
        "ma_value": ma_value,
        "days_since_peak": days_since_peak,
    }


def evaluate_weekly_confirmation(
    bars: pd.DataFrame,
    quote: dict[str, Any],
    *,
    today: str,
    config: KodexExitAlertConfig | None = None,
) -> dict[str, Any] | None:
    cfg = config or KodexExitAlertConfig()
    frame = _upsert_today_bar(bars, quote, today)
    weekly = _aggregate_ohlcv(frame, "W-FRI")
    monthly = _aggregate_ohlcv(frame, "ME")
    if len(weekly) < max(cfg.weekly_high_lookback, cfg.weekly_ma_period):
        return None
    if len(monthly) < cfg.monthly_ma_period:
        return None

    recent_weekly = weekly.tail(cfg.weekly_high_lookback).reset_index(drop=True)
    latest_week = recent_weekly.iloc[-1]
    weekly_close = _safe_float(latest_week["close"])
    weekly_high = _safe_float(recent_weekly["high"].max())
    if weekly_close is None or weekly_high is None or weekly_high <= 0:
        return None

    weekly_ma = float(weekly["close"].tail(cfg.weekly_ma_period).mean())
    retrace_pct = ((weekly_close / weekly_high) - 1.0) * 100.0

    monthly_close = float(monthly.iloc[-1]["close"])
    monthly_ma = float(monthly["close"].tail(cfg.monthly_ma_period).mean())
    monthly_trend_ok = monthly_close >= monthly_ma

    triggered = weekly_close < weekly_ma and retrace_pct <= (-abs(cfg.weekly_retrace_pct))
    return {
        "triggered": triggered,
        "weekly_close": weekly_close,
        "weekly_high": weekly_high,
        "weekly_ma": weekly_ma,
        "retrace_pct": retrace_pct,
        "week_end": pd.Timestamp(latest_week["date"]).strftime("%Y-%m-%d"),
        "monthly_close": monthly_close,
        "monthly_ma": monthly_ma,
        "monthly_trend_ok": monthly_trend_ok,
    }


def _load_state(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
            if isinstance(raw, dict):
                return raw
    except FileNotFoundError:
        return {}
    except Exception as exc:
        logger.warning("KODEX exit alert state load failed path=%s error=%s", path, exc)
    return {}


def _save_state(path: str, payload: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=os.path.dirname(path) or ".", delete=False) as tmp:
        json.dump(payload, tmp, ensure_ascii=False, indent=2)
        tmp.write("\n")
        tmp_path = tmp.name
    os.replace(tmp_path, path)


def _fmt_price(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:,.0f}원"


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}%"


def _pnl_vs_average_cost(current_price: float | None, average_cost: float | None) -> float | None:
    if current_price is None or average_cost is None or average_cost <= 0:
        return None
    return ((current_price / average_cost) - 1.0) * 100.0


def _iso_week_id(date_yyyymmdd: str) -> str:
    dt = datetime.strptime(date_yyyymmdd, "%Y%m%d")
    year, week, _ = dt.isocalendar()
    return f"{year}-W{week:02d}"


def _is_trading_day(api: Any, date: str) -> bool:
    if hasattr(api, "is_trading_day") and callable(getattr(api, "is_trading_day")):
        try:
            return bool(getattr(api, "is_trading_day")(date))
        except Exception:
            pass

    bars = api.daily_bars(code=_MARKET_PROXY_CODE, end=date, lookback=3)
    frame = _to_frame(bars)
    if frame.empty:
        return False
    return frame.iloc[-1]["date"].strftime("%Y%m%d") == date


def _is_last_trading_day_of_week(api: Any, today: str) -> bool:
    today_dt = datetime.strptime(today, "%Y%m%d")
    today_week = today_dt.isocalendar()[:2]
    for offset in range(1, 7):
        candidate = today_dt + timedelta(days=offset)
        if candidate.isocalendar()[:2] != today_week:
            break
        if _is_trading_day(api, candidate.strftime("%Y%m%d")):
            return False
    return True


async def check_kodex_kospi100_daily_warning(
    *,
    config: KodexExitAlertConfig | None = None,
) -> bool:
    cfg = config or KodexExitAlertConfig()
    from backend.integrations.kis.trading_adapter import create_trading_api
    from backend.integrations.telegram import send_telegram_message

    api = create_trading_api()
    today = now_kst().strftime("%Y%m%d")
    if not _is_trading_day(api, today):
        return False

    bars = api.daily_bars(cfg.code, end=today, lookback=cfg.history_lookback)
    quote = api.quote(cfg.code)
    result = evaluate_daily_warning(bars, quote, today=today, config=cfg)
    if not result or not result["triggered"]:
        return False

    state = _load_state(cfg.state_path)
    if state.get("daily_last_alert_date") == today:
        return False

    weekly = evaluate_weekly_confirmation(bars, quote, today=today, config=cfg)
    weekly_hint = "주봉 확인 대기"
    if weekly:
        weekly_hint = "주봉 확인 신호 진행 중" if weekly["triggered"] else "주봉 확인 전"
    pnl_pct = _pnl_vs_average_cost(result["current_price"], cfg.average_cost)

    message = (
        f"⚠️ [{cfg.name} 일봉 조기경보]\n"
        f"- 코드: {cfg.code}\n"
        f"- 현재가: {_fmt_price(result['current_price'])}\n"
        f"- 평단: {_fmt_price(cfg.average_cost)} / 평단 대비: {_fmt_pct(pnl_pct)}\n"
        f"- 최근 {cfg.daily_high_lookback}일 고점: {_fmt_price(result['recent_high'])} ({result['recent_high_date']})\n"
        f"- 고점 대비: {_fmt_pct(result['retrace_pct'])}\n"
        f"- {cfg.daily_ma_period}일선: {_fmt_price(result['ma_value'])}\n"
        f"- 해석: 최근 고점 찍은 뒤 일봉상 한 번 꺾이는 흐름으로 보임\n"
        f"- 다음 단계: {weekly_hint}"
    )
    sent = await send_telegram_message(message, bot_type="main")
    if sent:
        state["daily_last_alert_date"] = today
        _save_state(cfg.state_path, state)
    return bool(sent)


async def check_kodex_kospi100_weekly_confirmation(
    *,
    config: KodexExitAlertConfig | None = None,
) -> bool:
    cfg = config or KodexExitAlertConfig()
    from backend.integrations.kis.trading_adapter import create_trading_api
    from backend.integrations.telegram import send_telegram_message

    api = create_trading_api()
    today = now_kst().strftime("%Y%m%d")
    if not _is_trading_day(api, today):
        return False
    if not _is_last_trading_day_of_week(api, today):
        return False

    bars = api.daily_bars(cfg.code, end=today, lookback=cfg.history_lookback)
    quote = api.quote(cfg.code)
    result = evaluate_weekly_confirmation(bars, quote, today=today, config=cfg)
    if not result or not result["triggered"]:
        return False

    week_id = _iso_week_id(today)
    state = _load_state(cfg.state_path)
    if state.get("weekly_last_alert_week") == week_id:
        return False

    monthly_line = "월봉 추세는 아직 버팀" if result["monthly_trend_ok"] else "월봉도 약해져서 방어 우선"
    pnl_pct = _pnl_vs_average_cost(result["weekly_close"], cfg.average_cost)
    message = (
        f"🚨 [{cfg.name} 주봉 확인 신호]\n"
        f"- 코드: {cfg.code}\n"
        f"- 주간 종가 기준일: {result['week_end']}\n"
        f"- 주간 종가: {_fmt_price(result['weekly_close'])}\n"
        f"- 평단: {_fmt_price(cfg.average_cost)} / 평단 대비: {_fmt_pct(pnl_pct)}\n"
        f"- 최근 {cfg.weekly_high_lookback}주 고점: {_fmt_price(result['weekly_high'])}\n"
        f"- 고점 대비: {_fmt_pct(result['retrace_pct'])}\n"
        f"- {cfg.weekly_ma_period}주선: {_fmt_price(result['weekly_ma'])}\n"
        f"- 월봉 {cfg.monthly_ma_period}개월선: {_fmt_price(result['monthly_ma'])}\n"
        f"- 월봉 상태: {monthly_line}\n"
        f"- 해석: 일봉 경고를 넘어서 주봉 기준으로도 꺾임 확인 구간"
    )
    sent = await send_telegram_message(message, bot_type="main")
    if sent:
        state["weekly_last_alert_week"] = week_id
        _save_state(cfg.state_path, state)
    return bool(sent)
