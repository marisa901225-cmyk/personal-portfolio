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
    available_cash_krw: float | None = None,
) -> tuple[bool, str]:
    normalized_entry_type = str(entry_type or "").strip().upper()
    if normalized_entry_type not in {"S", "T"}:
        return False, "INVALID_ENTRY_TYPE"
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

    if normalized_entry_type == "S":
        if state.swing_entries_today >= config.max_swing_entries_per_day:
            return False, "MAX_SWING_ENTRIES_DAY"
        if state.swing_entries_week >= config.max_swing_entries_per_week:
            return False, "MAX_SWING_ENTRIES_WEEK"
        if _count_reserved_positions(state, "S") >= config.max_swing_positions:
            return False, "MAX_SWING_POSITIONS"
    else:
        if state.day_entries_today >= _effective_max_day_entries_per_day(
            state,
            config,
            available_cash_krw=available_cash_krw,
        ):
            return False, "MAX_DAY_ENTRIES_DAY"
        if _count_reserved_positions(state, "T") >= _effective_max_day_positions(
            state,
            config,
            available_cash_krw=available_cash_krw,
        ):
            return False, "MAX_DAY_POSITIONS"
        if _should_block_day_afternoon_entry(state=state, now=now, cfg=config):
            return False, "DAY_AFTERNOON_LOSS_LIMIT"

    if _count_total_reserved_slots(state) >= config.max_total_positions:
        return False, "MAX_TOTAL_POSITIONS"

    if not _is_entry_window_open(
        normalized_entry_type,
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
    day_lock_intraday_trend_broken: bool | None = None,
    day_stop_loss_pct_override: float | None = None,
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
    if position.type == "T" and locked_profit_pct is not None and pnl_pct < locked_profit_pct:
        if bool(getattr(config, "day_lock_requires_intraday_trend_break", False)) and not bool(
            day_lock_intraday_trend_broken
        ):
            return False, "", pnl_pct
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

    day_stop_loss_pct = float(config.day_stop_loss_pct)
    if day_stop_loss_pct_override is not None:
        day_stop_loss_pct = min(day_stop_loss_pct, float(day_stop_loss_pct_override))
    if pnl_pct <= day_stop_loss_pct:
        return True, "SL", pnl_pct
    if pnl_pct >= config.day_take_profit_pct:
        return True, "TP", pnl_pct
    force_h, force_m = parse_hhmm(config.day_force_exit_at)
    if (now.hour, now.minute) >= (force_h, force_m):
        return True, "FORCE", pnl_pct
    return False, "", pnl_pct


def _effective_max_day_entries_per_day(
    state: TradeState,
    cfg: TradeEngineConfig,
    *,
    available_cash_krw: float | None = None,
) -> int:
    base_limit = max(0, int(cfg.max_day_entries_per_day))
    if not bool(getattr(cfg, "day_conditional_extra_entries_enabled", True)):
        return base_limit

    extra_entries = max(0, int(getattr(cfg, "day_conditional_extra_entries", 0)))
    if extra_entries <= 0:
        return base_limit

    if not _conditional_extra_performance_allows(state=state, cfg=cfg):
        return base_limit

    return base_limit + _conditional_extra_entries_supported_by_budget(
        state=state,
        cfg=cfg,
        extra_entries=extra_entries,
        available_cash_krw=available_cash_krw,
    )


def _conditional_extra_entries_supported_by_budget(
    *,
    state: TradeState,
    cfg: TradeEngineConfig,
    extra_entries: int,
    available_cash_krw: float | None = None,
) -> int:
    extra_slot_floor = _day_extra_slot_budget_floor(cfg)
    if extra_slot_floor <= 0:
        return extra_entries

    if available_cash_krw is not None:
        cash_available = max(0.0, float(available_cash_krw))
        if cash_available < extra_slot_floor:
            return 0
        return max(0, min(extra_entries, int(cash_available // extra_slot_floor)))

    unused_swing_budget = _unused_swing_budget_for_day(state=state, cfg=cfg)
    if unused_swing_budget <= 0:
        return 0

    total_day_budget = max(0.0, float(cfg.initial_capital) * float(cfg.day_cash_ratio)) + unused_swing_budget
    if unused_swing_budget < extra_slot_floor:
        return 0

    affordable_slots = max(1, int(total_day_budget // extra_slot_floor))
    return max(0, min(1, extra_entries, affordable_slots - 1))


def _effective_max_day_positions(
    state: TradeState,
    cfg: TradeEngineConfig,
    *,
    available_cash_krw: float | None = None,
) -> int:
    configured_limit = max(0, int(getattr(cfg, "max_day_positions", 0) or 0))
    if configured_limit <= 1:
        return configured_limit
    if not bool(getattr(cfg, "day_conditional_extra_entries_enabled", True)):
        return 1
    if not _conditional_extra_performance_allows(state=state, cfg=cfg):
        return 1
    budget_supported_slots = 1 + _conditional_extra_entries_supported_by_budget(
        state=state,
        cfg=cfg,
        extra_entries=max(0, int(getattr(cfg, "day_conditional_extra_entries", 0) or 0)),
        available_cash_krw=available_cash_krw,
    )
    return max(1, min(configured_limit, budget_supported_slots))


def _conditional_extra_performance_allows(*, state: TradeState, cfg: TradeEngineConfig) -> bool:
    wins = max(0, int(getattr(state, "day_wins_today", 0)))
    losses = max(0, int(getattr(state, "day_losses_today", 0)))
    closed_trades = wins + losses
    min_closed_trades = max(0, int(getattr(cfg, "day_conditional_extra_min_closed_trades", 0)))
    if closed_trades < min_closed_trades:
        return False

    win_rate = wins / closed_trades if closed_trades else 0.0
    min_win_rate = float(getattr(cfg, "day_conditional_extra_min_win_rate", 0.0))
    if win_rate < min_win_rate:
        return False

    min_realized_pnl = float(getattr(cfg, "day_conditional_extra_min_realized_pnl", 0.0))
    if float(state.realized_pnl_today) < min_realized_pnl:
        return False

    max_losses = max(0, int(getattr(cfg, "day_conditional_extra_max_consecutive_losses", 0)))
    return int(state.consecutive_losses_today) <= max_losses


def _unused_swing_budget_for_day(*, state: TradeState, cfg: TradeEngineConfig) -> float:
    if not bool(getattr(cfg, "day_reuse_unused_swing_cash_enabled", True)):
        return 0.0

    profit_buffer = max(0.0, float(getattr(state, "realized_pnl_total", 0.0) or 0.0))
    swing_budget_cap = max(
        0.0,
        float(cfg.initial_capital) * float(cfg.swing_cash_ratio) + profit_buffer,
    )
    if swing_budget_cap <= 0:
        return 0.0

    deployed_swing_cost = 0.0
    for position in state.open_positions.values():
        if getattr(position, "type", "") != "S":
            continue
        qty = max(0, int(getattr(position, "qty", 0) or 0))
        entry_price = max(0.0, float(getattr(position, "entry_price", 0.0) or 0.0))
        if qty <= 0 or entry_price <= 0:
            continue
        deployed_swing_cost += float(qty) * float(entry_price)

    if deployed_swing_cost <= 0:
        return 0.0

    unused_swing_budget = max(0.0, swing_budget_cap - deployed_swing_cost)
    return unused_swing_budget


def _day_extra_slot_budget_floor(cfg: TradeEngineConfig) -> float:
    base_day_budget = max(0.0, float(cfg.initial_capital) * float(cfg.day_cash_ratio))
    min_order_amount = max(0.0, float(getattr(cfg, "day_conditional_extra_min_order_amount_krw", 0) or 0))
    return max(base_day_budget, min_order_amount)


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


def _count_reserved_positions(state: TradeState, position_type: str) -> int:
    reserved_codes = {
        code
        for code, pos in state.open_positions.items()
        if pos.type == position_type
    }
    reserved_codes.update(
        code
        for code, pending_type in state.pending_entry_orders.items()
        if pending_type == position_type and code not in state.open_positions
    )
    return len(reserved_codes)


def _count_total_reserved_slots(state: TradeState) -> int:
    return len(set(state.open_positions) | set(state.pending_entry_orders))
