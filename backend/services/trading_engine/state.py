from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from tempfile import NamedTemporaryFile

from .types import PendingExitOrder


def _today_yyyymmdd() -> str:
    return datetime.now().strftime("%Y%m%d")


def _week_id(yyyymmdd: str) -> str:
    d = datetime.strptime(yyyymmdd, "%Y%m%d")
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


@dataclass(slots=True)
class PositionState:
    type: str  # S | T | P
    entry_time: str
    entry_price: float
    qty: int
    highest_price: float | None
    entry_date: str
    locked_profit_pct: float | None = None
    bars_held: int = 0


@dataclass(slots=True)
class TradeState:
    trade_date: str
    week_id: str
    swing_entries_today: int = 0
    swing_entries_week: int = 0
    day_entries_today: int = 0
    realized_pnl_today: float = 0.0
    realized_pnl_total: float = 0.0
    consecutive_losses_today: int = 0
    blacklist_today: set[str] = field(default_factory=set)
    open_positions: dict[str, PositionState] = field(default_factory=dict)
    pending_entry_orders: dict[str, str] = field(default_factory=dict)
    pending_exit_orders: dict[str, PendingExitOrder] = field(default_factory=dict)
    last_run_timestamp: str | None = None
    last_bar_date_seen: str | None = None
    last_panic_date: str | None = None
    pass_reasons_today: dict[str, int] = field(default_factory=dict)
    pending_notifications: list[dict[str, object]] = field(default_factory=list)
    day_stoploss_fail_counts: dict[str, int] = field(default_factory=dict)
    day_stoploss_excluded_codes: set[str] = field(default_factory=set)
    day_stoploss_codes_today: set[str] = field(default_factory=set)
    day_stop_llm_reviewed_positions: set[str] = field(default_factory=set)
    day_entry_windows_used_today: set[int] = field(default_factory=set)
    swing_time_excluded_codes: set[str] = field(default_factory=set)


def new_state(trade_date: str | None = None) -> TradeState:
    date = trade_date or _today_yyyymmdd()
    return TradeState(trade_date=date, week_id=_week_id(date))


def load_state(path: str) -> TradeState:
    if not os.path.exists(path):
        return new_state()

    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    st = TradeState(
        trade_date=raw.get("trade_date") or _today_yyyymmdd(),
        week_id=raw.get("week_id") or _week_id(raw.get("trade_date") or _today_yyyymmdd()),
        swing_entries_today=int(raw.get("swing_entries_today", 0)),
        swing_entries_week=int(raw.get("swing_entries_week", 0)),
        day_entries_today=int(raw.get("day_entries_today", 0)),
        realized_pnl_today=float(raw.get("realized_pnl_today", 0.0)),
        realized_pnl_total=float(raw.get("realized_pnl_total", 0.0)),
        consecutive_losses_today=int(raw.get("consecutive_losses_today", 0)),
        blacklist_today=set(raw.get("blacklist_today", [])),
        open_positions=_parse_open_positions(raw.get("open_positions", {})),
        pending_entry_orders=_parse_pending_entry_orders(raw.get("pending_entry_orders", {})),
        pending_exit_orders=_parse_pending_exit_orders(raw.get("pending_exit_orders", {})),
        last_run_timestamp=raw.get("last_run_timestamp"),
        last_bar_date_seen=raw.get("last_bar_date_seen"),
        last_panic_date=raw.get("last_panic_date"),
        pass_reasons_today=dict(raw.get("pass_reasons_today", {})),
        pending_notifications=list(raw.get("pending_notifications", [])),
        day_stoploss_fail_counts=_parse_day_stoploss_fail_counts(
            raw.get("day_stoploss_fail_counts", {})
        ),
        day_stoploss_excluded_codes=_parse_day_stoploss_excluded_codes(
            raw.get("day_stoploss_excluded_codes", [])
        ),
        day_stoploss_codes_today=_parse_day_stoploss_excluded_codes(
            raw.get("day_stoploss_codes_today", [])
        ),
        day_stop_llm_reviewed_positions=_parse_day_stoploss_excluded_codes(
            raw.get("day_stop_llm_reviewed_positions", [])
        ),
        day_entry_windows_used_today=_parse_int_set(
            raw.get("day_entry_windows_used_today", [])
        ),
        swing_time_excluded_codes=_parse_day_stoploss_excluded_codes(
            raw.get("swing_time_excluded_codes", [])
        ),
    )
    return st


def save_state(path: str, state: TradeState) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    payload = asdict(state)
    payload["blacklist_today"] = sorted(state.blacklist_today)
    payload["open_positions"] = {
        code: asdict(pos)
        for code, pos in state.open_positions.items()
    }
    payload["pending_entry_orders"] = {
        code: strategy_type
        for code, strategy_type in sorted(state.pending_entry_orders.items())
        if str(code).strip() and str(strategy_type).strip() in {"S", "T", "P"}
    }
    payload["pending_exit_orders"] = {
        code: dict(order)
        for code, order in sorted(state.pending_exit_orders.items())
        if str(code).strip() and isinstance(order, dict)
    }
    payload["day_stoploss_fail_counts"] = {
        code: int(count)
        for code, count in sorted(state.day_stoploss_fail_counts.items())
        if str(code).strip() and int(count) > 0
    }
    payload["day_stoploss_excluded_codes"] = sorted(state.day_stoploss_excluded_codes)
    payload["day_stoploss_codes_today"] = sorted(state.day_stoploss_codes_today)
    payload["day_stop_llm_reviewed_positions"] = sorted(state.day_stop_llm_reviewed_positions)
    payload["day_entry_windows_used_today"] = sorted(
        int(idx) for idx in state.day_entry_windows_used_today
    )
    payload["swing_time_excluded_codes"] = sorted(state.swing_time_excluded_codes)

    original_mode: int | None = None
    if os.path.exists(path):
        original_mode = os.stat(path).st_mode & 0o777

    with NamedTemporaryFile("w", encoding="utf-8", dir=os.path.dirname(path) or ".", delete=False) as tmp:
        json.dump(payload, tmp, ensure_ascii=False, indent=2)
        tmp.write("\n")
        tmp_path = tmp.name

    if original_mode is not None:
        os.chmod(tmp_path, original_mode)
    os.replace(tmp_path, path)


def rollover_state_for_date(state: TradeState, today: str) -> TradeState:
    if state.trade_date == today:
        return state

    state.trade_date = today
    state.swing_entries_today = 0
    state.day_entries_today = 0
    state.realized_pnl_today = 0.0
    state.consecutive_losses_today = 0
    state.blacklist_today.clear()
    state.pass_reasons_today.clear()
    state.pending_entry_orders.clear()
    state.pending_exit_orders.clear()
    state.day_stoploss_codes_today.clear()
    state.day_stop_llm_reviewed_positions.clear()
    state.day_entry_windows_used_today.clear()
    state.swing_time_excluded_codes.clear()

    new_week_id = _week_id(today)
    if new_week_id != state.week_id:
        state.week_id = new_week_id
        state.swing_entries_week = 0

    return state


def add_pass_reason(state: TradeState, reason: str) -> None:
    state.pass_reasons_today[reason] = int(state.pass_reasons_today.get(reason, 0)) + 1


def record_day_stoploss_failure(
    state: TradeState,
    *,
    code: str,
    exclude_after_losses: int = 3,
) -> int:
    normalized_code = str(code).strip()
    if not normalized_code:
        return 0

    current_count = int(state.day_stoploss_fail_counts.get(normalized_code, 0))
    next_count = current_count + 1
    state.day_stoploss_fail_counts[normalized_code] = next_count

    if next_count >= max(1, int(exclude_after_losses)):
        state.day_stoploss_excluded_codes.add(normalized_code)
    else:
        state.day_stoploss_excluded_codes.discard(normalized_code)

    return next_count


def mark_day_stoploss_excluded(
    state: TradeState,
    *,
    code: str,
) -> None:
    normalized_code = str(code).strip()
    if not normalized_code:
        return

    state.day_stoploss_excluded_codes.add(normalized_code)


def get_day_stoploss_fail_count(state: TradeState, code: str) -> int:
    normalized_code = str(code).strip()
    if not normalized_code:
        return 0
    return int(state.day_stoploss_fail_counts.get(normalized_code, 0))


def get_day_stoploss_excluded_codes(state: TradeState) -> set[str]:
    return {str(code) for code in state.day_stoploss_excluded_codes}


def mark_day_stoploss_today(
    state: TradeState,
    *,
    code: str,
) -> None:
    normalized_code = str(code).strip()
    if not normalized_code:
        return

    state.day_stoploss_codes_today.add(normalized_code)


def get_day_stoploss_codes_today(state: TradeState) -> set[str]:
    return {str(code) for code in state.day_stoploss_codes_today}


def get_day_reentry_blocked_codes(state: TradeState) -> set[str]:
    blocked_codes = get_day_stoploss_excluded_codes(state)
    blocked_codes.update(get_day_stoploss_codes_today(state))
    return blocked_codes


def mark_swing_time_excluded(
    state: TradeState,
    *,
    code: str,
) -> None:
    normalized_code = str(code).strip()
    if not normalized_code:
        return

    state.swing_time_excluded_codes.add(normalized_code)


def get_swing_time_excluded_codes(state: TradeState) -> set[str]:
    return {str(code) for code in state.swing_time_excluded_codes}


def _parse_open_positions(raw: object) -> dict[str, PositionState]:
    if not isinstance(raw, dict):
        return {}

    out: dict[str, PositionState] = {}
    for code, item in (raw or {}).items():
        if not isinstance(item, dict):
            continue
        out[str(code)] = PositionState(
            type=str(item.get("type", "S")),
            entry_time=str(item.get("entry_time", "")),
            entry_price=float(item.get("entry_price", 0.0)),
            qty=int(item.get("qty", 0)),
            highest_price=float(item["highest_price"]) if item.get("highest_price") is not None else None,
            entry_date=str(item.get("entry_date", "")),
            locked_profit_pct=float(item["locked_profit_pct"]) if item.get("locked_profit_pct") is not None else None,
            bars_held=int(item.get("bars_held", 0)),
        )
    return out


def _parse_pending_entry_orders(raw: object) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}

    out: dict[str, str] = {}
    for code, strategy_type in (raw or {}).items():
        normalized_code = str(code or "").strip()
        normalized_type = str(strategy_type or "").strip().upper()
        if not normalized_code or normalized_type not in {"S", "T", "P"}:
            continue
        out[normalized_code] = normalized_type
    return out


def _parse_pending_exit_orders(raw: object) -> dict[str, PendingExitOrder]:
    if not isinstance(raw, dict):
        return {}

    out: dict[str, PendingExitOrder] = {}
    for code, item in raw.items():
        normalized_code = str(code or "").strip()
        if not normalized_code or not isinstance(item, dict):
            continue
        order: PendingExitOrder = {}
        for key in ("strategy_type", "reason", "order_id", "qty", "order_time"):
            value = item.get(key)
            if value is not None:
                order[key] = value
        if order:
            out[normalized_code] = order
    return out


def _parse_day_stoploss_excluded_codes(raw: object) -> set[str]:
    if isinstance(raw, dict):
        items = raw.keys()
    elif isinstance(raw, (list, tuple, set)):
        items = raw
    else:
        items = []

    return {
        str(code).strip()
        for code in items
        if str(code).strip()
    }


def _parse_day_stoploss_fail_counts(raw: object) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}

    out: dict[str, int] = {}
    for code, value in raw.items():
        normalized_code = str(code).strip()
        if not normalized_code:
            continue
        try:
            count = int(value)
        except (TypeError, ValueError):
            continue
        if count > 0:
            out[normalized_code] = count
    return out


def _parse_int_set(raw: object) -> set[int]:
    if isinstance(raw, dict):
        items = raw.keys()
    elif isinstance(raw, (list, tuple, set)):
        items = raw
    else:
        items = []

    out: set[int] = set()
    for value in items:
        try:
            out.add(int(value))
        except (TypeError, ValueError):
            continue
    return out
