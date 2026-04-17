from __future__ import annotations

import asyncio
import importlib
import logging
import os
from typing import Any, Callable

from .bot import HybridTradingBot
from .config import TradeEngineConfig
from .interfaces import TradingAPI
from .notifier import BestEffortNotifier
from .runtime_config import _env_bool, load_trade_engine_config_from_env

logger = logging.getLogger(__name__)

_BOT: HybridTradingBot | None = None
_FACTORY_LOAD_FAILED = False


def trading_engine_enabled() -> bool:
    return _env_bool("TRADING_ENGINE_ENABLED", default=False)


def load_config_from_env() -> TradeEngineConfig:
    return _load_config_from_env()


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


def _load_api_factory() -> Callable[[], Any] | None:
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
