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

logger = logging.getLogger(__name__)

_BOT: HybridTradingBot | None = None
_FACTORY_LOAD_FAILED = False


def trading_engine_enabled() -> bool:
    return _env_bool("TRADING_ENGINE_ENABLED", default=False)


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
    cfg = TradeEngineConfig()

    if os.getenv("TRADING_ENGINE_STATE_PATH"):
        cfg.state_path = os.getenv("TRADING_ENGINE_STATE_PATH", cfg.state_path)
    if os.getenv("TRADING_ENGINE_OUTPUT_DIR"):
        cfg.output_dir = os.getenv("TRADING_ENGINE_OUTPUT_DIR", cfg.output_dir)
    if os.getenv("TRADING_ENGINE_RUNLOG_PATH"):
        cfg.runlog_path = os.getenv("TRADING_ENGINE_RUNLOG_PATH", cfg.runlog_path)

    cfg.include_etf = _env_bool("TRADING_ENGINE_INCLUDE_ETF", cfg.include_etf)
    cfg.monitor_interval_sec = _env_int("TRADING_ENGINE_MONITOR_SEC", cfg.monitor_interval_sec)
    cfg.telegram_retry_max = _env_int("TRADING_ENGINE_TELEGRAM_RETRY", cfg.telegram_retry_max)

    cfg.swing_cash_ratio = _env_float("TRADING_ENGINE_SWING_CASH_RATIO", cfg.swing_cash_ratio)
    cfg.day_cash_ratio = _env_float("TRADING_ENGINE_DAY_CASH_RATIO", cfg.day_cash_ratio)
    if os.getenv("TRADING_ENGINE_SWING_ENTRY_ORDER_TYPE"):
        cfg.swing_entry_order_type = os.getenv(
            "TRADING_ENGINE_SWING_ENTRY_ORDER_TYPE",
            cfg.swing_entry_order_type,
        ).strip()
    if os.getenv("TRADING_ENGINE_DAY_ENTRY_ORDER_TYPE"):
        cfg.day_entry_order_type = os.getenv(
            "TRADING_ENGINE_DAY_ENTRY_ORDER_TYPE",
            cfg.day_entry_order_type,
        ).strip()
    cfg.risk_off_parking_enabled = _env_bool(
        "TRADING_ENGINE_RISK_OFF_PARKING_ENABLED",
        cfg.risk_off_parking_enabled,
    )
    cfg.risk_off_parking_cash_ratio = _env_float(
        "TRADING_ENGINE_RISK_OFF_PARKING_CASH_RATIO",
        cfg.risk_off_parking_cash_ratio,
    )
    if os.getenv("TRADING_ENGINE_RISK_OFF_PARKING_ORDER_TYPE"):
        cfg.risk_off_parking_order_type = os.getenv(
            "TRADING_ENGINE_RISK_OFF_PARKING_ORDER_TYPE",
            cfg.risk_off_parking_order_type,
        ).strip()
    if os.getenv("TRADING_ENGINE_RISK_OFF_PARKING_CODE"):
        cfg.risk_off_parking_code = os.getenv(
            "TRADING_ENGINE_RISK_OFF_PARKING_CODE",
            cfg.risk_off_parking_code,
        ).strip()
    cfg.day_hard_drop_exclude_pct = _env_float(
        "TRADING_ENGINE_DAY_HARD_DROP_EXCLUDE_PCT",
        cfg.day_hard_drop_exclude_pct,
    )
    cfg.day_negative_penalty_per_pct = _env_float(
        "TRADING_ENGINE_DAY_NEGATIVE_PENALTY_PER_PCT",
        cfg.day_negative_penalty_per_pct,
    )
    cfg.day_negative_penalty_max = _env_float(
        "TRADING_ENGINE_DAY_NEGATIVE_PENALTY_MAX",
        cfg.day_negative_penalty_max,
    )
    cfg.swing_momentum_bonus_max = _env_float(
        "TRADING_ENGINE_SWING_MOMENTUM_BONUS_MAX",
        cfg.swing_momentum_bonus_max,
    )
    cfg.swing_momentum_bonus_cap_pct = _env_float(
        "TRADING_ENGINE_SWING_MOMENTUM_BONUS_CAP_PCT",
        cfg.swing_momentum_bonus_cap_pct,
    )
    cfg.swing_negative_penalty_max = _env_float(
        "TRADING_ENGINE_SWING_NEGATIVE_PENALTY_MAX",
        cfg.swing_negative_penalty_max,
    )
    cfg.swing_hard_drop_exclude_pct = _env_float(
        "TRADING_ENGINE_SWING_HARD_DROP_EXCLUDE_PCT",
        cfg.swing_hard_drop_exclude_pct,
    )
    cfg.swing_etf_fallback_min_change_pct = _env_float(
        "TRADING_ENGINE_SWING_ETF_FALLBACK_MIN_CHANGE_PCT",
        cfg.swing_etf_fallback_min_change_pct,
    )
    cfg.swing_sl_requires_trend_break = _env_bool(
        "TRADING_ENGINE_SWING_SL_REQUIRES_TREND_BREAK",
        cfg.swing_sl_requires_trend_break,
    )
    cfg.swing_trend_ma_window = _env_int("TRADING_ENGINE_SWING_TREND_MA_WINDOW", cfg.swing_trend_ma_window)
    cfg.swing_trend_lookback_bars = _env_int(
        "TRADING_ENGINE_SWING_TREND_LOOKBACK_BARS",
        cfg.swing_trend_lookback_bars,
    )
    cfg.swing_trend_break_buffer_pct = _env_float(
        "TRADING_ENGINE_SWING_TREND_BREAK_BUFFER_PCT",
        cfg.swing_trend_break_buffer_pct,
    )
    cfg.regime_vol_threshold = _env_float(
        "TRADING_ENGINE_REGIME_VOL_THRESHOLD",
        cfg.regime_vol_threshold,
    )
    cfg.use_intraday_circuit_breaker = _env_bool(
        "TRADING_ENGINE_USE_INTRADAY_CB",
        cfg.use_intraday_circuit_breaker,
    )
    cfg.intraday_cb_day_change_pct = _env_float(
        "TRADING_ENGINE_INTRADAY_CB_DAY_CHANGE_PCT",
        cfg.intraday_cb_day_change_pct,
    )
    cfg.intraday_cb_1bar_drop_pct = _env_float(
        "TRADING_ENGINE_INTRADAY_CB_1BAR_DROP_PCT",
        cfg.intraday_cb_1bar_drop_pct,
    )
    cfg.intraday_cb_window_minutes = _env_int(
        "TRADING_ENGINE_INTRADAY_CB_WINDOW_MINUTES",
        cfg.intraday_cb_window_minutes,
    )
    cfg.intraday_cb_window_drop_pct = _env_float(
        "TRADING_ENGINE_INTRADAY_CB_WINDOW_DROP_PCT",
        cfg.intraday_cb_window_drop_pct,
    )
    cfg.use_news_sentiment = _env_bool("TRADING_ENGINE_USE_NEWS_SENTIMENT", cfg.use_news_sentiment)
    cfg.news_lookback_hours = _env_int("TRADING_ENGINE_NEWS_LOOKBACK_HOURS", cfg.news_lookback_hours)
    cfg.news_max_articles = _env_int("TRADING_ENGINE_NEWS_MAX_ARTICLES", cfg.news_max_articles)
    cfg.news_min_articles = _env_int("TRADING_ENGINE_NEWS_MIN_ARTICLES", cfg.news_min_articles)
    cfg.news_cache_ttl_sec = _env_int("TRADING_ENGINE_NEWS_CACHE_TTL_SEC", cfg.news_cache_ttl_sec)
    cfg.news_day_weight = _env_float("TRADING_ENGINE_NEWS_DAY_WEIGHT", cfg.news_day_weight)
    cfg.news_swing_weight = _env_float("TRADING_ENGINE_NEWS_SWING_WEIGHT", cfg.news_swing_weight)
    cfg.news_market_fallback_ratio = _env_float(
        "TRADING_ENGINE_NEWS_MARKET_FALLBACK_RATIO",
        cfg.news_market_fallback_ratio,
    )
    if os.getenv("TRADING_ENGINE_NEWS_SECTOR_QUERIES_PATH"):
        cfg.news_sector_queries_path = os.getenv(
            "TRADING_ENGINE_NEWS_SECTOR_QUERIES_PATH",
            cfg.news_sector_queries_path,
        )

    return cfg


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on", "y"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _send_text_sync(text: str) -> bool:
    try:
        from backend.integrations.telegram import send_telegram_message

        return bool(asyncio.run(send_telegram_message(text, bot_type="main")))
    except Exception:
        logger.warning("trading telegram notify failed", exc_info=True)
        return False
