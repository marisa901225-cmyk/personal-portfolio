from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .config import TradeEngineConfig
from .interfaces import TradingAPI
from .utils import normalize_bar_date


def is_trading_day(
    api: TradingAPI,
    date: str,
    *,
    config: TradeEngineConfig | None = None,
) -> bool:
    cfg = config or TradeEngineConfig()

    if hasattr(api, "is_trading_day") and callable(getattr(api, "is_trading_day")):
        try:
            return bool(getattr(api, "is_trading_day")(date))
        except Exception:
            pass

    bars = api.daily_bars(code=cfg.market_proxy_code, end=date, lookback=3)
    if bars is None or bars.empty:
        return False

    last_row = bars.iloc[-1]
    last_date = normalize_bar_date(last_row.get("date"))
    return last_date == date


def get_last_trading_day(
    api: TradingAPI,
    date: str,
    *,
    max_lookback_days: int = 14,
    config: TradeEngineConfig | None = None,
) -> str:
    base = datetime.strptime(date, "%Y%m%d")
    for offset in range(0, max_lookback_days + 1):
        target = (base - timedelta(days=offset)).strftime("%Y%m%d")
        if is_trading_day(api, target, config=config):
            return target
    return date


def get_market_session(
    date: str,
    *,
    config: TradeEngineConfig | None = None,
    is_trading_day_value: bool | None = None,
) -> dict[str, Any]:
    cfg = config or TradeEngineConfig()
    return {
        "date": date,
        "is_trading_day": bool(is_trading_day_value) if is_trading_day_value is not None else None,
        "open": "09:00",
        "close": "15:30",
        "force_exit": cfg.day_force_exit_at,
    }
