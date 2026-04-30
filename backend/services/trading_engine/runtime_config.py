from __future__ import annotations

import os

from .config import TradeEngineConfig
from .utils import parse_hhmm


def load_trade_engine_config_from_env() -> TradeEngineConfig:
    cfg = TradeEngineConfig()
    _apply_path_overrides(cfg)
    _apply_general_overrides(cfg)
    _apply_daytrade_overrides(cfg)
    _apply_swing_overrides(cfg)
    _apply_regime_and_news_overrides(cfg)
    _apply_master_path_overrides(cfg)
    return cfg


def _apply_path_overrides(cfg: TradeEngineConfig) -> None:
    cfg.state_path = _env_text("TRADING_ENGINE_STATE_PATH", cfg.state_path)
    cfg.output_dir = _env_text("TRADING_ENGINE_OUTPUT_DIR", cfg.output_dir)
    cfg.runlog_path = _env_text("TRADING_ENGINE_RUNLOG_PATH", cfg.runlog_path)


def _apply_general_overrides(cfg: TradeEngineConfig) -> None:
    cfg.initial_capital = _env_int("TRADING_ENGINE_INITIAL_CAPITAL", cfg.initial_capital)
    cfg.include_etf = _env_bool("TRADING_ENGINE_INCLUDE_ETF", cfg.include_etf)
    cfg.monitor_interval_sec = _env_int("TRADING_ENGINE_MONITOR_SEC", cfg.monitor_interval_sec)
    cfg.telegram_retry_max = _env_int("TRADING_ENGINE_TELEGRAM_RETRY", cfg.telegram_retry_max)
    cfg.max_swing_positions = _env_int("TRADING_ENGINE_MAX_SWING_POSITIONS", cfg.max_swing_positions)
    cfg.max_day_positions = _env_int("TRADING_ENGINE_MAX_DAY_POSITIONS", cfg.max_day_positions)
    cfg.max_total_positions = _env_int("TRADING_ENGINE_MAX_TOTAL_POSITIONS", cfg.max_total_positions)
    cfg.max_swing_entries_per_week = _env_int(
        "TRADING_ENGINE_MAX_SWING_ENTRIES_PER_WEEK",
        cfg.max_swing_entries_per_week,
    )
    cfg.max_swing_entries_per_day = _env_int(
        "TRADING_ENGINE_MAX_SWING_ENTRIES_PER_DAY",
        cfg.max_swing_entries_per_day,
    )
    cfg.max_day_entries_per_day = _env_int(
        "TRADING_ENGINE_MAX_DAY_ENTRIES_PER_DAY",
        cfg.max_day_entries_per_day,
    )
    cfg.swing_cash_ratio = _env_float("TRADING_ENGINE_SWING_CASH_RATIO", cfg.swing_cash_ratio)
    cfg.day_cash_ratio = _env_float("TRADING_ENGINE_DAY_CASH_RATIO", cfg.day_cash_ratio)
    cfg.day_reuse_unused_swing_cash_enabled = _env_bool(
        "TRADING_ENGINE_DAY_REUSE_UNUSED_SWING_CASH_ENABLED",
        cfg.day_reuse_unused_swing_cash_enabled,
    )
    cfg.day_reuse_unused_swing_cash_min_krw = _env_int(
        "TRADING_ENGINE_DAY_REUSE_UNUSED_SWING_CASH_MIN_KRW",
        cfg.day_reuse_unused_swing_cash_min_krw,
    )
    cfg.popular_sector_top_n = _env_int(
        "TRADING_ENGINE_POPULAR_SECTOR_TOP_N",
        cfg.popular_sector_top_n,
    )
    cfg.use_realized_profit_buffer = _env_bool(
        "TRADING_ENGINE_USE_REALIZED_PROFIT_BUFFER",
        cfg.use_realized_profit_buffer,
    )
    cfg.swing_entry_order_type = _env_text(
        "TRADING_ENGINE_SWING_ENTRY_ORDER_TYPE",
        cfg.swing_entry_order_type,
    )
    cfg.day_entry_order_type = _env_text(
        "TRADING_ENGINE_DAY_ENTRY_ORDER_TYPE",
        cfg.day_entry_order_type,
    )
    cfg.risk_off_parking_enabled = _env_bool(
        "TRADING_ENGINE_RISK_OFF_PARKING_ENABLED",
        cfg.risk_off_parking_enabled,
    )
    cfg.risk_off_parking_cash_ratio = _env_float(
        "TRADING_ENGINE_RISK_OFF_PARKING_CASH_RATIO",
        cfg.risk_off_parking_cash_ratio,
    )
    cfg.risk_off_parking_order_type = _env_text(
        "TRADING_ENGINE_RISK_OFF_PARKING_ORDER_TYPE",
        cfg.risk_off_parking_order_type,
    )
    cfg.risk_off_parking_code = _env_text(
        "TRADING_ENGINE_RISK_OFF_PARKING_CODE",
        cfg.risk_off_parking_code,
    )
    cfg.daily_max_loss_pct = _env_float("TRADING_ENGINE_DAILY_MAX_LOSS_PCT", cfg.daily_max_loss_pct)
    cfg.max_consecutive_losses = _env_int(
        "TRADING_ENGINE_MAX_CONSECUTIVE_LOSSES",
        cfg.max_consecutive_losses,
    )
    cfg.no_new_entry_after = _env_valid_hhmm(
        "TRADING_ENGINE_NO_NEW_ENTRY_AFTER",
        cfg.no_new_entry_after,
    )
    cfg.day_force_exit_at = _env_valid_hhmm(
        "TRADING_ENGINE_DAY_FORCE_EXIT_AT",
        cfg.day_force_exit_at,
    )
    cfg.entry_windows = _env_entry_windows("TRADING_ENGINE_ENTRY_WINDOWS", cfg.entry_windows)
    cfg.market_proxy_code = _env_text("TRADING_ENGINE_MARKET_PROXY_CODE", cfg.market_proxy_code)
    cfg.kosdaq_proxy_code = _env_text("TRADING_ENGINE_KOSDAQ_PROXY_CODE", cfg.kosdaq_proxy_code)
    cfg.use_kosdaq_confirmation = _env_bool(
        "TRADING_ENGINE_USE_KOSDAQ_CONFIRMATION",
        cfg.use_kosdaq_confirmation,
    )
    cfg.notify_on_core_pass_only = _env_bool(
        "TRADING_ENGINE_NOTIFY_ON_CORE_PASS_ONLY",
        cfg.notify_on_core_pass_only,
    )


def _apply_daytrade_overrides(cfg: TradeEngineConfig) -> None:
    cfg.day_stop_loss_pct = _env_float(
        "TRADING_ENGINE_DAY_STOP_LOSS_PCT",
        cfg.day_stop_loss_pct,
    )
    cfg.day_stock_min_avg_value_5d = _env_int(
        "TRADING_ENGINE_DAY_STOCK_MIN_AVG_VALUE_5D",
        cfg.day_stock_min_avg_value_5d,
    )
    cfg.day_stock_min_mcap = _env_int(
        "TRADING_ENGINE_DAY_STOCK_MIN_MCAP",
        cfg.day_stock_min_mcap,
    )
    cfg.day_stock_prefer_threshold = _env_float(
        "TRADING_ENGINE_DAY_STOCK_PREFER_THRESHOLD",
        cfg.day_stock_prefer_threshold,
    )
    cfg.day_industry_lookback_bars = _env_int(
        "TRADING_ENGINE_DAY_INDUSTRY_LOOKBACK_BARS",
        cfg.day_industry_lookback_bars,
    )
    cfg.day_industry_trend_bonus_max = _env_float(
        "TRADING_ENGINE_DAY_INDUSTRY_TREND_BONUS_MAX",
        cfg.day_industry_trend_bonus_max,
    )
    cfg.day_industry_negative_penalty_max = _env_float(
        "TRADING_ENGINE_DAY_INDUSTRY_NEGATIVE_PENALTY_MAX",
        cfg.day_industry_negative_penalty_max,
    )
    cfg.day_base_score = _env_float(
        "TRADING_ENGINE_DAY_BASE_SCORE",
        cfg.day_base_score,
    )
    cfg.day_avg_value_bonus_unit = _env_float(
        "TRADING_ENGINE_DAY_AVG_VALUE_BONUS_UNIT",
        cfg.day_avg_value_bonus_unit,
    )
    cfg.day_avg_value_bonus_max = _env_float(
        "TRADING_ENGINE_DAY_AVG_VALUE_BONUS_MAX",
        cfg.day_avg_value_bonus_max,
    )
    cfg.day_momentum_bonus_max = _env_float(
        "TRADING_ENGINE_DAY_MOMENTUM_BONUS_MAX",
        cfg.day_momentum_bonus_max,
    )
    cfg.day_momentum_bonus_cap_pct = _env_float(
        "TRADING_ENGINE_DAY_MOMENTUM_BONUS_CAP_PCT",
        cfg.day_momentum_bonus_cap_pct,
    )
    cfg.day_hard_drop_exclude_pct = _env_float(
        "TRADING_ENGINE_DAY_HARD_DROP_EXCLUDE_PCT",
        cfg.day_hard_drop_exclude_pct,
    )
    cfg.day_recent_high_retrace_10d_min_pct = _env_float(
        "TRADING_ENGINE_DAY_RECENT_HIGH_RETRACE_10D_MIN_PCT",
        cfg.day_recent_high_retrace_10d_min_pct,
    )
    cfg.day_min_change_pct = _env_float(
        "TRADING_ENGINE_DAY_MIN_CHANGE_PCT",
        cfg.day_min_change_pct,
    )
    cfg.day_max_change_pct = _env_float(
        "TRADING_ENGINE_DAY_MAX_CHANGE_PCT",
        cfg.day_max_change_pct,
    )
    cfg.day_etf_max_change_pct = _env_float(
        "TRADING_ENGINE_DAY_ETF_MAX_CHANGE_PCT",
        cfg.day_etf_max_change_pct,
    )
    cfg.day_use_intraday_confirmation = _env_bool(
        "TRADING_ENGINE_DAY_USE_INTRADAY_CONFIRMATION",
        cfg.day_use_intraday_confirmation,
    )
    cfg.day_intraday_confirmation_bars = _env_int(
        "TRADING_ENGINE_DAY_INTRADAY_CONFIRMATION_BARS",
        cfg.day_intraday_confirmation_bars,
    )
    cfg.day_intraday_min_window_change_pct = _env_float(
        "TRADING_ENGINE_DAY_INTRADAY_MIN_WINDOW_CHANGE_PCT",
        cfg.day_intraday_min_window_change_pct,
    )
    cfg.day_intraday_min_last_bar_change_pct = _env_float(
        "TRADING_ENGINE_DAY_INTRADAY_MIN_LAST_BAR_CHANGE_PCT",
        cfg.day_intraday_min_last_bar_change_pct,
    )
    cfg.day_intraday_max_retrace_from_high_pct = _env_float(
        "TRADING_ENGINE_DAY_INTRADAY_MAX_RETRACE_FROM_HIGH_PCT",
        cfg.day_intraday_max_retrace_from_high_pct,
    )
    cfg.day_intraday_tight_base_min_day_change_pct = _env_float(
        "TRADING_ENGINE_DAY_INTRADAY_TIGHT_BASE_MIN_DAY_CHANGE_PCT",
        cfg.day_intraday_tight_base_min_day_change_pct,
    )
    cfg.day_intraday_tight_base_min_window_change_pct = _env_float(
        "TRADING_ENGINE_DAY_INTRADAY_TIGHT_BASE_MIN_WINDOW_CHANGE_PCT",
        cfg.day_intraday_tight_base_min_window_change_pct,
    )
    cfg.day_intraday_tight_base_min_last_bar_change_pct = _env_float(
        "TRADING_ENGINE_DAY_INTRADAY_TIGHT_BASE_MIN_LAST_BAR_CHANGE_PCT",
        cfg.day_intraday_tight_base_min_last_bar_change_pct,
    )
    cfg.day_intraday_tight_base_max_range_pct = _env_float(
        "TRADING_ENGINE_DAY_INTRADAY_TIGHT_BASE_MAX_RANGE_PCT",
        cfg.day_intraday_tight_base_max_range_pct,
    )
    cfg.day_intraday_tight_base_max_retrace_from_high_pct = _env_float(
        "TRADING_ENGINE_DAY_INTRADAY_TIGHT_BASE_MAX_RETRACE_FROM_HIGH_PCT",
        cfg.day_intraday_tight_base_max_retrace_from_high_pct,
    )
    cfg.day_negative_penalty_per_pct = _env_float(
        "TRADING_ENGINE_DAY_NEGATIVE_PENALTY_PER_PCT",
        cfg.day_negative_penalty_per_pct,
    )
    cfg.day_negative_penalty_max = _env_float(
        "TRADING_ENGINE_DAY_NEGATIVE_PENALTY_MAX",
        cfg.day_negative_penalty_max,
    )
    cfg.day_negative_penalty_full_pct = _env_float(
        "TRADING_ENGINE_DAY_NEGATIVE_PENALTY_FULL_PCT",
        cfg.day_negative_penalty_full_pct,
    )
    cfg.day_volatility_penalty_start_pct = _env_float(
        "TRADING_ENGINE_DAY_VOLATILITY_PENALTY_START_PCT",
        cfg.day_volatility_penalty_start_pct,
    )
    cfg.day_volatility_penalty_full_pct = _env_float(
        "TRADING_ENGINE_DAY_VOLATILITY_PENALTY_FULL_PCT",
        cfg.day_volatility_penalty_full_pct,
    )
    cfg.day_volatility_penalty_max = _env_float(
        "TRADING_ENGINE_DAY_VOLATILITY_PENALTY_MAX",
        cfg.day_volatility_penalty_max,
    )
    cfg.day_extreme_momentum_penalty = _env_float(
        "TRADING_ENGINE_DAY_EXTREME_MOMENTUM_PENALTY",
        cfg.day_extreme_momentum_penalty,
    )
    cfg.day_wide_spread_penalty = _env_float(
        "TRADING_ENGINE_DAY_WIDE_SPREAD_PENALTY",
        cfg.day_wide_spread_penalty,
    )
    cfg.day_fallback_penalty = _env_float(
        "TRADING_ENGINE_DAY_FALLBACK_PENALTY",
        cfg.day_fallback_penalty,
    )
    cfg.day_legacy_top10_bonus = _env_float(
        "TRADING_ENGINE_DAY_LEGACY_TOP10_BONUS",
        cfg.day_legacy_top10_bonus,
    )
    cfg.day_non_etf_bonus = _env_float(
        "TRADING_ENGINE_DAY_NON_ETF_BONUS",
        cfg.day_non_etf_bonus,
    )
    cfg.day_intraday_strength_weight = _env_float(
        "TRADING_ENGINE_DAY_INTRADAY_STRENGTH_WEIGHT",
        cfg.day_intraday_strength_weight,
    )
    cfg.day_etf_momentum_bonus_scale = _env_float(
        "TRADING_ENGINE_DAY_ETF_MOMENTUM_BONUS_SCALE",
        cfg.day_etf_momentum_bonus_scale,
    )
    cfg.day_etf_volatility_penalty_scale = _env_float(
        "TRADING_ENGINE_DAY_ETF_VOLATILITY_PENALTY_SCALE",
        cfg.day_etf_volatility_penalty_scale,
    )
    cfg.day_etf_intraday_strength_weight = _env_float(
        "TRADING_ENGINE_DAY_ETF_INTRADAY_STRENGTH_WEIGHT",
        cfg.day_etf_intraday_strength_weight,
    )
    cfg.day_etf_industry_trend_scale = _env_float(
        "TRADING_ENGINE_DAY_ETF_INDUSTRY_TREND_SCALE",
        cfg.day_etf_industry_trend_scale,
    )
    cfg.day_etf_news_weight_scale = _env_float(
        "TRADING_ENGINE_DAY_ETF_NEWS_WEIGHT_SCALE",
        cfg.day_etf_news_weight_scale,
    )
    cfg.day_etf_sector_bucket_bonus = _env_float(
        "TRADING_ENGINE_DAY_ETF_SECTOR_BUCKET_BONUS",
        cfg.day_etf_sector_bucket_bonus,
    )
    cfg.day_etf_theme_sector_bonus = _env_float(
        "TRADING_ENGINE_DAY_ETF_THEME_SECTOR_BONUS",
        cfg.day_etf_theme_sector_bonus,
    )
    cfg.day_etf_positive_sector_news_bonus_max = _env_float(
        "TRADING_ENGINE_DAY_ETF_POSITIVE_SECTOR_NEWS_BONUS_MAX",
        cfg.day_etf_positive_sector_news_bonus_max,
    )
    cfg.day_etf_positive_market_breadth_bonus_max = _env_float(
        "TRADING_ENGINE_DAY_ETF_POSITIVE_MARKET_BREADTH_BONUS_MAX",
        cfg.day_etf_positive_market_breadth_bonus_max,
    )
    cfg.day_global_sector_positive_bonus_max = _env_float(
        "TRADING_ENGINE_DAY_GLOBAL_SECTOR_POSITIVE_BONUS_MAX",
        cfg.day_global_sector_positive_bonus_max,
    )
    cfg.day_global_sector_negative_penalty_max = _env_float(
        "TRADING_ENGINE_DAY_GLOBAL_SECTOR_NEGATIVE_PENALTY_MAX",
        cfg.day_global_sector_negative_penalty_max,
    )
    cfg.day_global_market_negative_penalty_max = _env_float(
        "TRADING_ENGINE_DAY_GLOBAL_MARKET_NEGATIVE_PENALTY_MAX",
        cfg.day_global_market_negative_penalty_max,
    )
    cfg.day_hts_top_view_top_n = _env_int(
        "TRADING_ENGINE_DAY_HTS_TOP_VIEW_TOP_N",
        cfg.day_hts_top_view_top_n,
    )
    cfg.day_hts_top_view_bonus_max = _env_float(
        "TRADING_ENGINE_DAY_HTS_TOP_VIEW_BONUS_MAX",
        cfg.day_hts_top_view_bonus_max,
    )
    cfg.day_momentum_chase_max_change_pct = _env_float(
        "TRADING_ENGINE_DAY_MOMENTUM_CHASE_MAX_CHANGE_PCT",
        cfg.day_momentum_chase_max_change_pct,
    )
    cfg.day_momentum_chase_min_intraday_score = _env_float(
        "TRADING_ENGINE_DAY_MOMENTUM_CHASE_MIN_INTRADAY_SCORE",
        cfg.day_momentum_chase_min_intraday_score,
    )
    cfg.day_momentum_pullback_min_day_change_pct = _env_float(
        "TRADING_ENGINE_DAY_MOMENTUM_PULLBACK_MIN_DAY_CHANGE_PCT",
        cfg.day_momentum_pullback_min_day_change_pct,
    )
    cfg.day_momentum_pullback_min_window_change_pct = _env_float(
        "TRADING_ENGINE_DAY_MOMENTUM_PULLBACK_MIN_WINDOW_CHANGE_PCT",
        cfg.day_momentum_pullback_min_window_change_pct,
    )
    cfg.day_momentum_pullback_min_last_bar_change_pct = _env_float(
        "TRADING_ENGINE_DAY_MOMENTUM_PULLBACK_MIN_LAST_BAR_CHANGE_PCT",
        cfg.day_momentum_pullback_min_last_bar_change_pct,
    )
    cfg.day_momentum_pullback_max_retrace_from_high_pct = _env_float(
        "TRADING_ENGINE_DAY_MOMENTUM_PULLBACK_MAX_RETRACE_FROM_HIGH_PCT",
        cfg.day_momentum_pullback_max_retrace_from_high_pct,
    )
    cfg.day_theme_candidate_injection_enabled = _env_bool(
        "TRADING_ENGINE_DAY_THEME_CANDIDATE_INJECTION_ENABLED",
        cfg.day_theme_candidate_injection_enabled,
    )
    cfg.day_theme_candidate_max_injections = _env_int(
        "TRADING_ENGINE_DAY_THEME_CANDIDATE_MAX_INJECTIONS",
        cfg.day_theme_candidate_max_injections,
    )
    cfg.day_theme_candidate_min_sector_score = _env_float(
        "TRADING_ENGINE_DAY_THEME_CANDIDATE_MIN_SECTOR_SCORE",
        cfg.day_theme_candidate_min_sector_score,
    )
    cfg.day_theme_candidate_min_avg_value_5d = _env_int(
        "TRADING_ENGINE_DAY_THEME_CANDIDATE_MIN_AVG_VALUE_5D",
        cfg.day_theme_candidate_min_avg_value_5d,
    )
    cfg.day_lock_profit_trigger_pct = _env_float(
        "TRADING_ENGINE_DAY_LOCK_PROFIT_TRIGGER_PCT",
        cfg.day_lock_profit_trigger_pct,
    )
    cfg.day_lock_profit_floor_pct = _env_float(
        "TRADING_ENGINE_DAY_LOCK_PROFIT_FLOOR_PCT",
        cfg.day_lock_profit_floor_pct,
    )
    cfg.day_lock_retrace_gap_pct = _env_float(
        "TRADING_ENGINE_DAY_LOCK_RETRACE_GAP_PCT",
        cfg.day_lock_retrace_gap_pct,
    )
    cfg.day_lock_volatility_gap_multiplier = _env_float(
        "TRADING_ENGINE_DAY_LOCK_VOLATILITY_GAP_MULTIPLIER",
        cfg.day_lock_volatility_gap_multiplier,
    )
    cfg.day_stop_loss_volatility_multiplier = _env_float(
        "TRADING_ENGINE_DAY_STOP_LOSS_VOLATILITY_MULTIPLIER",
        cfg.day_stop_loss_volatility_multiplier,
    )
    cfg.day_stop_loss_max_pct = _env_float(
        "TRADING_ENGINE_DAY_STOP_LOSS_MAX_PCT",
        cfg.day_stop_loss_max_pct,
    )
    cfg.day_stoploss_exclude_after_losses = _env_int(
        "TRADING_ENGINE_DAY_STOPLOSS_EXCLUDE_AFTER_LOSSES",
        cfg.day_stoploss_exclude_after_losses,
    )
    cfg.day_stop_llm_review_enabled = _env_bool(
        "TRADING_ENGINE_DAY_STOP_LLM_REVIEW_ENABLED",
        cfg.day_stop_llm_review_enabled,
    )
    cfg.day_stop_llm_review_use_paid = _env_bool(
        "TRADING_ENGINE_DAY_STOP_LLM_REVIEW_USE_PAID",
        cfg.day_stop_llm_review_use_paid,
    )
    cfg.day_stop_llm_review_model = _env_text(
        "TRADING_ENGINE_DAY_STOP_LLM_REVIEW_MODEL",
        cfg.day_stop_llm_review_model,
    )
    cfg.day_stop_llm_review_reasoning_effort = _env_text(
        "TRADING_ENGINE_DAY_STOP_LLM_REVIEW_REASONING_EFFORT",
        cfg.day_stop_llm_review_reasoning_effort,
    )
    cfg.day_stop_llm_min_day_change_pct = _env_float(
        "TRADING_ENGINE_DAY_STOP_LLM_MIN_DAY_CHANGE_PCT",
        cfg.day_stop_llm_min_day_change_pct,
    )
    cfg.day_stop_llm_max_retrace_from_high_pct = _env_float(
        "TRADING_ENGINE_DAY_STOP_LLM_MAX_RETRACE_FROM_HIGH_PCT",
        cfg.day_stop_llm_max_retrace_from_high_pct,
    )
    cfg.day_stop_llm_hard_stop_pct = _env_float(
        "TRADING_ENGINE_DAY_STOP_LLM_HARD_STOP_PCT",
        cfg.day_stop_llm_hard_stop_pct,
    )
    cfg.day_stop_llm_hold_confidence_min = _env_float(
        "TRADING_ENGINE_DAY_STOP_LLM_HOLD_CONFIDENCE_MIN",
        cfg.day_stop_llm_hold_confidence_min,
    )
    cfg.day_overnight_carry_enabled = _env_bool(
        "TRADING_ENGINE_DAY_OVERNIGHT_CARRY_ENABLED",
        cfg.day_overnight_carry_enabled,
    )
    cfg.day_overnight_carry_model = _env_text(
        "TRADING_ENGINE_DAY_OVERNIGHT_CARRY_MODEL",
        cfg.day_overnight_carry_model,
    )
    cfg.day_overnight_carry_reasoning_effort = _env_text(
        "TRADING_ENGINE_DAY_OVERNIGHT_CARRY_REASONING_EFFORT",
        cfg.day_overnight_carry_reasoning_effort,
    )
    cfg.day_overnight_carry_hold_confidence_min = _env_float(
        "TRADING_ENGINE_DAY_OVERNIGHT_CARRY_HOLD_CONFIDENCE_MIN",
        cfg.day_overnight_carry_hold_confidence_min,
    )
    cfg.day_overnight_carry_max_calendar_gap_days = _env_int(
        "TRADING_ENGINE_DAY_OVERNIGHT_CARRY_MAX_CALENDAR_GAP_DAYS",
        cfg.day_overnight_carry_max_calendar_gap_days,
    )
    cfg.day_chart_review_enabled = _env_bool(
        "TRADING_ENGINE_DAY_CHART_REVIEW_ENABLED",
        cfg.day_chart_review_enabled,
    )
    cfg.day_chart_review_top_n = _env_int(
        "TRADING_ENGINE_DAY_CHART_REVIEW_TOP_N",
        cfg.day_chart_review_top_n,
    )
    cfg.day_chart_review_chart_wildcard_slots = _env_int(
        "TRADING_ENGINE_DAY_CHART_REVIEW_CHART_WILDCARD_SLOTS",
        cfg.day_chart_review_chart_wildcard_slots,
    )
    cfg.day_chart_review_paid_min_candidates = _env_int(
        "TRADING_ENGINE_DAY_CHART_REVIEW_PAID_MIN_CANDIDATES",
        cfg.day_chart_review_paid_min_candidates,
    )
    cfg.day_chart_review_model = _env_text(
        "TRADING_ENGINE_DAY_CHART_REVIEW_MODEL",
        cfg.day_chart_review_model,
    )
    cfg.day_chart_review_reasoning_effort = _env_text(
        "TRADING_ENGINE_DAY_CHART_REVIEW_REASONING_EFFORT",
        cfg.day_chart_review_reasoning_effort,
    )
    cfg.day_afternoon_entry_start_window_index = _env_int(
        "TRADING_ENGINE_DAY_AFTERNOON_ENTRY_START_WINDOW_INDEX",
        cfg.day_afternoon_entry_start_window_index,
    )
    cfg.day_afternoon_loss_limit_loss_count = _env_int(
        "TRADING_ENGINE_DAY_AFTERNOON_LOSS_LIMIT_LOSS_COUNT",
        cfg.day_afternoon_loss_limit_loss_count,
    )
    cfg.defer_swing_scan_in_day_entry_window = _env_bool(
        "TRADING_ENGINE_DEFER_SWING_SCAN_IN_DAY_ENTRY_WINDOW",
        cfg.defer_swing_scan_in_day_entry_window,
    )


def _apply_swing_overrides(cfg: TradeEngineConfig) -> None:
    cfg.swing_take_profit_mode = _env_text(
        "TRADING_ENGINE_SWING_TAKE_PROFIT_MODE",
        cfg.swing_take_profit_mode,
    )
    cfg.swing_source_model_strict_bonus = _env_float(
        "TRADING_ENGINE_SWING_SOURCE_MODEL_STRICT_BONUS",
        cfg.swing_source_model_strict_bonus,
    )
    cfg.swing_source_model_relaxed_bonus = _env_float(
        "TRADING_ENGINE_SWING_SOURCE_MODEL_RELAXED_BONUS",
        cfg.swing_source_model_relaxed_bonus,
    )
    cfg.swing_ma20_bonus = _env_float(
        "TRADING_ENGINE_SWING_MA20_BONUS",
        cfg.swing_ma20_bonus,
    )
    cfg.swing_ma20_cross_bonus = _env_float(
        "TRADING_ENGINE_SWING_MA20_CROSS_BONUS",
        cfg.swing_ma20_cross_bonus,
    )
    cfg.swing_avg_value_bonus_unit = _env_float(
        "TRADING_ENGINE_SWING_AVG_VALUE_BONUS_UNIT",
        cfg.swing_avg_value_bonus_unit,
    )
    cfg.swing_avg_value_bonus_max = _env_float(
        "TRADING_ENGINE_SWING_AVG_VALUE_BONUS_MAX",
        cfg.swing_avg_value_bonus_max,
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
    cfg.swing_ma20_premium_penalty_start_pct = _env_float(
        "TRADING_ENGINE_SWING_MA20_PREMIUM_PENALTY_START_PCT",
        cfg.swing_ma20_premium_penalty_start_pct,
    )
    cfg.swing_ma20_premium_penalty_full_pct = _env_float(
        "TRADING_ENGINE_SWING_MA20_PREMIUM_PENALTY_FULL_PCT",
        cfg.swing_ma20_premium_penalty_full_pct,
    )
    cfg.swing_ma20_premium_penalty_max = _env_float(
        "TRADING_ENGINE_SWING_MA20_PREMIUM_PENALTY_MAX",
        cfg.swing_ma20_premium_penalty_max,
    )
    cfg.swing_structure_volume_ratio_start = _env_float(
        "TRADING_ENGINE_SWING_STRUCTURE_VOLUME_RATIO_START",
        cfg.swing_structure_volume_ratio_start,
    )
    cfg.swing_structure_volume_ratio_full = _env_float(
        "TRADING_ENGINE_SWING_STRUCTURE_VOLUME_RATIO_FULL",
        cfg.swing_structure_volume_ratio_full,
    )
    cfg.swing_structure_volume_weight_floor = _env_float(
        "TRADING_ENGINE_SWING_STRUCTURE_VOLUME_WEIGHT_FLOOR",
        cfg.swing_structure_volume_weight_floor,
    )
    cfg.swing_structure_volume_weight_ceiling = _env_float(
        "TRADING_ENGINE_SWING_STRUCTURE_VOLUME_WEIGHT_CEILING",
        cfg.swing_structure_volume_weight_ceiling,
    )
    cfg.swing_volatility_penalty_start_pct = _env_float(
        "TRADING_ENGINE_SWING_VOLATILITY_PENALTY_START_PCT",
        cfg.swing_volatility_penalty_start_pct,
    )
    cfg.swing_volatility_penalty_full_pct = _env_float(
        "TRADING_ENGINE_SWING_VOLATILITY_PENALTY_FULL_PCT",
        cfg.swing_volatility_penalty_full_pct,
    )
    cfg.swing_volatility_penalty_max = _env_float(
        "TRADING_ENGINE_SWING_VOLATILITY_PENALTY_MAX",
        cfg.swing_volatility_penalty_max,
    )
    cfg.swing_hard_drop_exclude_pct = _env_float(
        "TRADING_ENGINE_SWING_HARD_DROP_EXCLUDE_PCT",
        cfg.swing_hard_drop_exclude_pct,
    )
    cfg.swing_industry_lookback_bars = _env_int(
        "TRADING_ENGINE_SWING_INDUSTRY_LOOKBACK_BARS",
        cfg.swing_industry_lookback_bars,
    )
    cfg.swing_industry_trend_bonus_max = _env_float(
        "TRADING_ENGINE_SWING_INDUSTRY_TREND_BONUS_MAX",
        cfg.swing_industry_trend_bonus_max,
    )
    cfg.swing_industry_negative_penalty_max = _env_float(
        "TRADING_ENGINE_SWING_INDUSTRY_NEGATIVE_PENALTY_MAX",
        cfg.swing_industry_negative_penalty_max,
    )
    cfg.swing_etf_fallback_min_change_pct = _env_float(
        "TRADING_ENGINE_SWING_ETF_FALLBACK_MIN_CHANGE_PCT",
        cfg.swing_etf_fallback_min_change_pct,
    )
    cfg.swing_prefer_sector_etf_on_theme_day = _env_bool(
        "TRADING_ENGINE_SWING_PREFER_SECTOR_ETF_ON_THEME_DAY",
        cfg.swing_prefer_sector_etf_on_theme_day,
    )
    cfg.swing_sector_etf_min_sector_score = _env_float(
        "TRADING_ENGINE_SWING_SECTOR_ETF_MIN_SECTOR_SCORE",
        cfg.swing_sector_etf_min_sector_score,
    )
    cfg.swing_sector_etf_min_breadth = _env_int(
        "TRADING_ENGINE_SWING_SECTOR_ETF_MIN_BREADTH",
        cfg.swing_sector_etf_min_breadth,
    )
    cfg.swing_sector_etf_min_score = _env_float(
        "TRADING_ENGINE_SWING_SECTOR_ETF_MIN_SCORE",
        cfg.swing_sector_etf_min_score,
    )
    cfg.swing_sector_etf_min_change_pct = _env_float(
        "TRADING_ENGINE_SWING_SECTOR_ETF_MIN_CHANGE_PCT",
        cfg.swing_sector_etf_min_change_pct,
    )
    cfg.swing_global_sector_positive_bonus_max = _env_float(
        "TRADING_ENGINE_SWING_GLOBAL_SECTOR_POSITIVE_BONUS_MAX",
        cfg.swing_global_sector_positive_bonus_max,
    )
    cfg.swing_global_sector_negative_penalty_max = _env_float(
        "TRADING_ENGINE_SWING_GLOBAL_SECTOR_NEGATIVE_PENALTY_MAX",
        cfg.swing_global_sector_negative_penalty_max,
    )
    cfg.swing_global_market_negative_penalty_max = _env_float(
        "TRADING_ENGINE_SWING_GLOBAL_MARKET_NEGATIVE_PENALTY_MAX",
        cfg.swing_global_market_negative_penalty_max,
    )
    cfg.swing_chart_review_enabled = _env_bool(
        "TRADING_ENGINE_SWING_CHART_REVIEW_ENABLED",
        cfg.swing_chart_review_enabled,
    )
    cfg.swing_chart_review_top_n = _env_int(
        "TRADING_ENGINE_SWING_CHART_REVIEW_TOP_N",
        cfg.swing_chart_review_top_n,
    )
    cfg.swing_chart_review_paid_min_candidates = _env_int(
        "TRADING_ENGINE_SWING_CHART_REVIEW_PAID_MIN_CANDIDATES",
        cfg.swing_chart_review_paid_min_candidates,
    )
    cfg.swing_chart_review_model = _env_text(
        "TRADING_ENGINE_SWING_CHART_REVIEW_MODEL",
        cfg.swing_chart_review_model,
    )
    cfg.swing_chart_review_reasoning_effort = _env_text(
        "TRADING_ENGINE_SWING_CHART_REVIEW_REASONING_EFFORT",
        cfg.swing_chart_review_reasoning_effort,
    )
    cfg.swing_sl_requires_trend_break = _env_bool(
        "TRADING_ENGINE_SWING_SL_REQUIRES_TREND_BREAK",
        cfg.swing_sl_requires_trend_break,
    )
    cfg.swing_trend_ma_window = _env_int(
        "TRADING_ENGINE_SWING_TREND_MA_WINDOW",
        cfg.swing_trend_ma_window,
    )
    cfg.swing_trend_lookback_bars = _env_int(
        "TRADING_ENGINE_SWING_TREND_LOOKBACK_BARS",
        cfg.swing_trend_lookback_bars,
    )
    cfg.swing_trend_break_buffer_pct = _env_float(
        "TRADING_ENGINE_SWING_TREND_BREAK_BUFFER_PCT",
        cfg.swing_trend_break_buffer_pct,
    )


def _apply_regime_and_news_overrides(cfg: TradeEngineConfig) -> None:
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
    cfg.use_global_market_leadership = _env_bool(
        "TRADING_ENGINE_USE_GLOBAL_MARKET_LEADERSHIP",
        cfg.use_global_market_leadership,
    )
    cfg.global_market_signal_exchanges = _env_csv_tuple(
        "TRADING_ENGINE_GLOBAL_MARKET_SIGNAL_EXCHANGES",
        cfg.global_market_signal_exchanges,
    )
    cfg.global_market_signal_nday = _env_text(
        "TRADING_ENGINE_GLOBAL_MARKET_SIGNAL_NDAY",
        cfg.global_market_signal_nday,
    )
    cfg.global_market_signal_vol_rang = _env_text(
        "TRADING_ENGINE_GLOBAL_MARKET_SIGNAL_VOL_RANG",
        cfg.global_market_signal_vol_rang,
    )
    cfg.global_market_signal_breakout_mode = _env_text(
        "TRADING_ENGINE_GLOBAL_MARKET_SIGNAL_BREAKOUT_MODE",
        cfg.global_market_signal_breakout_mode,
    )
    cfg.global_market_signal_min_price = _env_float(
        "TRADING_ENGINE_GLOBAL_MARKET_SIGNAL_MIN_PRICE",
        cfg.global_market_signal_min_price,
    )
    cfg.global_market_signal_min_volume = _env_int(
        "TRADING_ENGINE_GLOBAL_MARKET_SIGNAL_MIN_VOLUME",
        cfg.global_market_signal_min_volume,
    )
    cfg.global_market_signal_max_abs_change_pct = _env_float(
        "TRADING_ENGINE_GLOBAL_MARKET_SIGNAL_MAX_ABS_CHANGE_PCT",
        cfg.global_market_signal_max_abs_change_pct,
    )
    cfg.global_market_signal_require_tradable = _env_bool(
        "TRADING_ENGINE_GLOBAL_MARKET_SIGNAL_REQUIRE_TRADABLE",
        cfg.global_market_signal_require_tradable,
    )


def _apply_master_path_overrides(cfg: TradeEngineConfig) -> None:
    cfg.industry_idx_master_path = _env_text(
        "TRADING_ENGINE_INDUSTRY_IDX_MASTER_PATH",
        cfg.industry_idx_master_path,
    )
    cfg.industry_kospi_master_path = _env_text(
        "TRADING_ENGINE_INDUSTRY_KOSPI_MASTER_PATH",
        cfg.industry_kospi_master_path,
    )
    cfg.industry_kosdaq_master_path = _env_text(
        "TRADING_ENGINE_INDUSTRY_KOSDAQ_MASTER_PATH",
        cfg.industry_kosdaq_master_path,
    )
    cfg.news_sector_queries_path = _env_text(
        "TRADING_ENGINE_NEWS_SECTOR_QUERIES_PATH",
        cfg.news_sector_queries_path,
    )


def _env_text(name: str, default: str) -> str:
    raw = os.getenv(name)
    if raw is None:
        return default
    text = str(raw).strip()
    return text or default


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


def _env_valid_hhmm(name: str, default: str) -> str:
    raw = os.getenv(name)
    if raw is None:
        return default
    text = str(raw).strip()
    if not text:
        return default
    try:
        parse_hhmm(text)
    except (TypeError, ValueError):
        return default
    return text


def _env_csv_tuple(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.getenv(name)
    if raw is None:
        return default

    values = tuple(
        part.strip().upper()
        for part in str(raw).split(",")
        if str(part).strip()
    )
    return values or default


def _env_entry_windows(
    name: str,
    default: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    raw = os.getenv(name)
    if raw is None:
        return default

    text = str(raw).strip()
    if not text:
        return default

    windows: list[tuple[str, str]] = []
    try:
        for chunk in text.split(","):
            normalized = str(chunk).strip()
            if not normalized:
                return default
            start, end = normalized.split("-", 1)
            parse_hhmm(start)
            parse_hhmm(end)
            windows.append((start.strip(), end.strip()))
    except (TypeError, ValueError):
        return default

    return windows or default
