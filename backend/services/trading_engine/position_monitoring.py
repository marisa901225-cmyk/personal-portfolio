from __future__ import annotations

from datetime import datetime

from .execution import exit_position
from .notification_text import format_exit_message
from .position_helpers import swing_trend_break_meta
from .risk import should_exit_position
from .utils import parse_numeric


def monitor_positions(bot, *, now: datetime, logger) -> None:
    with bot._state_lock:
        for code, pos in list(bot.state.open_positions.items()):
            if code in bot.state.pending_exit_orders:
                continue
            try:
                q = bot.api.quote(code)
            except Exception:
                continue
            price = parse_numeric(q.get("price"))
            if price is None:
                continue

            swing_trend_broken: bool | None = None
            swing_trend_meta: dict[str, object] = {}
            day_lock_retrace_gap_pct_override: float | None = None
            day_lock_intraday_trend_broken: bool | None = None
            day_stop_loss_pct_override: float | None = None
            if pos.type == "S" and bot.config.swing_sl_requires_trend_break:
                pnl_pct = (price / pos.entry_price) - 1.0 if pos.entry_price > 0 else 0.0
                if pnl_pct <= bot.config.swing_stop_loss_pct:
                    swing_trend_meta = swing_trend_break_meta(
                        bot.api,
                        bot.config,
                        code=code,
                        quote_price=price,
                        now=now,
                        logger=logger,
                    )
                    swing_trend_broken = bool(swing_trend_meta.get("trend_broken", False))
            elif pos.type == "T":
                day_lock_retrace_gap_pct_override = bot._resolve_day_lock_retrace_gap_pct(code=code)
                day_stop_loss_pct_override = bot._resolve_day_stop_loss_pct(code=code)
                if (
                    bool(getattr(bot.config, "day_lock_requires_intraday_trend_break", True))
                    and pos.locked_profit_pct is not None
                    and pos.entry_price > 0
                    and (price / pos.entry_price - 1.0) < float(pos.locked_profit_pct)
                ):
                    day_lock_intraday_trend_broken = _is_day_lock_intraday_trend_broken(bot, code=code, logger=logger)

            exit_now, reason, pnl_pct = should_exit_position(
                pos,
                quote_price=price,
                now=now,
                config=bot.config,
                swing_trend_broken=swing_trend_broken,
                day_lock_retrace_gap_pct_override=day_lock_retrace_gap_pct_override,
                day_lock_intraday_trend_broken=day_lock_intraday_trend_broken,
                day_stop_loss_pct_override=day_stop_loss_pct_override,
            )
            if not exit_now:
                if pos.type == "S" and pnl_pct <= bot.config.swing_stop_loss_pct:
                    review_key = bot._day_stop_llm_review_key(code=code, pos=pos)
                    already_reviewed = review_key in bot.state.swing_stop_llm_reviewed_positions
                    if already_reviewed:
                        exit_now = True
                        reason = "SL_RECHECK"
                    else:
                        review = bot._review_swing_stop_decision(
                            code=code,
                            pos=pos,
                            quote_price=price,
                            pnl_pct=pnl_pct,
                            trend_meta=swing_trend_meta,
                            trigger_reason=reason or "SL",
                        )
                        if review is not None and review.decision == "EXIT":
                            exit_now = True
                            reason = "SL_LLM"
                        else:
                            continue
                else:
                    continue
            if (
                exit_now
                and pos.type == "S"
                and reason == "TRAIL"
            ):
                review = bot._review_swing_stop_decision(
                    code=code,
                    pos=pos,
                    quote_price=price,
                    pnl_pct=pnl_pct,
                    trend_meta=swing_trend_meta,
                    trigger_reason="TRAIL",
                )
                if review is not None and review.decision == "HOLD":
                    pos.highest_price = float(price)
                    continue
            if (
                exit_now
                and pos.type == "S"
                and pnl_pct <= bot.config.swing_stop_loss_pct
                and reason in {"SL", "SL_TREND"}
            ):
                review = bot._review_swing_stop_decision(
                    code=code,
                    pos=pos,
                    quote_price=price,
                    pnl_pct=pnl_pct,
                    trend_meta=swing_trend_meta,
                    trigger_reason=reason,
                )
                if review is not None:
                    if review.decision == "HOLD":
                        continue
                    reason = "SL_LLM"
                elif reason == "SL" and bot.config.swing_sl_requires_trend_break:
                    continue
            if bot._should_hold_day_stop_after_llm(
                code=code,
                pos=pos,
                quote_price=price,
                pnl_pct=pnl_pct,
                reason=reason,
                now=now,
            ):
                continue
            if bot._should_carry_day_force_exit(
                code=code,
                pos=pos,
                quote_price=price,
                reason=reason,
            ):
                continue

            result = exit_position(
                bot.api,
                bot.state,
                code=code,
                reason=reason,
                now=now,
                config=bot.config,
                on_order_accepted=lambda order, pos=pos: bot._record_pending_exit_order(
                    order,
                    strategy_type=pos.type,
                ),
            )
            if not result:
                continue

            bot.state.pending_exit_orders.pop(code, None)
            bot._journal(
                "EXIT_FILL",
                asof_date=bot.state.trade_date,
                code=code,
                side="SELL",
                qty=result.qty,
                avg_price=result.avg_price,
                pnl_pct=round(pnl_pct * 100.0, 4),
                reason=reason,
                strategy_type=pos.type,
            )
            bot._notify_text(
                format_exit_message(
                    strategy=pos.type,
                    reason=reason,
                    code=code,
                    qty=result.qty,
                    avg_price=result.avg_price,
                    pnl_pct=pnl_pct * 100,
                )
            )


def _is_day_lock_intraday_trend_broken(bot, *, code: str, logger) -> bool:
    ok, meta = bot._passes_day_intraday_confirmation(code=code)
    if ok:
        return False
    reason = str(meta.get("reason") or "").strip().upper()
    return reason in {"WEAK_INTRADAY_WINDOW", "WEAK_INTRADAY_LAST_BAR", "INTRADAY_RETRACE"}


def record_pending_exit_order(bot, order: dict, *, strategy_type: str) -> None:
    code = str(order.get("code") or "").strip()
    if not code:
        return
    reason = str(order.get("reason") or "").strip().upper()
    order_id = str(order.get("order_id") or "").strip()
    qty = int(parse_numeric(order.get("qty")) or 0)
    with bot._state_lock:
        bot.state.pending_exit_orders[code] = {
            "strategy_type": str(strategy_type or "").strip().upper(),
            "reason": reason,
            "order_id": order_id,
            "qty": qty,
            "order_time": str(order.get("order_time") or "").strip(),
        }
        bot._journal(
            "EXIT_ORDER_ACCEPTED",
            asof_date=bot.state.trade_date,
            code=code,
            side="SELL",
            qty=qty,
            reason=reason,
            order_id=order_id,
            strategy_type=str(strategy_type or "").strip().upper(),
        )


def refresh_pending_exit_orders(bot, *, logger) -> None:
    if not bot.state.pending_exit_orders:
        return

    try:
        open_orders = bot.api.open_orders() or []
    except Exception:
        logger.warning("open_orders refresh failed for pending exit sync", exc_info=True)
        open_orders = []

    open_sell_codes: set[str] = set()
    for order in open_orders:
        code = str(order.get("code") or order.get("pdno") or "").strip()
        side = str(order.get("side") or order.get("sll_buy_dvsn_cd") or "").strip().lower()
        remaining_qty = parse_numeric(order.get("remaining_qty") or order.get("psbl_qty"))
        if code and side in {"sell", "01"} and (remaining_qty is None or remaining_qty > 0):
            open_sell_codes.add(code)

    try:
        broker_positions = bot.api.positions() or []
    except Exception:
        logger.warning("positions refresh failed for pending exit sync", exc_info=True)
        return

    broker_qty_map = {
        str(item.get("code") or item.get("pdno") or "").strip(): int(
            parse_numeric(item.get("qty") or item.get("hldg_qty")) or 0
        )
        for item in broker_positions
    }

    for code in list(bot.state.pending_exit_orders):
        if code in open_sell_codes:
            continue

        pending = bot.state.pending_exit_orders.get(code) or {}
        broker_qty = int(broker_qty_map.get(code, 0))
        local_pos = bot.state.open_positions.get(code)
        local_qty = int(local_pos.qty) if local_pos is not None else 0

        if broker_qty <= 0:
            bot.state.open_positions.pop(code, None)
            bot.state.pending_exit_orders.pop(code, None)
            bot._journal(
                "STATE_RECONCILE_DROP",
                asof_date=bot.state.trade_date,
                code=code,
                qty=local_qty,
                reason=str(pending.get("reason") or "PENDING_EXIT_FILLED"),
                strategy_type=str(pending.get("strategy_type") or ""),
            )
            continue

        if local_pos is not None and broker_qty < local_qty:
            local_pos.qty = broker_qty
            bot._journal(
                "STATE_RECONCILE_UPDATE",
                asof_date=bot.state.trade_date,
                code=code,
                old_qty=local_qty,
                new_qty=broker_qty,
                old_avg_price=local_pos.entry_price,
                new_avg_price=local_pos.entry_price,
                reason="BROKER_POSITION_QTY_DECREASED",
                strategy_type=local_pos.type,
            )
            continue

        stale_date = str(pending.get("last_stale_notice_date") or "").strip()
        if stale_date == bot.state.trade_date:
            continue
        pending["last_stale_notice_date"] = bot.state.trade_date
        bot.state.pending_exit_orders[code] = pending
        bot._journal(
            "EXIT_PENDING_STALE",
            asof_date=bot.state.trade_date,
            code=code,
            qty=broker_qty,
            reason=str(pending.get("reason") or "UNKNOWN"),
            strategy_type=str(pending.get("strategy_type") or ""),
        )


def force_exit_day_positions(bot, *, now: datetime) -> None:
    force_h, force_m = map(int, bot.config.day_force_exit_at.split(":"))
    if (now.hour, now.minute) < (force_h, force_m):
        return

    with bot._state_lock:
        for code, pos in list(bot.state.open_positions.items()):
            if pos.type != "T":
                continue
            if code in bot.state.pending_exit_orders:
                continue
            try:
                q = bot.api.quote(code)
            except Exception:
                q = {}
            price = parse_numeric(q.get("price"))
            if price is not None and bot._should_carry_day_force_exit(
                code=code,
                pos=pos,
                quote_price=price,
                reason="FORCE",
            ):
                continue
            result = exit_position(
                bot.api,
                bot.state,
                code=code,
                reason="FORCE",
                now=now,
                config=bot.config,
                on_order_accepted=lambda order, pos=pos: bot._record_pending_exit_order(
                    order,
                    strategy_type=pos.type,
                ),
            )
            if not result:
                continue
            bot.state.pending_exit_orders.pop(code, None)
            bot._journal(
                "FORCE_EXIT",
                asof_date=bot.state.trade_date,
                code=code,
                side="SELL",
                qty=result.qty,
                avg_price=result.avg_price,
                reason="FORCE",
                strategy_type="T",
            )


__all__ = [
    "force_exit_day_positions",
    "monitor_positions",
    "record_pending_exit_order",
    "refresh_pending_exit_orders",
]
