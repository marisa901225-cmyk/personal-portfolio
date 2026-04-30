from __future__ import annotations

from unittest.mock import patch

from backend.services.trading_engine.config import TradeEngineConfig
from backend.services.trading_engine.runtime_config import load_trade_engine_config_from_env


def test_runtime_config_applies_core_risk_overrides() -> None:
    with patch.dict(
        "os.environ",
        {
            "TRADING_ENGINE_INITIAL_CAPITAL": "2500000",
            "TRADING_ENGINE_DAILY_MAX_LOSS_PCT": "-0.03",
            "TRADING_ENGINE_MAX_CONSECUTIVE_LOSSES": "4",
            "TRADING_ENGINE_NO_NEW_ENTRY_AFTER": "14:35",
            "TRADING_ENGINE_DAY_FORCE_EXIT_AT": "15:10",
            "TRADING_ENGINE_ENTRY_WINDOWS": "09:05-09:20,13:00-13:20",
        },
        clear=False,
    ):
        cfg = load_trade_engine_config_from_env()

    assert cfg.initial_capital == 2_500_000
    assert cfg.daily_max_loss_pct == -0.03
    assert cfg.max_consecutive_losses == 4
    assert cfg.no_new_entry_after == "14:35"
    assert cfg.day_force_exit_at == "15:10"
    assert cfg.entry_windows == [("09:05", "09:20"), ("13:00", "13:20")]


def test_runtime_config_keeps_default_entry_windows_on_invalid_override() -> None:
    default_windows = TradeEngineConfig().entry_windows
    with patch.dict(
        "os.environ",
        {"TRADING_ENGINE_ENTRY_WINDOWS": "09:05-09:20,bad-window"},
        clear=False,
    ):
        cfg = load_trade_engine_config_from_env()

    assert cfg.entry_windows == default_windows


def test_runtime_config_applies_frequently_tuned_scoring_and_global_signal_overrides() -> None:
    with patch.dict(
        "os.environ",
        {
            "TRADING_ENGINE_DAY_STOCK_PREFER_THRESHOLD": "0.93",
            "TRADING_ENGINE_DAY_ETF_INTRADAY_STRENGTH_WEIGHT": "3.4",
            "TRADING_ENGINE_DAY_GLOBAL_SECTOR_NEGATIVE_PENALTY_MAX": "7.5",
            "TRADING_ENGINE_SWING_GLOBAL_MARKET_NEGATIVE_PENALTY_MAX": "3.1",
            "TRADING_ENGINE_USE_GLOBAL_MARKET_LEADERSHIP": "0",
            "TRADING_ENGINE_GLOBAL_MARKET_SIGNAL_EXCHANGES": "nas,nys",
            "TRADING_ENGINE_GLOBAL_MARKET_SIGNAL_MIN_VOLUME": "750000",
            "TRADING_ENGINE_DAY_REUSE_UNUSED_SWING_CASH_MIN_KRW": "120000",
            "TRADING_ENGINE_DAY_OVERNIGHT_CARRY_MAX_CALENDAR_GAP_DAYS": "4",
        },
        clear=False,
    ):
        cfg = load_trade_engine_config_from_env()

    assert cfg.day_stock_prefer_threshold == 0.93
    assert cfg.day_etf_intraday_strength_weight == 3.4
    assert cfg.day_global_sector_negative_penalty_max == 7.5
    assert cfg.swing_global_market_negative_penalty_max == 3.1
    assert cfg.use_global_market_leadership is False
    assert cfg.global_market_signal_exchanges == ("NAS", "NYS")
    assert cfg.global_market_signal_min_volume == 750_000
    assert cfg.day_reuse_unused_swing_cash_min_krw == 120_000
    assert cfg.day_overnight_carry_max_calendar_gap_days == 4
