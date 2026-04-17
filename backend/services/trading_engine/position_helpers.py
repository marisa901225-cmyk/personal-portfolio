from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from .config import TradeEngineConfig
from .interfaces import TradingAPI
from .state import PositionState, TradeState
from .utils import compute_sma, parse_numeric


def reconcile_state_with_broker_positions(
    api: TradingAPI,
    state: TradeState,
    *,
    trade_date: str,
    journal: Callable[..., None],
    notify_text: Callable[[str], None],
    logger: logging.Logger | None = None,
) -> None:
    try:
        broker_positions = api.positions() or []
    except Exception as exc:
        if logger is not None:
            logger.warning("positions reconcile skipped: failed to load broker positions: %s", exc)
        return

    broker_codes: set[str] = set()
    for item in broker_positions:
        code = str(item.get("code") or item.get("pdno") or "").strip()
        qty = int(parse_numeric(item.get("qty") or item.get("hldg_qty")) or 0)
        if code and qty > 0:
            broker_codes.add(code)

    stale_codes = [code for code in state.open_positions if code not in broker_codes]
    for code in stale_codes:
        pos = state.open_positions.pop(code, None)
        if not pos:
            continue
        if logger is not None:
            logger.warning(
                "state reconcile dropped stale position code=%s type=%s qty=%s",
                code,
                pos.type,
                pos.qty,
            )
        journal(
            "STATE_RECONCILE_DROP",
            asof_date=trade_date,
            code=code,
            qty=pos.qty,
            reason="BROKER_POSITION_MISSING",
            strategy_type=pos.type,
        )
        notify_text(f"[STATE_SYNC][DROP] {code} local_qty={pos.qty} broker_qty=0")


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
