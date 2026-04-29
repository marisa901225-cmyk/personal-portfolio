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
