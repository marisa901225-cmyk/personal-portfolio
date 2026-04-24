from __future__ import annotations

import logging

import pandas as pd

from .config import TradeEngineConfig
from .interfaces import TradingAPI
from .utils import parse_numeric


def _numeric_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce").dropna()


def sort_intraday_bars(bars: pd.DataFrame) -> pd.DataFrame:
    if bars is None or bars.empty:
        return bars

    view = bars.copy()
    if "timestamp" in view.columns:
        return view.sort_values("timestamp", ascending=True)

    if "date" in view.columns and "time" in view.columns:
        key = view["date"].astype(str) + view["time"].astype(str).str.zfill(6)
        return view.assign(_k=key).sort_values("_k", ascending=True).drop(columns=["_k"])

    if "date" in view.columns:
        return view.sort_values("date", ascending=True)

    return view.sort_index(ascending=True)


def passes_day_intraday_confirmation(
    api: TradingAPI,
    *,
    trade_date: str,
    code: str,
    config: TradeEngineConfig,
    logger: logging.Logger | None = None,
) -> tuple[bool, dict[str, object]]:
    intraday_fn = getattr(api, "intraday_bars", None)
    if not callable(intraday_fn):
        return True, {"reason": "UNSUPPORTED"}

    recent_n = max(2, int(config.day_intraday_confirmation_bars))
    lookback = max(12, recent_n + 4)
    try:
        bars = intraday_fn(code=code, asof=trade_date, lookback=lookback)
    except Exception:
        if logger is not None:
            logger.debug("day intraday confirmation fetch failed code=%s", code, exc_info=True)
        # Day-trade entry should not proceed when the chart gate could not be evaluated.
        return False, {"reason": "FETCH_FAILED"}

    if bars is None or bars.empty:
        return False, {"reason": "NO_DATA"}

    sorted_bars = sort_intraday_bars(bars)
    recent_rows = sorted_bars.tail(recent_n)
    close_s = _numeric_series(recent_rows, "close")
    if len(close_s) < recent_n:
        return False, {"reason": "INSUFFICIENT_DATA", "bars": int(len(close_s))}

    recent = close_s.tail(recent_n)
    start_close = float(recent.iloc[0])
    prev_close = float(recent.iloc[-2]) if len(recent) >= 2 else start_close
    last_close = float(recent.iloc[-1])
    high_s = _numeric_series(recent_rows, "high")
    low_s = _numeric_series(recent_rows, "low")
    recent_high = float(max(recent.max(), high_s.max())) if not high_s.empty else float(recent.max())
    recent_low = float(min(recent.min(), low_s.min())) if not low_s.empty else float(recent.min())
    day_change_s = _numeric_series(sorted_bars, "change_pct")
    day_change_pct = float(day_change_s.iloc[-1]) if not day_change_s.empty else None
    day_change_pct = _resolve_day_change_pct(api, code=code, current=day_change_pct)

    if start_close <= 0 or prev_close <= 0 or recent_high <= 0 or recent_low <= 0:
        return False, {"reason": "INVALID_DATA", "bars": int(len(close_s))}

    window_change_pct = (last_close / start_close - 1.0) * 100.0
    last_bar_change_pct = (last_close / prev_close - 1.0) * 100.0
    retrace_from_high_pct = (last_close / recent_high - 1.0) * 100.0
    recent_range_pct = (recent_high / recent_low - 1.0) * 100.0

    meta = {
        "bars": int(len(recent)),
        "window_change_pct": round(window_change_pct, 4),
        "last_bar_change_pct": round(last_bar_change_pct, 4),
        "retrace_from_high_pct": round(retrace_from_high_pct, 4),
        "recent_range_pct": round(recent_range_pct, 4),
    }
    if day_change_pct is not None:
        meta["day_change_pct"] = round(day_change_pct, 4)

    if window_change_pct < float(config.day_intraday_min_window_change_pct):
        tight_base_ok = (
            day_change_pct is not None
            and day_change_pct >= float(config.day_intraday_tight_base_min_day_change_pct)
            and window_change_pct >= float(config.day_intraday_tight_base_min_window_change_pct)
            and last_bar_change_pct >= float(config.day_intraday_tight_base_min_last_bar_change_pct)
            and recent_range_pct <= float(config.day_intraday_tight_base_max_range_pct)
            and retrace_from_high_pct >= float(config.day_intraday_tight_base_max_retrace_from_high_pct)
        )
        if tight_base_ok:
            return True, {"reason": "TIGHT_INTRADAY_BASE", **meta}
        if _is_momentum_pullback_ok(
            config=config,
            day_change_pct=day_change_pct,
            window_change_pct=window_change_pct,
            last_bar_change_pct=last_bar_change_pct,
            retrace_from_high_pct=retrace_from_high_pct,
        ):
            return True, {"reason": "MOMENTUM_PULLBACK_OK", **meta}
        return False, {
            "reason": "WEAK_INTRADAY_WINDOW",
            **meta,
        }

    if last_bar_change_pct < float(config.day_intraday_min_last_bar_change_pct):
        if _is_momentum_pullback_ok(
            config=config,
            day_change_pct=day_change_pct,
            window_change_pct=window_change_pct,
            last_bar_change_pct=last_bar_change_pct,
            retrace_from_high_pct=retrace_from_high_pct,
        ):
            return True, {"reason": "MOMENTUM_PULLBACK_OK", **meta}
        return False, {
            "reason": "WEAK_INTRADAY_LAST_BAR",
            **meta,
        }

    if retrace_from_high_pct < float(config.day_intraday_max_retrace_from_high_pct):
        return False, {
            "reason": "INTRADAY_RETRACE",
            **meta,
        }

    return True, {
        "reason": "OK",
        **meta,
    }


def _resolve_day_change_pct(
    api: TradingAPI,
    *,
    code: str,
    current: float | None,
) -> float | None:
    if current is not None and abs(float(current)) > 1e-9:
        return float(current)

    try:
        quote = api.quote(code) or {}
    except Exception:
        return current

    fallback = parse_numeric(quote.get("change_pct"))
    if fallback is None:
        fallback = parse_numeric(quote.get("change_rate"))
    return float(fallback) if fallback is not None else current


def _is_momentum_pullback_ok(
    *,
    config: TradeEngineConfig,
    day_change_pct: float | None,
    window_change_pct: float,
    last_bar_change_pct: float,
    retrace_from_high_pct: float,
) -> bool:
    if day_change_pct is None:
        return False

    return (
        day_change_pct >= float(getattr(config, "day_momentum_pullback_min_day_change_pct", 0.0))
        and window_change_pct >= float(getattr(config, "day_momentum_pullback_min_window_change_pct", 0.0))
        and last_bar_change_pct >= float(getattr(config, "day_momentum_pullback_min_last_bar_change_pct", 0.0))
        and retrace_from_high_pct >= float(getattr(config, "day_momentum_pullback_max_retrace_from_high_pct", 0.0))
    )
