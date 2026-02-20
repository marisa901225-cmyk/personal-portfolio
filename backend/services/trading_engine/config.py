from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class TradeEngineConfig:
    # Capital / universe
    initial_capital: int = 1_000_000
    include_etf: bool = True

    # Position limits
    max_swing_positions: int = 1
    max_day_positions: int = 1
    max_total_positions: int = 2

    # Entry limits
    max_swing_entries_per_week: int = 2
    max_swing_entries_per_day: int = 1
    max_day_entries_per_day: int = 1

    # Sizing
    swing_cash_ratio: float = 0.75
    day_cash_ratio: float = 0.20

    # Swing exits
    swing_stop_loss_pct: float = -0.03
    swing_take_profit_pct: float = 0.05
    swing_trail_start: float = 0.03
    swing_trail_gap: float = -0.02
    swing_max_hold_bars: int = 10
    swing_take_profit_mode: str = "both"  # fixed|trailing|both

    # Day-trade exits
    day_stop_loss_pct: float = -0.012
    day_take_profit_pct: float = 0.018
    day_force_exit_at: str = "15:15"

    # Global risk
    daily_max_loss_pct: float = -0.02
    max_consecutive_losses: int = 2

    # Time windows
    entry_windows: list[tuple[str, str]] = field(
        default_factory=lambda: [("09:05", "09:20"), ("13:00", "13:20")]
    )
    no_new_entry_after: str = "15:00"
    monitor_interval_sec: int = 240
    day_entry_only_second_window: bool = True

    # Scanner knobs
    popular_volume_top_n: int = 100
    popular_value_candidate_top_n: int = 200
    popular_final_top_n: int = 10
    model_top_k: int = 500
    model_mcap_min: int = 1_000_000_000_000
    model_avg_value_20d_min: int = 500_000_000_000
    swing_etf_min_avg_value_20d: int = 100_000_000_000
    day_etf_min_avg_value_5d: int = 50_000_000_000
    quote_score_limit: int = 30
    allow_etf_swing_fallback: bool = True

    # Regime / calendar
    market_proxy_code: str = "069500"
    kosdaq_proxy_code: str = "229200"
    use_kosdaq_confirmation: bool = False

    # Paths
    state_path: str = "backend/storage/trading_engine/state.json"
    output_dir: str = "backend/storage/trading_engine/output"
    runlog_path: str = "backend/storage/trading_engine/runlog_current.log"

    # Notifications
    telegram_retry_max: int = 3
    notify_on_core_pass_only: bool = True
