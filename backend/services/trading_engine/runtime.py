from __future__ import annotations

import asyncio
import importlib
import logging
import os
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from .config import TradeEngineConfig
from .interfaces import TradingAPI
from .notifier import BestEffortNotifier
from .runtime_config import _env_bool, load_trade_engine_config_from_env
from .utils import normalize_bar_date

if TYPE_CHECKING:
    from .bot import HybridTradingBot

logger = logging.getLogger(__name__)

_BOT: HybridTradingBot | None = None
_FACTORY_LOAD_FAILED = False


def trading_engine_enabled() -> bool:
    return _env_bool("TRADING_ENGINE_ENABLED", default=False)


def load_config_from_env() -> TradeEngineConfig:
    return _load_config_from_env()


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
) -> dict[str, str | bool | None]:
    cfg = config or TradeEngineConfig()
    return {
        "date": date,
        "is_trading_day": bool(is_trading_day_value) if is_trading_day_value is not None else None,
        "open": "09:00",
        "close": "15:30",
        "force_exit": cfg.day_force_exit_at,
    }


def get_or_create_bot() -> HybridTradingBot | None:
    global _BOT
    if _BOT is not None:
        return _BOT

    if not trading_engine_enabled():
        return None

    api_factory = _load_api_factory()
    if api_factory is None:
        return None

    try:
        api = api_factory()
    except Exception as exc:
        logger.error("failed to create trading api from factory: %s", exc, exc_info=True)
        return None

    if not isinstance(api, TradingAPI):
        logger.error("trading api instance does not satisfy TradingAPI protocol: %r", type(api))
        return None

    cfg = _load_config_from_env()
    notifier = BestEffortNotifier(
        send_text=_send_text_sync,
        max_retry=cfg.telegram_retry_max,
    )
    from .bot import HybridTradingBot

    _BOT = HybridTradingBot(api, config=cfg, notifier=notifier)
    logger.info("trading engine bot initialized")
    return _BOT


def close_bot() -> None:
    global _BOT
    if _BOT is None:
        return
    try:
        _BOT.close()
    except Exception:
        logger.warning("failed to close trading bot cleanly", exc_info=True)
    finally:
        _BOT = None


def _load_api_factory() -> Callable[[], object] | None:
    global _FACTORY_LOAD_FAILED

    factory_path = os.getenv("TRADING_ENGINE_API_FACTORY", "").strip()
    if not factory_path:
        if not _FACTORY_LOAD_FAILED:
            logger.warning("TRADING_ENGINE_ENABLED=1 but TRADING_ENGINE_API_FACTORY is not set")
            _FACTORY_LOAD_FAILED = True
        return None

    try:
        module_path, attr_name = factory_path.split(":", 1)
        module = importlib.import_module(module_path)
        attr = getattr(module, attr_name)
        if not callable(attr):
            raise TypeError(f"{factory_path} is not callable")
        return attr
    except Exception as exc:
        if not _FACTORY_LOAD_FAILED:
            logger.error("failed to import TRADING_ENGINE_API_FACTORY=%s: %s", factory_path, exc)
            _FACTORY_LOAD_FAILED = True
        return None


def _load_config_from_env() -> TradeEngineConfig:
    return load_trade_engine_config_from_env()


def _send_text_sync(text: str) -> bool:
    try:
        from backend.integrations.telegram import send_telegram_message

        return bool(asyncio.run(send_telegram_message(text, bot_type="main")))
    except Exception:
        logger.warning("trading telegram notify failed", exc_info=True)
        return False
