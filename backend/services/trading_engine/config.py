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
    max_day_entries_per_day: int = 4

    # Sizing
    swing_cash_ratio: float = 0.80
    day_cash_ratio: float = 0.20
    use_realized_profit_buffer: bool = True
    swing_entry_order_type: str = "best"
    day_entry_order_type: str = "best"

    # Risk-off cash parking
    risk_off_parking_enabled: bool = True
    risk_off_parking_code: str = "440650"
    risk_off_parking_cash_ratio: float = 0.95
    risk_off_parking_order_type: str = "best"

    # Swing exits
    swing_stop_loss_pct: float = -0.03
    swing_sl_requires_trend_break: bool = True
    swing_trend_ma_window: int = 20
    swing_trend_lookback_bars: int = 60
    swing_trend_break_buffer_pct: float = 0.0
    swing_take_profit_pct: float = 0.05
    swing_trail_start: float = 0.03
    swing_trail_gap: float = -0.02
    swing_max_hold_bars: int = 10
    swing_take_profit_mode: str = "both"  # fixed|trailing|both

    # Day-trade exits
    day_stop_loss_pct: float = -0.012
    day_take_profit_pct: float = 0.03
    day_force_exit_at: str = "15:15"
    day_lock_profit_trigger_pct: float = 0.012
    day_lock_profit_floor_pct: float = 0.005
    day_lock_retrace_gap_pct: float = 0.006
    day_lock_volatility_gap_multiplier: float = 0.60
    day_stoploss_exclude_after_losses: int = 3
    day_stop_llm_review_enabled: bool = True
    day_stop_llm_review_use_paid: bool = True
    day_stop_llm_review_model: str = "gpt-5.5"
    day_stop_llm_review_reasoning_effort: str = "low"
    day_stop_llm_min_day_change_pct: float = 12.0
    day_stop_llm_max_retrace_from_high_pct: float = -3.0
    day_stop_llm_hard_stop_pct: float = -0.022
    day_stop_llm_hold_confidence_min: float = 0.55
    day_chart_review_enabled: bool = True
    day_chart_review_top_n: int = 3
    day_chart_review_chart_wildcard_slots: int = 1
    day_chart_review_paid_min_candidates: int = 3
    day_chart_review_model: str = "gpt-5.5"
    day_chart_review_reasoning_effort: str = "high"
    day_afternoon_entry_start_window_index: int = 2
    day_afternoon_loss_limit_loss_count: int = 2

    # Global risk
    daily_max_loss_pct: float = -0.02
    max_consecutive_losses: int = 2

    # Time windows
    entry_windows: list[tuple[str, str]] = field(
        default_factory=lambda: [
            ("09:05", "09:20"),
            ("09:55", "10:10"),
            ("13:00", "13:20"),
            ("13:55", "14:10"),
        ]
    )
    no_new_entry_after: str = "15:00"
    monitor_interval_sec: int = 240
    day_entry_window_index: int = 0

    # Scanner knobs
    popular_volume_top_n: int = 150
    popular_value_candidate_top_n: int = 400
    popular_sector_top_n: int = 10
    popular_final_top_n: int = 15
    model_top_k: int = 500
    model_mcap_min: int = 1_000_000_000_000
    model_avg_value_20d_min: int = 100_000_000_000
    swing_etf_min_avg_value_20d: int = 100_000_000_000
    day_etf_min_avg_value_5d: int = 50_000_000_000
    day_stock_min_avg_value_5d: int = 10_000_000_000
    day_stock_min_mcap: int = 850_000_000_000
    day_stock_prefer_threshold: float = 0.95
    day_industry_lookback_bars: int = 30
    day_industry_trend_bonus_max: float = 8.0
    day_industry_negative_penalty_max: float = 8.0
    day_momentum_bonus_max: float = 20.0
    day_momentum_bonus_cap_pct: float = 15.0
    day_intraday_strength_weight: float = 1.8
    day_hts_top_view_top_n: int = 20
    day_hts_top_view_bonus_max: float = 3.0
    day_momentum_chase_max_change_pct: float = 26.0
    day_momentum_chase_min_intraday_score: float = 3.0
    day_momentum_pullback_min_day_change_pct: float = 12.0
    day_momentum_pullback_min_window_change_pct: float = -1.0
    day_momentum_pullback_min_last_bar_change_pct: float = -0.25
    day_momentum_pullback_max_retrace_from_high_pct: float = -1.8
    day_min_change_pct: float = 0.5
    day_max_change_pct: float = 6.0
    day_etf_max_change_pct: float = 4.0
    day_hard_drop_exclude_pct: float = -6.0
    day_recent_high_retrace_10d_min_pct: float = -12.0
    day_use_intraday_confirmation: bool = True
    day_intraday_confirmation_bars: int = 3
    day_intraday_min_window_change_pct: float = 0.2
    day_intraday_min_last_bar_change_pct: float = -0.2
    day_intraday_max_retrace_from_high_pct: float = -0.8
    day_intraday_tight_base_min_day_change_pct: float = 1.0
    day_intraday_tight_base_min_window_change_pct: float = 0.05
    day_intraday_tight_base_min_last_bar_change_pct: float = 0.05
    day_intraday_tight_base_max_range_pct: float = 0.8
    day_intraday_tight_base_max_retrace_from_high_pct: float = -0.3
    day_negative_penalty_per_pct: float = 3.0
    day_negative_penalty_max: float = 30.0
    day_theme_candidate_injection_enabled: bool = True
    day_theme_candidate_max_injections: int = 3
    day_theme_candidate_min_sector_score: float = 0.35
    day_theme_candidate_min_avg_value_5d: int = 30_000_000_000
    swing_momentum_bonus_max: float = 12.0
    swing_momentum_bonus_cap_pct: float = 8.0
    swing_negative_penalty_max: float = 30.0
    swing_hard_drop_exclude_pct: float = -6.0
    swing_industry_lookback_bars: int = 60
    swing_industry_trend_bonus_max: float = 14.0
    swing_industry_negative_penalty_max: float = 10.0
    swing_etf_fallback_min_change_pct: float = -1.0
    swing_prefer_sector_etf_on_theme_day: bool = True
    swing_sector_etf_min_sector_score: float = 0.2
    swing_sector_etf_min_breadth: int = 2
    swing_sector_etf_min_score: float = 30.0
    swing_sector_etf_min_change_pct: float = 0.0
    swing_chart_review_enabled: bool = True
    swing_chart_review_top_n: int = 5
    swing_chart_review_paid_min_candidates: int = 3
    swing_chart_review_model: str = "gpt-5.5"
    swing_chart_review_reasoning_effort: str = "high"
    quote_score_limit: int = 30
    allow_etf_swing_fallback: bool = True
    industry_idx_master_path: str = "backend/data/trading_engine_masters/idxcode.mst.zip"
    industry_kospi_master_path: str = "backend/data/trading_engine_masters/kospi_code.mst.zip"
    industry_kosdaq_master_path: str = "backend/data/trading_engine_masters/kosdaq_code.mst.zip"

    # Regime / calendar
    market_proxy_code: str = "069500"
    kosdaq_proxy_code: str = "229200"
    use_kosdaq_confirmation: bool = False
    regime_vol_threshold: float = 0.05
    use_intraday_circuit_breaker: bool = True
    intraday_cb_day_change_pct: float = -3.0
    intraday_cb_1bar_drop_pct: float = -1.2
    intraday_cb_window_minutes: int = 5
    intraday_cb_window_drop_pct: float = -2.0

    # Paths
    state_path: str = "backend/storage/trading_engine/state.json"
    output_dir: str = "backend/storage/trading_engine/output"
    runlog_path: str = "backend/storage/trading_engine/runlog_current.log"

    # Notifications
    telegram_retry_max: int = 3
    notify_on_core_pass_only: bool = True

    # News sentiment (market/sector auxiliary signal)
    use_news_sentiment: bool = True
    news_lookback_hours: int = 18
    news_max_articles: int = 300
    news_min_articles: int = 8
    news_cache_ttl_sec: int = 300
    news_day_weight: float = 6.0
    news_swing_weight: float = 4.0
    news_market_fallback_ratio: float = 0.4
    news_sector_queries_path: str = "backend/data/trading_engine_sector_queries.json"
