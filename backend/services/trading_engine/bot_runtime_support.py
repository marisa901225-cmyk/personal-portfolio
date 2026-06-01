from __future__ import annotations

import json
from datetime import datetime
import logging

import pandas as pd

from .config import TradeEngineConfig
from ..llm.service import LLMService
from ..prompt_loader import load_prompt
from .journal import TradeJournal
from .notification_text import exit_reason_label, reason_label
from .run_context import CachedTradingAPI, TradingRunMetrics
from .stock_master import load_stock_master_map
from .strategy import Candidates
from .utils import parse_numeric

_DEFAULT_FINALIZE_SYSTEM_PROMPT = (
    "너는 자동매매 마감 문자를 읽기 쉽게 정리하는 비서다. "
    "입력에 있는 숫자와 사실만 사용하고, 한국어로 4~7줄 마감 브리핑을 작성하라. "
    "매수와 청산은 줄을 나누고, 첫 줄은 반드시 '[마감] YYYYMMDD' 형식으로 시작하라."
)


def entry_sizing_fields(result: object) -> dict[str, object]:
    sizing = getattr(result, "sizing", None) or {}
    if not isinstance(sizing, dict):
        return {}
    return dict(sizing)


def strategy_budget_cash_cap(bot, *, cash_ratio: float, position_type: str | None = None) -> float | None:
    normalized_position_type = str(position_type or "").strip().upper()
    if normalized_position_type == "S":
        account_budget_total = account_budget_total_from_account(bot, logger=logging.getLogger(__name__))
        base_cap = max(0.0, account_budget_total * float(cash_ratio))
    else:
        base_cap = max(0.0, float(bot.config.initial_capital) * float(cash_ratio))
    unused_swing_budget = 0.0
    budget_cap = base_cap
    if normalized_position_type == "S":
        budget_cap = max(0.0, base_cap - deployed_swing_cost_from_state(bot))
    elif normalized_position_type == "T":
        unused_swing_budget = unused_swing_budget_for_day(bot)
        budget_cap += unused_swing_budget

    return _cap_day_entry_budget(
        bot,
        _split_conditional_day_budget(
            bot,
            budget_cap=budget_cap,
            position_type=normalized_position_type,
            unused_swing_budget=unused_swing_budget,
        ),
        normalized_position_type,
    )


def _cap_day_entry_budget(bot, budget_cap: float, position_type: str) -> float:
    if position_type != "T":
        return budget_cap
    per_entry_cap = max(0.0, float(getattr(bot.config, "day_entry_budget_cap_krw", 0) or 0))
    if per_entry_cap <= 0:
        return budget_cap
    return max(0.0, min(float(budget_cap), per_entry_cap))


def _split_conditional_day_budget(
    bot,
    *,
    budget_cap: float,
    position_type: str,
    unused_swing_budget: float,
) -> float:
    if position_type != "T":
        return budget_cap
    active_slots = _conditional_day_budget_slots(
        bot,
        total_budget_cap=budget_cap,
        unused_swing_budget=unused_swing_budget,
    )
    if active_slots <= 1:
        return budget_cap
    return max(0.0, float(budget_cap) / float(active_slots))


def _conditional_day_budget_slots(
    bot,
    *,
    total_budget_cap: float,
    unused_swing_budget: float,
) -> int:
    config: TradeEngineConfig = bot.config
    if not bool(getattr(config, "day_conditional_extra_entries_enabled", False)):
        return 1
    extra_entries = max(0, int(getattr(config, "day_conditional_extra_entries", 0) or 0))
    if extra_entries <= 0 or unused_swing_budget <= 0:
        return 1
    if not _conditional_day_performance_allows_extra_slots(bot):
        return 1

    extra_slot_floor = _day_extra_slot_budget_floor(config)
    if unused_swing_budget < extra_slot_floor:
        return 1

    affordable_slots = max(1, int(float(total_budget_cap) // extra_slot_floor))
    return max(1, min(2, 1 + extra_entries, affordable_slots))


def _conditional_day_performance_allows_extra_slots(bot) -> bool:
    config = bot.config
    state = bot.state
    wins = max(0, int(getattr(state, "day_wins_today", 0) or 0))
    losses = max(0, int(getattr(state, "day_losses_today", 0) or 0))
    closed_trades = wins + losses
    min_closed_trades = max(0, int(getattr(config, "day_conditional_extra_min_closed_trades", 0) or 0))
    if closed_trades < min_closed_trades:
        return False

    win_rate = wins / closed_trades if closed_trades else 0.0
    min_win_rate = float(getattr(config, "day_conditional_extra_min_win_rate", 0.0) or 0.0)
    if win_rate < min_win_rate:
        return False

    min_realized_pnl = float(getattr(config, "day_conditional_extra_min_realized_pnl", 0.0) or 0.0)
    if float(getattr(state, "realized_pnl_today", 0.0) or 0.0) < min_realized_pnl:
        return False

    max_losses = max(0, int(getattr(config, "day_conditional_extra_max_consecutive_losses", 0) or 0))
    return int(getattr(state, "consecutive_losses_today", 0) or 0) <= max_losses


def _day_extra_slot_budget_floor(config: TradeEngineConfig) -> float:
    base_day_budget = max(0.0, float(config.initial_capital) * float(config.day_cash_ratio))
    min_order_amount = max(0.0, float(getattr(config, "day_conditional_extra_min_order_amount_krw", 0) or 0))
    return max(base_day_budget, min_order_amount)


def unused_swing_budget_for_day(bot) -> float:
    if not bool(getattr(bot.config, "day_reuse_unused_swing_cash_enabled", True)):
        return 0.0

    account_budget_total = account_budget_total_from_account(bot, logger=logging.getLogger(__name__))
    swing_budget_cap = max(
        0.0,
        account_budget_total * float(bot.config.swing_cash_ratio),
    )
    if swing_budget_cap <= 0:
        return 0.0

    deployed_swing_cost = deployed_swing_cost_from_state(bot)
    if deployed_swing_cost <= 0:
        return 0.0

    unused_swing_budget = max(0.0, swing_budget_cap - deployed_swing_cost)
    return unused_swing_budget


def deployed_swing_cost_from_state(bot) -> float:
    deployed_swing_cost = 0.0
    for position in bot.state.open_positions.values():
        if getattr(position, "type", "") != "S":
            continue
        qty = max(0, int(getattr(position, "qty", 0) or 0))
        entry_price = max(0.0, float(getattr(position, "entry_price", 0.0) or 0.0))
        if qty <= 0 or entry_price <= 0:
            continue
        deployed_swing_cost += float(qty) * float(entry_price)
    return deployed_swing_cost


def account_budget_total_from_account(bot, *, logger: logging.Logger) -> float:
    if not bool(getattr(bot.config, "use_realized_profit_buffer", True)):
        return max(0.0, float(bot.config.initial_capital))
    try:
        cash_available = max(0.0, float(bot.api.cash_available()))
        positions = bot.api.positions() or []
        eval_value_total = 0.0
        for item in positions:
            qty = parse_numeric(item.get("qty") or item.get("hldg_qty"))
            current_price = parse_numeric(
                item.get("current_price")
                or item.get("prpr")
                or item.get("now_pric")
                or item.get("avg_price")
                or item.get("pchs_avg_pric")
            )
            if qty is None or current_price is None or qty <= 0 or current_price <= 0:
                continue
            eval_value_total += float(qty) * float(current_price)
        return max(0.0, cash_available + eval_value_total)
    except Exception:
        logger.warning("account budget total snapshot failed; using configured initial capital", exc_info=True)
        return max(0.0, float(bot.config.initial_capital))


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


def build_finalize_message_with_local_llm(
    *,
    trade_date: str,
    journal_summary: str,
    realized_pnl: float,
    realized_pct: float,
    open_positions: int,
    pass_reasons: dict[str, int],
    logger: logging.Logger,
    account_summary: str | None = None,
    trade_activity_summary: str | None = None,
    state_sync_summary: str | None = None,
    price_sync_summary: str | None = None,
) -> str | None:
    llm = LLMService.get_instance()
    if not llm.settings.is_remote_configured():
        return None

    raw_context = (
        f"거래일: {trade_date}\n"
        f"이벤트 요약: {journal_summary or '이벤트 없음'}\n"
        f"실현손익: {realized_pnl:,.0f}원 ({realized_pct:+.2f}%)\n"
        f"오늘 매매 요약: {trade_activity_summary or '체결/청산 특이사항 없음'}\n"
        f"상태동기화: {state_sync_summary or '0건'}\n"
        f"시세동기화: {price_sync_summary or '확인 없음'}\n"
        f"마감 시 열린 포지션 수: {open_positions}\n"
        f"계좌 상황: {account_summary or '확인 불가'}\n"
        f"패스 특이사항: {summarize_finalize_pass_reasons(pass_reasons)}\n"
    )
    messages = [
        {
            "role": "system",
            "content": load_prompt("trading_finalize_summary_system") or _DEFAULT_FINALIZE_SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": raw_context,
        },
    ]
    try:
        text = llm.generate_chat(
            messages,
            max_tokens=900,
            temperature=0.2,
            model="gpt-5.4-mini",
            allow_paid_fallback=True,
        )
    except Exception:
        logger.warning("trading finalize local LLM summary failed", exc_info=True)
        return None

    text = _clean_finalize_llm_message(text)
    if not text:
        return None
    if not text.startswith("[마감]"):
        text = f"[마감] {trade_date}\n{text}"
    realized_amount_text = f"{realized_pnl:,.0f}원"
    if realized_amount_text not in text:
        text = f"{text}\n실현손익: {realized_pnl:,.0f}원 ({realized_pct:+.2f}%)"
    return text


def _clean_finalize_llm_message(text: str) -> str:
    lines: list[str] = []
    in_reason = False
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.lower().startswith("<reason"):
            in_reason = True
            continue
        if line.lower().startswith("</reason"):
            in_reason = False
            continue
        if in_reason:
            continue
        if line.startswith("```"):
            continue
        lines.append(line)
    cleaned = "\n".join(lines).strip()
    return cleaned.replace("%)로", "%)으로")


def summarize_finalize_pass_reasons(pass_reasons: dict[str, int]) -> str:
    noteworthy_labels = {
        "DAILY_MAX_LOSS": "일일 손실 한도 도달",
        "DAY_AFTERNOON_LOSS_LIMIT": "오후 단타 손실 제한",
        "DAY_ENTRY_FAILED": "단타 진입 실패",
        "DAY_ENTRY_RECHECK_FAILED": "주문 직전 단타 흐름 약화",
        "FETCH_FAILED": "장중 데이터 조회 실패",
        "MAX_CONSECUTIVE_LOSSES": "연속 손실 제한",
        "STATE_LOAD_CORRUPT": "상태 파일 손상 감지",
        "STATE_RECOVERY_REQUIRED": "상태 복구 점검 필요",
        "SWING_ENTRY_FAILED": "스윙 진입 실패",
    }
    phrases = [
        noteworthy_labels[str(reason)]
        for reason, count in sorted(pass_reasons.items(), key=lambda item: str(item[0]))
        if int(count) > 0 and str(reason) in noteworthy_labels
    ]
    if not phrases:
        return "특이사항 없음"
    return ", ".join(dict.fromkeys(phrases))


def finalize_account_summary(bot, *, logger: logging.Logger) -> str | None:
    snapshot = finalize_account_snapshot(bot, logger=logger)
    if snapshot is None:
        return None

    cash = snapshot.get("cash")
    position_count = int(snapshot.get("position_count") or 0)
    holding_labels = list(snapshot.get("holding_labels") or [])
    eval_pnl_total = float(snapshot.get("eval_pnl_total") or 0.0)
    eval_value_total = float(snapshot.get("eval_value_total") or 0.0)
    cost_basis_total = float(snapshot.get("cost_basis_total") or 0.0)

    parts: list[str] = []
    if cash is not None:
        parts.append(f"예수금 {float(cash):,.0f}원")
    if holding_labels:
        extra_count = position_count - len(holding_labels)
        suffix = f" 외 {extra_count}종목" if extra_count > 0 else ""
        parts.append(f"보유 {position_count}종목: {', '.join(holding_labels)}{suffix}")
    else:
        parts.append(f"보유 {position_count}종목")
    if position_count > 0:
        if eval_value_total > 0:
            parts.append(f"평가금액 {eval_value_total:,.0f}원")
        if eval_pnl_total:
            eval_pnl_pct = (eval_pnl_total / cost_basis_total * 100.0) if cost_basis_total > 0 else 0.0
            parts.append(f"평가손익 {eval_pnl_total:,.0f}원 ({eval_pnl_pct:+.2f}%)")
    return ", ".join(parts)


def finalize_calendar_account_summary(bot, *, logger: logging.Logger) -> str | None:
    context = finalize_calendar_account_context(bot, logger=logger)
    if context is None:
        return None
    return str(context.get("account_line") or "") or None


def finalize_calendar_account_context(bot, *, logger: logging.Logger) -> dict[str, object] | None:
    snapshot = finalize_account_snapshot(bot, logger=logger)
    if snapshot is None:
        return None

    cash = snapshot.get("cash")
    position_count = int(snapshot.get("position_count") or 0)
    cost_basis_total = float(snapshot.get("cost_basis_total") or 0.0)
    eval_pnl_total = float(snapshot.get("eval_pnl_total") or 0.0)
    eval_value_total = float(snapshot.get("eval_value_total") or 0.0)
    total_value = (float(cash) if cash is not None else 0.0) + eval_value_total
    if total_value <= 0:
        return None
    eval_pct = (eval_pnl_total / cost_basis_total * 100.0) if cost_basis_total > 0 else None
    parts = [f"총평가 {total_value:,.0f}원"]
    if cash is not None:
        parts.append(f"현금 {float(cash):,.0f}원")
    parts.append(f"보유 {position_count}종목")
    return {
        "account_line": " / ".join(parts),
        "eval_pct": eval_pct,
    }


def finalize_account_snapshot(bot, *, logger: logging.Logger) -> dict[str, object] | None:
    cash_available = getattr(bot.api, "cash_available", None)
    if callable(cash_available):
        try:
            cash = parse_numeric(cash_available())
        except Exception:
            logger.warning("finalize account cash snapshot failed", exc_info=True)
            cash = None
    else:
        cash = None

    positions_fn = getattr(bot.api, "positions", None)
    if callable(positions_fn):
        try:
            positions = positions_fn() or []
        except Exception:
            logger.warning("finalize account positions snapshot failed", exc_info=True)
            positions = []
    else:
        positions = []

    position_count = 0
    eval_pnl_total = 0.0
    eval_value_total = 0.0
    cost_basis_total = 0.0
    holding_labels: list[str] = []
    for item in positions:
        if not isinstance(item, dict):
            continue
        qty = parse_numeric(item.get("qty") or item.get("hldg_qty"))
        if qty is None or qty <= 0:
            continue
        position_count += 1
        code = str(item.get("code") or item.get("pdno") or "").strip()
        name = str(item.get("name") or item.get("prdt_name") or "").strip()
        if len(holding_labels) < 3:
            if name or code:
                holding_labels.append(name or code)
        avg_price = parse_numeric(item.get("avg_price") or item.get("pchs_avg_pric"))
        current_price = parse_numeric(item.get("current_price") or item.get("prpr"))
        pnl = parse_numeric(item.get("pnl") or item.get("evlu_pfls_amt"))
        if pnl is not None:
            eval_pnl_total += float(pnl)
        if avg_price is not None and avg_price > 0:
            cost_basis_total += float(avg_price) * float(qty)
        if current_price is not None and current_price > 0:
            eval_value_total += float(current_price) * float(qty)

    if cash is None and position_count == 0:
        return None

    return {
        "cash": cash,
        "position_count": position_count,
        "holding_labels": holding_labels,
        "eval_pnl_total": eval_pnl_total,
        "eval_value_total": eval_value_total,
        "cost_basis_total": cost_basis_total,
    }


def finalize_trade_activity_summary(
    *,
    journal: TradeJournal,
    config: TradeEngineConfig,
    logger: logging.Logger,
) -> str | None:
    rows = _load_journal_rows(journal.jsonl_path, logger=logger)
    if not rows:
        return None

    name_map = _load_finalize_name_map(config=config, logger=logger)
    entries_by_code: dict[str, str] = {}
    exit_by_code: dict[str, str] = {}

    for row in rows:
        event = str(row.get("event") or "").strip().upper()
        code = str(row.get("code") or "").strip()
        if not code:
            continue
        name = _resolve_finalize_stock_name(code, name_map)
        if event in {"ENTRY_FILL", "STATE_RECONCILE_ADD"}:
            qty = int(parse_numeric(row.get("qty")) or 0)
            avg_price = parse_numeric(row.get("avg_price"))
            strategy_type = str(row.get("strategy_type") or "").strip().upper()
            strategy_label = "스윙" if strategy_type == "S" else "단타" if strategy_type == "T" else "파킹" if strategy_type == "P" else ""
            price_text = f" {float(avg_price):,.0f}원" if avg_price is not None else ""
            qty_text = f" {qty}주" if qty > 0 else ""
            prefix = f"{strategy_label} " if strategy_label else ""
            entries_by_code[code] = f"{prefix}{name}{qty_text}{price_text}".strip()
            continue

        exit_text = _format_finalize_exit_row(row=row, name=name)
        if exit_text:
            exit_by_code[code] = exit_text

    parts: list[str] = []
    if entries_by_code:
        parts.append(f"매수: {_join_limited(list(entries_by_code.values()))}")
    if exit_by_code:
        parts.append(f"청산: {_join_limited(list(exit_by_code.values()))}")
    return " / ".join(parts) if parts else None


def finalize_state_sync_summary(
    *,
    journal: TradeJournal,
    logger: logging.Logger,
) -> str | None:
    rows = _load_journal_rows(journal.jsonl_path, logger=logger)
    if not rows:
        return None
    sync_count = sum(1 for row in rows if str(row.get("event") or "").strip().upper().startswith("STATE_RECONCILE_"))
    if sync_count <= 0:
        return None
    return f"{sync_count}건"


def finalize_price_sync_summary(
    *,
    trade_date: str,
    status_path: str,
    logger: logging.Logger,
) -> str | None:
    try:
        with open(status_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError):
        logger.warning("finalize price sync status read failed path=%s", status_path, exc_info=True)
        return None
    if not isinstance(payload, dict):
        return None
    if str(payload.get("trade_date") or "") != str(trade_date):
        return None
    ticker_count = int(parse_numeric(payload.get("ticker_count")) or 0)
    if ticker_count <= 0:
        return None
    synced_at = str(payload.get("synced_at") or "").strip()
    if synced_at:
        return f"{ticker_count}종목 완료 ({synced_at} 기준)"
    return f"{ticker_count}종목 완료"


def _load_journal_rows(path: str, *, logger: logging.Logger) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except OSError:
        logger.warning("finalize trade journal read failed path=%s", path, exc_info=True)
    return rows


def _load_finalize_name_map(*, config: TradeEngineConfig, logger: logging.Logger) -> dict[str, str]:
    try:
        master_map = load_stock_master_map(
            kospi_master_path=config.industry_kospi_master_path,
            kosdaq_master_path=config.industry_kosdaq_master_path,
        )
    except Exception:
        logger.warning("finalize stock master load failed", exc_info=True)
        return {}
    return {code: info.name for code, info in master_map.items() if getattr(info, "name", "")}


def _resolve_finalize_stock_name(code: str, name_map: dict[str, str]) -> str:
    return str(name_map.get(code) or code).strip() or code


def _format_finalize_exit_row(*, row: dict[str, object], name: str) -> str | None:
    event = str(row.get("event") or "").strip().upper()
    if event not in {"EXIT_FILL", "STATE_RECONCILE_DROP"}:
        return None
    reason = str(row.get("reason") or row.get("exit_reason") or "").strip().upper()
    if event == "STATE_RECONCILE_DROP":
        reason = str(row.get("exit_reason") or "").strip().upper()
        if not reason:
            return None
    qty = int(parse_numeric(row.get("exit_fill_qty") or row.get("qty")) or 0)
    pnl_pct = parse_numeric(row.get("exit_fill_pnl_pct") or row.get("pnl_pct"))
    price = parse_numeric(row.get("exit_fill_avg_price") or row.get("avg_price"))
    qty_text = f" {qty}주" if qty > 0 else ""
    price_text = f" {float(price):,.0f}원" if price is not None else ""
    pnl_text = f" {float(pnl_pct):+.2f}%" if pnl_pct is not None else ""
    reason_text = exit_reason_label(reason, pnl_pct=pnl_pct) if reason else "청산"
    return f"{name}{qty_text} {reason_text}{price_text}{pnl_text}".strip()


def _join_limited(items: list[str], *, limit: int = 6) -> str:
    visible = [item for item in items if item][:limit]
    suffix = f" 외 {len(items) - limit}건" if len(items) > limit else ""
    return ", ".join(visible) + suffix


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
