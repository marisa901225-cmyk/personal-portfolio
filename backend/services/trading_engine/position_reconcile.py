from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from datetime import datetime

from .config import TradeEngineConfig
from .interfaces import TradingAPI
from .notification_text import (
    format_state_sync_add_message,
    format_state_sync_drop_message,
    format_state_sync_update_message,
    format_unknown_broker_position_message,
)
from .state import PositionState, TradeState
from .types import BrokerPosition
from .utils import parse_numeric


def reconcile_state_with_broker_positions(
    api: TradingAPI,
    state: TradeState,
    *,
    trade_date: str,
    journal: Callable[..., None],
    notify_text: Callable[[str], None],
    config: TradeEngineConfig | None = None,
    now: datetime | None = None,
    logger: logging.Logger | None = None,
) -> None:
    cfg = config or TradeEngineConfig()
    sync_now = now or datetime.now()
    try:
        broker_positions = api.positions() or []
    except Exception as exc:
        if logger is not None:
            logger.warning("positions reconcile skipped: failed to load broker positions: %s", exc)
        return

    broker_position_map: dict[str, BrokerPosition] = {}
    for item in broker_positions:
        code = str(item.get("code") or item.get("pdno") or "").strip()
        qty = int(parse_numeric(item.get("qty") or item.get("hldg_qty")) or 0)
        if code and qty > 0:
            avg_price = parse_numeric(item.get("avg_price") or item.get("pchs_avg_pric"))
            current_price = parse_numeric(item.get("current_price") or item.get("prpr"))
            broker_position_map[code] = {
                "qty": qty,
                "avg_price": float(avg_price) if avg_price is not None and avg_price > 0 else None,
                "current_price": float(current_price) if current_price is not None and current_price > 0 else None,
            }

    broker_codes = set(broker_position_map)
    position_type_hints = load_position_type_hints(
        output_dir=cfg.output_dir,
        trade_date=trade_date,
        config=cfg,
    )

    stale_codes = [code for code in state.open_positions if code not in broker_codes]
    for code in stale_codes:
        pos = state.open_positions.pop(code, None)
        if not pos:
            continue
        drop_meta = collect_drop_meta(
            api,
            code=code,
        )
        pending_exit = state.pending_exit_orders.pop(code, None)
        if isinstance(pending_exit, dict):
            drop_meta["exit_reason"] = str(pending_exit.get("reason") or "").strip() or None
            drop_meta["exit_order_id"] = str(pending_exit.get("order_id") or "").strip() or None
        if logger is not None:
            logger.warning(
                "state reconcile dropped stale position code=%s type=%s qty=%s broker_qty=0 last_price=%s",
                code,
                pos.type,
                pos.qty,
                drop_meta["last_quote_price"],
            )
        journal(
            "STATE_RECONCILE_DROP",
            asof_date=trade_date,
            code=code,
            qty=pos.qty,
            reason="BROKER_POSITION_MISSING",
            strategy_type=pos.type,
            last_quote_price=drop_meta["last_quote_price"],
            exit_reason=drop_meta.get("exit_reason"),
            exit_order_id=drop_meta.get("exit_order_id"),
        )
        notify_text(format_drop_notification(code=code, position=pos, drop_meta=drop_meta, config=config))

    missing_codes = [code for code in broker_codes if code not in state.open_positions]
    for code in missing_codes:
        strategy_type = state.pending_entry_orders.get(code) or position_type_hints.get(code)
        if strategy_type not in {"S", "T", "P"}:
            record_unknown_broker_position(
                state=state,
                code=code,
                qty=int(broker_position_map[code]["qty"]),
                trade_date=trade_date,
                journal=journal,
                notify_text=notify_text,
            )
            if logger is not None:
                logger.warning("state reconcile skipped unknown broker-only position code=%s", code)
            continue

        broker_snapshot = broker_position_map[code]
        broker_qty = int(broker_snapshot["qty"])
        resolved_price = broker_snapshot.get("avg_price") or broker_snapshot.get("current_price")
        if resolved_price is None or resolved_price <= 0:
            try:
                quote = api.quote(code) or {}
            except Exception:
                quote = {}
            resolved_price = parse_numeric(quote.get("price"))
        if resolved_price is None or resolved_price <= 0:
            if logger is not None:
                logger.warning("state reconcile failed to price broker-only position code=%s", code)
            continue

        state.open_positions[code] = PositionState(
            type=strategy_type,
            entry_time=sync_now.isoformat(timespec="seconds"),
            entry_price=float(resolved_price),
            qty=broker_qty,
            highest_price=float(resolved_price),
            entry_date=trade_date,
            locked_profit_pct=None,
            bars_held=0,
        )
        if strategy_type == "S":
            state.swing_entries_today += 1
            state.swing_entries_week += 1
        elif strategy_type == "T":
            state.day_entries_today += 1
        state.blacklist_today.add(code)
        if logger is not None:
            logger.warning(
                "state reconcile added broker-only position code=%s type=%s qty=%s avg=%.4f",
                code,
                strategy_type,
                broker_qty,
                float(resolved_price),
            )
        journal(
            "STATE_RECONCILE_ADD",
            asof_date=trade_date,
            code=code,
            qty=broker_qty,
            avg_price=float(resolved_price),
            reason="BROKER_POSITION_FOUND_DURING_POLLING_SYNC",
            strategy_type=strategy_type,
        )
        notify_text(
            format_state_sync_add_message(
                code=code,
                strategy=strategy_type,
                qty=broker_qty,
                avg_price=float(resolved_price),
            )
        )
        state.pending_entry_orders.pop(code, None)
        state.pending_exit_orders.pop(code, None)
        state.unknown_broker_positions.pop(code, None)

    for code, pos in state.open_positions.items():
        broker_snapshot = broker_position_map.get(code)
        if broker_snapshot is None:
            continue

        state.pending_entry_orders.pop(code, None)
        changed, old_qty, old_avg, reason = sync_position_from_broker_snapshot(
            position=pos,
            broker_snapshot=broker_snapshot,
        )
        if not changed:
            continue

        if logger is not None:
            logger.warning(
                "state reconcile updated position code=%s qty=%s->%s avg=%.4f->%.4f",
                code,
                old_qty,
                pos.qty,
                old_avg,
                pos.entry_price,
            )
        journal(
            "STATE_RECONCILE_UPDATE",
            asof_date=trade_date,
            code=code,
            old_qty=old_qty,
            new_qty=pos.qty,
            old_avg_price=old_avg,
            new_avg_price=pos.entry_price,
            reason=reason,
            strategy_type=pos.type,
        )
        notify_text(
            format_state_sync_update_message(
                code=code,
                old_qty=old_qty,
                new_qty=pos.qty,
                old_avg_price=old_avg,
                new_avg_price=pos.entry_price,
            )
        )


def collect_drop_meta(
    api: TradingAPI,
    *,
    code: str,
) -> dict[str, float | str | None]:
    try:
        quote = api.quote(code) or {}
    except Exception:
        quote = {}

    last_price = parse_numeric(quote.get("price"))
    return {
        "last_quote_price": float(last_price) if last_price is not None and last_price > 0 else None,
        "exit_reason": None,
        "exit_order_id": None,
    }


def format_drop_notification(
    *,
    code: str,
    position: PositionState,
    drop_meta: dict[str, float | str | None],
    config: TradeEngineConfig | None,
) -> str:
    del config
    last_quote_price = drop_meta.get("last_quote_price")
    exit_reason = str(drop_meta.get("exit_reason") or "").strip()
    exit_order_id = str(drop_meta.get("exit_order_id") or "").strip()

    return format_state_sync_drop_message(
        code=code,
        local_qty=position.qty,
        last_price=float(last_quote_price) if last_quote_price is not None else None,
        exit_reason=exit_reason or None,
        exit_order_id=exit_order_id or None,
    )


def load_position_type_hints(
    *,
    output_dir: str,
    trade_date: str,
    config: TradeEngineConfig,
) -> dict[str, str]:
    hints: dict[str, str] = {}

    if config.risk_off_parking_enabled and str(config.risk_off_parking_code).strip():
        hints[str(config.risk_off_parking_code).strip()] = "P"

    journal_path = os.path.join(output_dir, f"trade_journal_{trade_date}.jsonl")
    if not os.path.exists(journal_path):
        return hints

    try:
        with open(journal_path, "r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                apply_position_type_hint(hints, row)
    except OSError:
        return hints

    return hints


def apply_position_type_hint(hints: dict[str, str], row: dict[str, object]) -> None:
    event = str(row.get("event") or "").strip()
    if not event:
        return

    if event in {"ENTRY_FILL", "STATE_RECONCILE_ADD"}:
        code = normalize_hint_code(row.get("code"))
        strategy_type = str(row.get("strategy_type") or "").strip()
        if code and strategy_type in {"S", "T", "P"}:
            hints[code] = strategy_type
        return

    if event == "DAY_CHART_REVIEW":
        for code in split_hint_codes(row.get("approved_codes")):
            hints.setdefault(code, "T")
        selected_code = normalize_hint_code(row.get("selected_code"))
        if selected_code:
            hints[selected_code] = "T"
        return

    if event == "SWING_CHART_REVIEW":
        for code in split_hint_codes(row.get("approved_codes")):
            hints.setdefault(code, "S")
        selected_code = normalize_hint_code(row.get("selected_code"))
        if selected_code:
            hints[selected_code] = "S"


def split_hint_codes(raw: object) -> list[str]:
    if raw is None:
        return []
    text = str(raw).strip()
    if not text:
        return []
    return [code for code in (normalize_hint_code(part) for part in text.split(",")) if code]


def normalize_hint_code(raw: object) -> str:
    text = str(raw or "").strip()
    if not text or text.upper() == "NONE":
        return ""
    return text


def sync_position_from_broker_snapshot(
    *,
    position: PositionState,
    broker_snapshot: BrokerPosition,
) -> tuple[bool, int, float, str]:
    broker_qty = int(broker_snapshot["qty"])
    broker_avg_price = broker_snapshot.get("avg_price")
    changed = False
    old_qty = position.qty
    old_avg = float(position.entry_price)
    reason = "BROKER_POSITION_MISMATCH"

    if broker_qty > 0 and broker_qty != position.qty:
        position.qty = broker_qty
        changed = True
        if broker_qty < old_qty:
            reason = "BROKER_POSITION_QTY_DECREASED"
        elif broker_qty > old_qty:
            reason = "BROKER_POSITION_QTY_INCREASED"

    if broker_avg_price is not None and broker_avg_price > 0 and abs(broker_avg_price - position.entry_price) > 1e-6:
        position.entry_price = float(broker_avg_price)
        changed = True

    return changed, old_qty, old_avg, reason


def record_unknown_broker_position(
    *,
    state: TradeState,
    code: str,
    qty: int,
    trade_date: str,
    journal: Callable[..., None],
    notify_text: Callable[[str], None],
) -> bool:
    if state.unknown_broker_positions.get(code) == trade_date:
        return False

    state.unknown_broker_positions[code] = trade_date
    journal(
        "UNKNOWN_BROKER_POSITION",
        asof_date=trade_date,
        code=code,
        qty=qty,
        reason="BROKER_ONLY_WITHOUT_HINT",
    )
    notify_text(
        format_unknown_broker_position_message(
            code=code,
            qty=qty,
        )
    )
    return True
