from __future__ import annotations

from datetime import datetime

from .config import TradeEngineConfig
from .state import PositionState, TradeState
from .utils import parse_hhmm


def _hhmm_to_minutes(hhmm: str) -> int:
    h, m = parse_hhmm(hhmm)
    return h * 60 + m


def _is_in_window(now: datetime, start: str, end: str) -> bool:
    minute = now.hour * 60 + now.minute
    return _hhmm_to_minutes(start) <= minute <= _hhmm_to_minutes(end)


def can_enter(
    entry_type: str,
    state: TradeState,
    *,
    regime: str,
    candidates_count: int,
    now: datetime,
    config: TradeEngineConfig,
    is_trading_day_value: bool = True,
) -> tuple[bool, str]:
    if not is_trading_day_value:
        return False, "HOLIDAY"
    if regime == "RISK_OFF":
        return False, "RISK_OFF"
    if candidates_count <= 0:
        return False, "NO_CANDIDATE"

    daily_loss_limit = config.initial_capital * config.daily_max_loss_pct
    if state.realized_pnl_today <= daily_loss_limit:
        return False, "DAILY_MAX_LOSS"
    if state.consecutive_losses_today >= config.max_consecutive_losses:
        return False, "MAX_CONSECUTIVE_LOSSES"

    now_minute = now.hour * 60 + now.minute
    if now_minute >= _hhmm_to_minutes(config.no_new_entry_after):
        return False, "NO_NEW_ENTRY_AFTER"

    if entry_type == "S":
        if state.swing_entries_today >= config.max_swing_entries_per_day:
            return False, "MAX_SWING_ENTRIES_DAY"
        if state.swing_entries_week >= config.max_swing_entries_per_week:
            return False, "MAX_SWING_ENTRIES_WEEK"
        if _count_positions(state, "S") >= config.max_swing_positions:
            return False, "MAX_SWING_POSITIONS"
    else:
        if state.day_entries_today >= config.max_day_entries_per_day:
            return False, "MAX_DAY_ENTRIES_DAY"
        if _count_positions(state, "T") >= config.max_day_positions:
            return False, "MAX_DAY_POSITIONS"
        if _should_block_day_afternoon_entry(state=state, now=now, cfg=config):
            return False, "DAY_AFTERNOON_LOSS_LIMIT"

    if len(state.open_positions) >= config.max_total_positions:
        return False, "MAX_TOTAL_POSITIONS"

    if not _is_entry_window_open(
        entry_type,
        now,
        config,
        day_entries_today=state.day_entries_today,
        day_entry_windows_used_today=state.day_entry_windows_used_today,
    ):
        return False, "ENTRY_WINDOW_CLOSED"

    return True, "OK"


def should_exit_position(
    position: PositionState,
    *,
    quote_price: float,
    now: datetime,
    config: TradeEngineConfig,
    swing_trend_broken: bool | None = None,
    day_lock_retrace_gap_pct_override: float | None = None,
) -> tuple[bool, str, float]:
    if position.entry_price <= 0:
        return False, "", 0.0

    pnl_pct = (quote_price / position.entry_price) - 1.0
    if position.type == "T":
        _update_day_profit_lock(
            position,
            pnl_pct,
            config,
            retrace_gap_pct_override=day_lock_retrace_gap_pct_override,
        )

    locked_profit_pct = float(position.locked_profit_pct) if position.locked_profit_pct is not None else None
    if locked_profit_pct is not None and pnl_pct < locked_profit_pct:
        return True, "LOCK", pnl_pct

    if position.type == "P":
        return False, "", pnl_pct

    if position.type == "S":
        if pnl_pct <= config.swing_stop_loss_pct:
            if not config.swing_sl_requires_trend_break:
                return True, "SL", pnl_pct
            if bool(swing_trend_broken):
                return True, "SL_TREND", pnl_pct

        if config.swing_take_profit_mode in {"fixed", "both"} and pnl_pct >= config.swing_take_profit_pct:
            return True, "TP", pnl_pct

        highest = position.highest_price or position.entry_price
        if quote_price > highest:
            position.highest_price = quote_price
            highest = quote_price

        if config.swing_take_profit_mode in {"trailing", "both"} and pnl_pct >= config.swing_trail_start:
            drawdown_pct = (quote_price / highest) - 1.0
            if drawdown_pct <= config.swing_trail_gap:
                return True, "TRAIL", pnl_pct

        if position.bars_held >= config.swing_max_hold_bars:
            return True, "TIME", pnl_pct

        return False, "", pnl_pct

    force_h, force_m = parse_hhmm(config.day_force_exit_at)
    if (now.hour, now.minute) >= (force_h, force_m):
        return True, "FORCE", pnl_pct
    if pnl_pct <= config.day_stop_loss_pct:
        return True, "SL", pnl_pct
    if pnl_pct >= config.day_take_profit_pct:
        return True, "TP", pnl_pct
    return False, "", pnl_pct


def _update_day_profit_lock(
    position: PositionState,
    pnl_pct: float,
    config: TradeEngineConfig,
    *,
    retrace_gap_pct_override: float | None = None,
) -> None:
    trigger_pct = float(config.day_lock_profit_trigger_pct)
    if trigger_pct <= 0 or pnl_pct < trigger_pct:
        return

    base_floor_pct = max(0.0, float(config.day_lock_profit_floor_pct))
    if retrace_gap_pct_override is None:
        retrace_gap_pct = max(0.0, float(config.day_lock_retrace_gap_pct))
    else:
        retrace_gap_pct = max(0.0, float(retrace_gap_pct_override))
    dynamic_floor_pct = max(base_floor_pct, pnl_pct - retrace_gap_pct)
    if dynamic_floor_pct <= 0:
        return

    current_floor_pct = float(position.locked_profit_pct) if position.locked_profit_pct is not None else 0.0
    position.locked_profit_pct = max(current_floor_pct, dynamic_floor_pct)


def _is_entry_window_open(
    entry_type: str,
    now: datetime,
    cfg: TradeEngineConfig,
    *,
    day_entries_today: int = 0,
    day_entry_windows_used_today: set[int] | None = None,
) -> bool:
    windows = cfg.entry_windows
    if not windows:
        return False

    if entry_type == "T":
        current_window_index = current_entry_window_index(now, cfg)
        if current_window_index is None:
            return False
        try:
            start_window_index = int(getattr(cfg, "day_entry_window_index", 0))
        except (TypeError, ValueError):
            start_window_index = 0
        if current_window_index < max(0, start_window_index):
            return False
        used_window_indices = day_entry_windows_used_today or set()
        return current_window_index not in used_window_indices

    return any(_is_in_window(now, start, end) for start, end in windows)


def current_entry_window_index(
    now: datetime,
    cfg: TradeEngineConfig,
) -> int | None:
    for index, (start, end) in enumerate(cfg.entry_windows):
        if _is_in_window(now, start, end):
            return index
    return None


def _should_block_day_afternoon_entry(
    *,
    state: TradeState,
    now: datetime,
    cfg: TradeEngineConfig,
) -> bool:
    current_window_index = current_entry_window_index(now, cfg)
    if current_window_index is None:
        return False

    try:
        afternoon_start_index = int(getattr(cfg, "day_afternoon_entry_start_window_index", 2))
    except (TypeError, ValueError):
        afternoon_start_index = 2
    if current_window_index < max(0, afternoon_start_index):
        return False

    loss_limit_amount = _day_afternoon_loss_limit_amount(cfg)
    if loss_limit_amount is None:
        return False

    return state.realized_pnl_today <= -loss_limit_amount


def _day_afternoon_loss_limit_amount(cfg: TradeEngineConfig) -> float | None:
    try:
        loss_count = int(getattr(cfg, "day_afternoon_loss_limit_loss_count", 2))
    except (TypeError, ValueError):
        loss_count = 2
    if loss_count <= 0:
        return None

    stop_loss_pct = abs(float(cfg.day_stop_loss_pct))
    cash_ratio = max(0.0, float(cfg.day_cash_ratio))
    initial_capital = max(0.0, float(cfg.initial_capital))
    if stop_loss_pct <= 0 or cash_ratio <= 0 or initial_capital <= 0:
        return None

    return initial_capital * cash_ratio * stop_loss_pct * loss_count


def _count_positions(state: TradeState, position_type: str) -> int:
    return sum(1 for pos in state.open_positions.values() if pos.type == position_type)
