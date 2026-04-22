from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from datetime import datetime
from typing import Any

from .config import TradeEngineConfig
from .interfaces import TradingAPI
from .notification_text import (
    format_state_sync_add_message,
    format_state_sync_drop_message,
    format_state_sync_update_message,
)
from .state import PositionState, TradeState
from .utils import compute_sma, parse_numeric


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

    broker_position_map: dict[str, dict[str, Any]] = {}
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
    position_type_hints = _load_position_type_hints(
        output_dir=cfg.output_dir,
        trade_date=trade_date,
        config=cfg,
    )

    stale_codes = [code for code in state.open_positions if code not in broker_codes]
    for code in stale_codes:
        pos = state.open_positions.pop(code, None)
        if not pos:
            continue
        drop_meta = _collect_drop_meta(
            api,
            code=code,
        )
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
        )
        notify_text(_format_drop_notification(code=code, position=pos, drop_meta=drop_meta, config=config))

    missing_codes = [code for code in broker_codes if code not in state.open_positions]
    for code in missing_codes:
        strategy_type = position_type_hints.get(code)
        if strategy_type not in {"S", "T", "P"}:
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

    for code, pos in state.open_positions.items():
        broker_snapshot = broker_position_map.get(code)
        if broker_snapshot is None:
            continue

        broker_qty = int(broker_snapshot["qty"])
        broker_avg_price = broker_snapshot.get("avg_price")
        changed = False
        old_qty = pos.qty
        old_avg = float(pos.entry_price)

        if broker_qty > 0 and broker_qty != pos.qty:
            pos.qty = broker_qty
            changed = True

        if broker_avg_price is not None and broker_avg_price > 0 and abs(broker_avg_price - pos.entry_price) > 1e-6:
            pos.entry_price = float(broker_avg_price)
            changed = True

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
            reason="BROKER_POSITION_MISMATCH",
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


def _load_position_type_hints(
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
                _apply_position_type_hint(hints, row)
    except OSError:
        return hints

    return hints


def _apply_position_type_hint(hints: dict[str, str], row: dict[str, Any]) -> None:
    event = str(row.get("event") or "").strip()
    if not event:
        return

    if event in {"ENTRY_FILL", "STATE_RECONCILE_ADD"}:
        code = _normalize_hint_code(row.get("code"))
        strategy_type = str(row.get("strategy_type") or "").strip()
        if code and strategy_type in {"S", "T", "P"}:
            hints[code] = strategy_type
        return

    if event == "DAY_CHART_REVIEW":
        for code in _split_hint_codes(row.get("approved_codes")):
            hints.setdefault(code, "T")
        selected_code = _normalize_hint_code(row.get("selected_code"))
        if selected_code:
            hints[selected_code] = "T"
        return

    if event == "SWING_CHART_REVIEW":
        for code in _split_hint_codes(row.get("approved_codes")):
            hints.setdefault(code, "S")
        selected_code = _normalize_hint_code(row.get("selected_code"))
        if selected_code:
            hints[selected_code] = "S"


def _split_hint_codes(raw: Any) -> list[str]:
    if raw is None:
        return []
    text = str(raw).strip()
    if not text:
        return []
    return [code for code in (_normalize_hint_code(part) for part in text.split(",")) if code]


def _normalize_hint_code(raw: Any) -> str:
    text = str(raw or "").strip()
    if not text or text.upper() == "NONE":
        return ""
    return text


def _collect_drop_meta(
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
    }


def _format_drop_notification(
    *,
    code: str,
    position: PositionState,
    drop_meta: dict[str, float | str | None],
    config: TradeEngineConfig | None,
) -> str:
    last_quote_price = drop_meta.get("last_quote_price")

    return format_state_sync_drop_message(
        code=code,
        local_qty=position.qty,
        last_price=float(last_quote_price) if last_quote_price is not None else None,
    )


def is_swing_trend_broken(
    api: TradingAPI,
    config: TradeEngineConfig,
    *,
    code: str,
    quote_price: float,
    now: datetime,
    logger: logging.Logger | None = None,
) -> bool:
    ma_window = max(2, int(config.swing_trend_ma_window))
    lookback = max(ma_window + 5, int(config.swing_trend_lookback_bars))
    asof = now.strftime("%Y%m%d")
    try:
        bars = api.daily_bars(code, asof, lookback)
    except Exception:
        if logger is not None:
            logger.debug("trend check daily_bars failed code=%s", code, exc_info=True)
        return False

    if bars is None or bars.empty or "close" not in bars.columns:
        return False

    close_s = bars["close"]
    if len(close_s) < ma_window:
        return False

    ma_s = compute_sma(close_s, ma_window)
    ma_value = parse_numeric(ma_s.iloc[-1]) if len(ma_s) else None
    if ma_value is None or ma_value <= 0:
        return False

    buffer_pct = max(0.0, float(config.swing_trend_break_buffer_pct))
    threshold = ma_value * (1.0 - buffer_pct)
    return quote_price < threshold


def lock_profitable_existing_position(
    api: TradingAPI,
    state: TradeState,
    *,
    trade_date: str,
    code: str,
    quotes: dict[str, Any],
    candidate_type: str,
    now: datetime,
    logger: logging.Logger | None = None,
) -> tuple[float | None, PositionState | None]:
    normalized_code = str(code).strip()
    if not normalized_code:
        return None, None

    local_position = state.open_positions.get(normalized_code)
    if local_position and local_position.qty > 0 and local_position.entry_price > 0:
        quote = quotes.get(normalized_code)
        price = parse_numeric((quote or {}).get("price"))
        if price is None:
            try:
                price = parse_numeric(api.quote(normalized_code).get("price"))
            except Exception:
                price = None
        if price is not None and price > 0:
            pnl_ratio = (price / local_position.entry_price) - 1.0
            if pnl_ratio > 0:
                local_position.highest_price = float(max(local_position.highest_price or 0.0, price))
                if _should_promote_locked_profit(
                    position_type=local_position.type,
                    candidate_type=candidate_type,
                ):
                    local_position.locked_profit_pct = max(
                        float(local_position.locked_profit_pct or pnl_ratio),
                        pnl_ratio,
                    )
                return pnl_ratio, local_position

    try:
        broker_positions = api.positions() or []
    except Exception as exc:
        if logger is not None:
            logger.debug(
                "positions lookup skipped while checking profitable hold code=%s error=%s",
                normalized_code,
                exc,
            )
        return None, local_position

    for item in broker_positions:
        broker_code = str(item.get("code") or item.get("pdno") or "").strip()
        qty = int(parse_numeric(item.get("qty") or item.get("hldg_qty")) or 0)
        if broker_code != normalized_code or qty <= 0:
            continue

        avg_price = parse_numeric(item.get("avg_price") or item.get("pchs_avg_pric"))
        current_price = parse_numeric(
            item.get("current_price") or item.get("prpr") or item.get("price")
        )
        if avg_price is not None and avg_price > 0 and current_price is not None and current_price > 0:
            pnl_ratio = (current_price / avg_price) - 1.0
            if pnl_ratio > 0:
                position = local_position
                if position is None:
                    position = PositionState(
                        type=candidate_type,
                        entry_time=now.isoformat(timespec="seconds"),
                        entry_price=float(avg_price),
                        qty=qty,
                        highest_price=float(max(avg_price, current_price)),
                        entry_date=trade_date,
                        locked_profit_pct=pnl_ratio if _should_promote_locked_profit(
                            position_type=candidate_type,
                            candidate_type=candidate_type,
                        ) else None,
                        bars_held=0,
                    )
                    state.open_positions[normalized_code] = position
                else:
                    position.highest_price = float(max(position.highest_price or 0.0, current_price))
                    if _should_promote_locked_profit(
                        position_type=position.type,
                        candidate_type=candidate_type,
                    ):
                        position.locked_profit_pct = max(
                            float(position.locked_profit_pct or pnl_ratio),
                            pnl_ratio,
                        )
                return pnl_ratio, position

        pnl_rate = parse_numeric(item.get("pnl_rate") or item.get("evlu_pfls_rt"))
        if pnl_rate is None or pnl_rate <= 0:
            continue

        pnl_ratio = pnl_rate / 100.0
        position = local_position
        if position is None:
            if current_price is None or current_price <= 0:
                quote = quotes.get(normalized_code)
                current_price = parse_numeric((quote or {}).get("price"))
            if (avg_price is None or avg_price <= 0) and current_price is not None and current_price > 0:
                avg_price = current_price / (1.0 + pnl_ratio)
        if position is None and avg_price is not None and avg_price > 0:
            position = PositionState(
                type=candidate_type,
                entry_time=now.isoformat(timespec="seconds"),
                entry_price=float(avg_price),
                qty=qty,
                highest_price=float(max(avg_price, current_price or avg_price)),
                entry_date=trade_date,
                locked_profit_pct=pnl_ratio if _should_promote_locked_profit(
                    position_type=candidate_type,
                    candidate_type=candidate_type,
                ) else None,
                bars_held=0,
            )
            state.open_positions[normalized_code] = position
        elif position is not None:
            if current_price is not None and current_price > 0:
                position.highest_price = float(max(position.highest_price or 0.0, current_price))
            if _should_promote_locked_profit(
                position_type=position.type,
                candidate_type=candidate_type,
            ):
                position.locked_profit_pct = max(
                    float(position.locked_profit_pct or pnl_ratio),
                    pnl_ratio,
                )
        if position is not None:
            return pnl_ratio, position

    return None, local_position


def _should_promote_locked_profit(*, position_type: str, candidate_type: str) -> bool:
    return str(position_type).strip().upper() == "S" or str(candidate_type).strip().upper() == "S"
