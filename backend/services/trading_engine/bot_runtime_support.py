from __future__ import annotations

from datetime import datetime
import logging

import pandas as pd

from .config import TradeEngineConfig
from .run_context import CachedTradingAPI, TradingRunMetrics
from .strategy import Candidates
from .utils import parse_numeric


def entry_sizing_fields(result: object) -> dict[str, object]:
    sizing = getattr(result, "sizing", None) or {}
    if not isinstance(sizing, dict):
        return {}
    return dict(sizing)


def strategy_budget_cash_cap(bot, *, cash_ratio: float, position_type: str | None = None) -> float | None:
    base_cap = max(0.0, float(bot.config.initial_capital) * float(cash_ratio))
    normalized_position_type = str(position_type or "").strip().upper()
    if normalized_position_type == "T":
        base_cap += unused_swing_budget_for_day(bot)
    if not bot.config.use_realized_profit_buffer:
        return base_cap

    profit_buffer = principal_buffer_from_account(bot, logger=logging.getLogger(__name__))
    return max(0.0, base_cap + profit_buffer)


def unused_swing_budget_for_day(bot) -> float:
    if not bool(getattr(bot.config, "day_reuse_unused_swing_cash_enabled", True)):
        return 0.0

    swing_budget_cap = max(0.0, float(bot.config.initial_capital) * float(bot.config.swing_cash_ratio))
    if swing_budget_cap <= 0:
        return 0.0

    deployed_swing_cost = 0.0
    for position in bot.state.open_positions.values():
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
    min_reuse_krw = max(0, int(getattr(bot.config, "day_reuse_unused_swing_cash_min_krw", 100_000)))
    if unused_swing_budget < float(min_reuse_krw):
        return 0.0
    return unused_swing_budget


def principal_buffer_from_account(bot, *, logger: logging.Logger) -> float:
    if bot._principal_buffer_snapshot is not None:
        return bot._principal_buffer_snapshot

    fallback_buffer = max(0.0, float(getattr(bot.state, "realized_pnl_total", 0.0)))
    try:
        cash_available = max(0.0, float(bot.api.cash_available()))
        positions = bot.api.positions() or []
        cost_basis_total = 0.0
        for item in positions:
            qty = parse_numeric(item.get("qty") or item.get("hldg_qty"))
            avg_price = parse_numeric(item.get("avg_price") or item.get("pchs_avg_pric"))
            if qty is None or avg_price is None or qty <= 0 or avg_price <= 0:
                continue
            cost_basis_total += float(qty) * float(avg_price)

        account_basis_total = cash_available + cost_basis_total
        principal_buffer = max(0.0, account_basis_total - float(bot.config.initial_capital))
        bot._principal_buffer_snapshot = max(principal_buffer, fallback_buffer)
    except Exception:
        logger.warning("principal buffer account snapshot failed; using state fallback", exc_info=True)
        bot._principal_buffer_snapshot = fallback_buffer

    return bot._principal_buffer_snapshot


def finalize_realized_pnl(bot, *, logger: logging.Logger) -> float:
    broker_realized_pnl = fetch_account_realized_pnl(bot, logger=logger)
    if broker_realized_pnl is not None:
        bot.state.realized_pnl_today = broker_realized_pnl
    return float(bot.state.realized_pnl_today)


def fetch_account_realized_pnl(bot, *, logger: logging.Logger) -> float | None:
    inquire_realized_pnl = getattr(bot.api, "inquire_realized_pnl", None)
    if not callable(inquire_realized_pnl):
        return None

    try:
        data = inquire_realized_pnl()
    except Exception:
        logger.warning("account realized pnl fetch failed; using state fallback", exc_info=True)
        return None

    if not isinstance(data, dict):
        return None

    total_realized_pnl = extract_realized_pnl(data.get("output2"))
    if total_realized_pnl is not None:
        return total_realized_pnl

    output1 = data.get("output1", [])
    if isinstance(output1, list):
        realized_values = [
            value
            for value in (extract_realized_pnl(row) for row in output1)
            if value is not None
        ]
        if realized_values:
            return float(sum(realized_values))

    logger.warning("account realized pnl not found in broker response; using state fallback")
    return None


def extract_realized_pnl(payload: object) -> float | None:
    row = payload[0] if isinstance(payload, list) and payload else payload
    if not isinstance(row, dict):
        return None
    for key in ("rlzt_pfls", "tot_rlzt_pfls"):
        value = parse_numeric(row.get(key))
        if value is not None:
            return float(value)
    return None


def empty_candidates(asof: str) -> Candidates:
    return Candidates(
        asof=asof,
        popular=pd.DataFrame(),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=[],
    )


def should_defer_swing_scan(config: TradeEngineConfig, *, now: datetime) -> bool:
    if not bool(getattr(config, "defer_swing_scan_in_day_entry_window", False)):
        return False
    from .risk import current_entry_window_index

    current_window_index = current_entry_window_index(now, config)
    if current_window_index is None:
        return False
    try:
        first_day_window_index = int(getattr(config, "day_entry_window_index", 0))
    except (TypeError, ValueError):
        first_day_window_index = 0
    return current_window_index == max(0, first_day_window_index)


def combine_quote_codes(*candidate_sets: Candidates) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for candidate_set in candidate_sets:
        for code in getattr(candidate_set, "quote_codes", []):
            code_str = str(code or "").strip()
            if not code_str or code_str in seen:
                continue
            seen.add(code_str)
            ordered.append(code_str)
    return ordered


def merge_candidate_frames(*candidate_sets: Candidates) -> pd.DataFrame:
    frames = [
        frame
        for item in candidate_sets
        for frame in [getattr(item, "merged", None)]
        if isinstance(frame, pd.DataFrame) and not frame.empty
    ]
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True, sort=False)
    if "code" in combined.columns:
        combined = combined.drop_duplicates(subset=["code"], keep="first")
    return combined.reset_index(drop=True)


def log_run_metrics(
    bot,
    *,
    asof_date: str,
    now: datetime,
    metrics: TradingRunMetrics,
    cached_api: CachedTradingAPI,
    logger: logging.Logger,
) -> None:
    if bot._run_metrics_logged:
        return
    bot._run_metrics_logged = True
    payload = metrics.as_log_fields()
    payload.update(cached_api.snapshot_counts())
    if not payload:
        return
    payload["asof_date"] = asof_date
    payload["run_time"] = now.isoformat(timespec="seconds")
    bot._journal("RUN_METRICS", **payload)
    logger.info("trading_engine_run_metrics %s", payload)


def should_apply_day_global_signal(config: TradeEngineConfig, now: datetime) -> bool:
    from .risk import current_entry_window_index

    window_index = current_entry_window_index(now, config)
    if window_index is None:
        return False
    return window_index < int(getattr(config, "day_afternoon_entry_start_window_index", 2))
