from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


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
    last_run_timestamp: str | None = None
    last_bar_date_seen: str | None = None
    last_panic_date: str | None = None
    pass_reasons_today: dict[str, int] = field(default_factory=dict)
    pending_notifications: list[dict[str, Any]] = field(default_factory=list)
    day_stoploss_fail_counts: dict[str, int] = field(default_factory=dict)
    day_stoploss_excluded_codes: set[str] = field(default_factory=set)
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
    payload["day_stoploss_fail_counts"] = {
        code: int(count)
        for code, count in sorted(state.day_stoploss_fail_counts.items())
        if str(code).strip() and int(count) > 0
    }
    payload["day_stoploss_excluded_codes"] = sorted(state.day_stoploss_excluded_codes)
    payload["swing_time_excluded_codes"] = sorted(state.swing_time_excluded_codes)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


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


def _parse_open_positions(raw: dict[str, Any]) -> dict[str, PositionState]:
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


def _parse_day_stoploss_excluded_codes(raw: Any) -> set[str]:
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


def _parse_day_stoploss_fail_counts(raw: Any) -> dict[str, int]:
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
