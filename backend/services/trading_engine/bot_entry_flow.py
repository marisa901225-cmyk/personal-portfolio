from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from .execution import FillResult, enter_position
from .intraday import passes_day_intraday_confirmation
from .news_sentiment import _load_sector_keywords
from .notification_text import (
    format_candidate_review_message,
    format_entry_message,
    format_pending_entry_message,
)
from .risk import can_enter, current_entry_window_index
from .state import PositionState
from .types import OrderPayload, Quote, QuoteMap
from .utils import match_name_to_sectors, parse_numeric

if TYPE_CHECKING:
    from .news_sentiment import NewsSentimentSignal
    from .strategy import Candidates

logger = logging.getLogger(__name__)


def _bot_module():
    from . import bot as bot_module

    return bot_module


def _krx_tick_size(price: float) -> int:
    if price < 2_000:
        return 1
    if price < 5_000:
        return 5
    if price < 20_000:
        return 10
    if price < 50_000:
        return 50
    if price < 200_000:
        return 100
    if price < 500_000:
        return 500
    return 1_000


def _resolve_day_entry_order(
    *,
    quote: Quote | None,
    configured_order_type: str,
) -> tuple[str, int | None]:
    normalized = str(configured_order_type or "").strip().lower()
    if normalized != "best":
        return configured_order_type, None

    price_now = parse_numeric((quote or {}).get("price"))
    if price_now is None or price_now <= 0:
        return "limit", None

    tick = _krx_tick_size(float(price_now))
    return "limit", int(price_now) + tick


def _swing_retry_codes_with_sector_peers(
    *,
    ranked_codes: list[str],
    candidates: "Candidates",
    config,
    news_signal: "NewsSentimentSignal | None" = None,
) -> list[str]:
    if len(ranked_codes) < 2:
        return ranked_codes

    sector_keywords = (
        news_signal.sector_keywords
        if news_signal is not None and getattr(news_signal, "sector_keywords", None)
        else _load_sector_keywords(config.news_sector_queries_path)
    )
    candidate_frame = _build_swing_retry_candidate_frame(candidates)
    if candidate_frame.empty:
        return ranked_codes

    anchor_code = str(ranked_codes[0]).strip()
    second_code = str(ranked_codes[1]).strip()
    anchor_sector = _resolve_swing_candidate_sector(
        code=anchor_code,
        candidate_frame=candidate_frame,
        sector_keywords=sector_keywords,
        news_signal=news_signal,
    )
    if not anchor_sector:
        return ranked_codes

    peer_codes: list[str] = []
    for _, row in candidate_frame.iterrows():
        code = str(row.get("code") or "").strip()
        if not code or code == anchor_code:
            continue
        if _resolve_swing_row_sector(
            row=row,
            sector_keywords=sector_keywords,
            news_signal=news_signal,
        ) != anchor_sector:
            continue
        peer_codes.append(code)
        if len(peer_codes) >= 3:
            break

    ordered: list[str] = []
    seen: set[str] = set()
    for code in [anchor_code, second_code, *peer_codes, *ranked_codes[2:]]:
        normalized = str(code or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def _build_swing_retry_candidate_frame(candidates: "Candidates"):
    import pandas as pd

    frames = [
        getattr(candidates, "model", pd.DataFrame()),
        getattr(candidates, "merged", pd.DataFrame()),
        getattr(candidates, "popular", pd.DataFrame()),
        getattr(candidates, "etf", pd.DataFrame()),
    ]
    usable = [frame for frame in frames if frame is not None and not frame.empty and "code" in frame.columns]
    if not usable:
        return pd.DataFrame()

    merged = pd.concat(usable, ignore_index=True, sort=False)
    sort_cols = [col for col in ("score", "avg_value_20d", "avg_value_5d", "change_pct") if col in merged.columns]
    if sort_cols:
        ascending = [False] * len(sort_cols)
        merged = merged.sort_values(by=sort_cols, ascending=ascending, na_position="last")
    return merged.drop_duplicates(subset=["code"], keep="first").reset_index(drop=True)


def _resolve_swing_candidate_sector(
    *,
    code: str,
    candidate_frame,
    sector_keywords: dict[str, tuple[str, ...]],
    news_signal: "NewsSentimentSignal | None" = None,
) -> str:
    matches = candidate_frame[candidate_frame["code"].astype(str) == str(code)]
    if matches.empty:
        return ""
    return _resolve_swing_row_sector(
        row=matches.iloc[0],
        sector_keywords=sector_keywords,
        news_signal=news_signal,
    )


def _resolve_swing_row_sector(
    *,
    row,
    sector_keywords: dict[str, tuple[str, ...]],
    news_signal: "NewsSentimentSignal | None" = None,
) -> str:
    for key in (
        "industry_bucket_name",
        "theme_sector",
        "industry_small_name",
        "industry_medium_name",
        "industry_large_name",
    ):
        value = str(row.get(key) or "").strip()
        if value:
            return value

    matched = match_name_to_sectors(str(row.get("name") or ""), sector_keywords)
    if not matched:
        return ""
    if news_signal is None:
        return sorted(matched)[0]
    return max(
        matched,
        key=lambda sector: (float(news_signal.sector_scores.get(sector, 0.0)), str(sector)),
    )


class BotEntryFlowMixin:
    def _try_enter_swing(
        self,
        *,
        now: datetime,
        regime: str,
        candidates: Candidates,
        quotes: QuoteMap,
        news_signal: NewsSentimentSignal | None = None,
    ) -> None:
        bot_module = _bot_module()
        ranked_codes = bot_module.rank_swing_codes(candidates, quotes, self.config, news_signal=news_signal)
        code = ranked_codes[0] if ranked_codes else None
        if code and self._should_hold_profitable_existing_position(
            code=code,
            quotes=quotes,
            candidate_type="S",
            now=now,
        ):
            return

        candidate_count = len(candidates.model) + len(candidates.etf)
        ok, reason = can_enter(
            "S",
            self.state,
            regime=regime,
            candidates_count=candidate_count,
            now=now,
            config=self.config,
            is_trading_day_value=True,
        )
        if not ok:
            self._pass(reason, regime)
            if reason == "NO_CANDIDATE":
                self._maybe_notify_swing_skip(now=now, regime=regime, reason=reason, candidates=candidates)
            return

        ranked_codes, review_applied = self._apply_swing_chart_review(
            ranked_codes=ranked_codes,
            candidates=candidates,
            quotes=quotes,
        )
        code = ranked_codes[0] if ranked_codes else None
        if not code:
            self._pass("SWING_LLM_VETO" if review_applied else "NO_SWING_PICK", regime)
            if review_applied:
                self._notify_chart_review_skip(
                    strategy_label="SWING",
                    reason="SWING_LLM_VETO",
                )
            if not review_applied:
                self._maybe_notify_swing_skip(
                    now=now,
                    regime=regime,
                    reason="NO_SWING_PICK",
                    candidates=candidates,
                )
            return

        ranked_codes = _swing_retry_codes_with_sector_peers(
            ranked_codes=ranked_codes,
            candidates=candidates,
            config=self.config,
            news_signal=news_signal,
        )

        result = None
        code = ""
        for ranked_code in ranked_codes:
            attempt = enter_position(
                self.api,
                self.state,
                position_type="S",
                code=ranked_code,
                cash_ratio=self.config.swing_cash_ratio,
                budget_cash_cap=self._strategy_budget_cash_cap(cash_ratio=self.config.swing_cash_ratio),
                asof_date=self.state.trade_date,
                now=now,
                order_type=self.config.swing_entry_order_type,
            )
            if attempt:
                result = attempt
                code = ranked_code
                break
            synced_result, pending_order = self._recover_failed_buy_attempt(
                code=ranked_code,
                strategy_type="S",
                now=now,
                regime=regime,
            )
            if synced_result is not None:
                result = synced_result
                code = ranked_code
                break
            if pending_order is not None:
                return
        if not result:
            self._pass("SWING_ENTRY_FAILED", regime)
            if review_applied:
                self._notify_chart_review_skip(
                    strategy_label="SWING",
                    reason="SWING_ENTRY_FAILED",
                    code=ranked_codes[0] if ranked_codes else None,
                )
            return

        self._journal(
            "ENTRY_FILL",
            asof_date=self.state.trade_date,
            code=code,
            side="BUY",
            qty=result.qty,
            avg_price=result.avg_price,
            strategy_type="S",
            regime=regime,
            **self._entry_sizing_fields(result),
        )
        if result.reason == "BROKER_SYNC":
            self._notify_text(
                format_entry_message(
                    strategy="S",
                    code=code,
                    qty=result.qty,
                    avg_price=result.avg_price,
                    regime=regime,
                    sync=True,
                )
            )
        else:
            self._notify_text(
                format_entry_message(
                    strategy="S",
                    code=code,
                    qty=result.qty,
                    avg_price=result.avg_price,
                    regime=regime,
                )
            )

    def _try_enter_day(
        self,
        *,
        now: datetime,
        regime: str,
        candidates: Candidates,
        quotes: QuoteMap,
        news_signal: NewsSentimentSignal | None = None,
    ) -> None:
        bot_module = _bot_module()
        ranked_codes = bot_module.rank_daytrade_codes(candidates, quotes, self.config, news_signal=news_signal)
        ranked_codes = self._apply_day_intraday_confirmation(ranked_codes, now=now)
        if ranked_codes and self._should_hold_profitable_existing_position(
            code=ranked_codes[0],
            quotes=quotes,
            candidate_type="T",
            now=now,
        ):
            return

        ok, reason = can_enter(
            "T",
            self.state,
            regime=regime,
            candidates_count=len(candidates.popular),
            now=now,
            config=self.config,
            is_trading_day_value=True,
        )
        if not ok:
            self._pass(reason, regime)
            return

        ranked_codes, review_applied = self._apply_day_chart_review(
            ranked_codes=ranked_codes,
            candidates=candidates,
            quotes=quotes,
        )
        if not ranked_codes:
            self._pass("DAY_LLM_VETO" if review_applied else "NO_DAY_PICK", regime)
            if review_applied:
                self._notify_chart_review_skip(
                    strategy_label="DAY",
                    reason="DAY_LLM_VETO",
                )
            return

        self._reconcile_state_with_broker_positions(now=now)
        ok, reason = can_enter(
            "T",
            self.state,
            regime=regime,
            candidates_count=len(ranked_codes),
            now=now,
            config=self.config,
            is_trading_day_value=True,
        )
        if not ok:
            self._pass(reason, regime)
            return

        result = None
        code = ""
        for ranked_code in ranked_codes:
            quote = quotes.get(ranked_code) if isinstance(quotes, dict) else None
            order_type, price = _resolve_day_entry_order(
                quote=quote,
                configured_order_type=self.config.day_entry_order_type,
            )
            attempt = enter_position(
                self.api,
                self.state,
                position_type="T",
                code=ranked_code,
                cash_ratio=self.config.day_cash_ratio,
                budget_cash_cap=self._strategy_budget_cash_cap(cash_ratio=self.config.day_cash_ratio),
                asof_date=self.state.trade_date,
                now=now,
                order_type=order_type,
                price=price,
            )
            if attempt:
                result = attempt
                code = ranked_code
                break
            synced_result, pending_order = self._recover_failed_buy_attempt(
                code=ranked_code,
                strategy_type="T",
                now=now,
                regime=regime,
            )
            if synced_result is not None:
                result = synced_result
                code = ranked_code
                break
            if pending_order is not None:
                return
        if not result:
            self._pass("DAY_ENTRY_FAILED", regime)
            if review_applied:
                self._notify_chart_review_skip(
                    strategy_label="DAY",
                    reason="DAY_ENTRY_FAILED",
                    code=ranked_codes[0] if ranked_codes else None,
                )
            return
        window_index = current_entry_window_index(now, self.config)
        if window_index is not None:
            self.state.day_entry_windows_used_today.add(window_index)

        self._journal(
            "ENTRY_FILL",
            asof_date=self.state.trade_date,
            code=code,
            side="BUY",
            qty=result.qty,
            avg_price=result.avg_price,
            strategy_type="T",
            regime=regime,
            **self._entry_sizing_fields(result),
        )
        if result.reason == "BROKER_SYNC":
            self._notify_text(
                format_entry_message(
                    strategy="T",
                    code=code,
                    qty=result.qty,
                    avg_price=result.avg_price,
                    regime=regime,
                    sync=True,
                )
            )
        else:
            self._notify_text(
                format_entry_message(
                    strategy="T",
                    code=code,
                    qty=result.qty,
                    avg_price=result.avg_price,
                    regime=regime,
                )
            )

    def _apply_day_intraday_confirmation(
        self,
        ranked_codes: list[str],
        *,
        now: datetime,
    ) -> list[str]:
        del now
        if not ranked_codes or not self.config.day_use_intraday_confirmation:
            return ranked_codes

        filtered_codes: list[str] = []
        for code in ranked_codes:
            ok, meta = self._passes_day_intraday_confirmation(code=code)
            if ok:
                filtered_codes.append(code)
                continue

            self._journal(
                "DAY_CANDIDATE_FILTERED",
                asof_date=self.state.trade_date,
                code=code,
                reason=meta.get("reason"),
                bars=meta.get("bars"),
                window_change_pct=meta.get("window_change_pct"),
                last_bar_change_pct=meta.get("last_bar_change_pct"),
                retrace_from_high_pct=meta.get("retrace_from_high_pct"),
                recent_range_pct=meta.get("recent_range_pct"),
                day_change_pct=meta.get("day_change_pct"),
            )

        return filtered_codes

    def _passes_day_intraday_confirmation(
        self,
        *,
        code: str,
    ) -> tuple[bool, dict[str, object]]:
        return passes_day_intraday_confirmation(
            self.api,
            trade_date=self.state.trade_date,
            code=code,
            config=self.config,
            logger=logger,
        )

    def _resolve_day_lock_retrace_gap_pct(self, *, code: str) -> float | None:
        multiplier = max(0.0, float(getattr(self.config, "day_lock_volatility_gap_multiplier", 0.0)))
        if multiplier <= 0:
            return None

        _, meta = self._passes_day_intraday_confirmation(code=code)
        recent_range_pct = parse_numeric(meta.get("recent_range_pct"))
        if recent_range_pct is None or recent_range_pct <= 0:
            return None

        adaptive_gap_pct = (float(recent_range_pct) / 100.0) * multiplier
        return max(float(self.config.day_lock_retrace_gap_pct), adaptive_gap_pct)

    def _apply_day_chart_review(
        self,
        *,
        ranked_codes: list[str],
        candidates: Candidates,
        quotes: QuoteMap,
    ) -> tuple[list[str], bool]:
        if not ranked_codes or not self.config.day_chart_review_enabled:
            return ranked_codes, False

        bot_module = _bot_module()
        review = bot_module.review_day_candidates_with_llm(
            api=self.api,
            trade_date=self.state.trade_date,
            ranked_codes=ranked_codes,
            candidates=candidates,
            quotes=quotes,
            config=self.config,
            output_dir=self.config.output_dir,
        )
        if review is None:
            return ranked_codes, False

        self._journal(
            "DAY_CHART_REVIEW",
            asof_date=self.state.trade_date,
            shortlisted_codes=",".join(review.shortlisted_codes),
            approved_codes=",".join(review.approved_codes),
            selected_code=review.selected_code,
            summary=review.summary,
        )
        summary = review.summary or "차트 구조 기준으로 shortlist 재검토 완료"
        selected = review.selected_code or (review.approved_codes[0] if review.approved_codes else "NONE")
        self._notify_text(
            format_candidate_review_message(
                strategy="DAY",
                shortlisted_codes=review.shortlisted_codes,
                selected_code=selected,
                approved_codes=review.approved_codes,
                summary=summary,
            )
        )
        for path in review.chart_paths:
            self._notify_file(path, caption="[단타][LLM][차트]")
        return review.approved_codes, True

    def _apply_swing_chart_review(
        self,
        *,
        ranked_codes: list[str],
        candidates: Candidates,
        quotes: QuoteMap,
    ) -> tuple[list[str], bool]:
        if not ranked_codes or not self.config.swing_chart_review_enabled:
            return ranked_codes, False
        if any(position.type == "S" for position in self.state.open_positions.values()):
            return ranked_codes, False

        bot_module = _bot_module()
        review = bot_module.review_swing_candidates_with_llm(
            api=self.api,
            trade_date=self.state.trade_date,
            ranked_codes=ranked_codes,
            candidates=candidates,
            quotes=quotes,
            config=self.config,
            output_dir=self.config.output_dir,
        )
        if review is None:
            return ranked_codes, False

        self._journal(
            "SWING_CHART_REVIEW",
            asof_date=self.state.trade_date,
            shortlisted_codes=",".join(review.shortlisted_codes),
            approved_codes=",".join(review.approved_codes),
            selected_code=review.selected_code,
            summary=review.summary,
        )
        summary = review.summary or "차트 구조 기준으로 swing shortlist 재검토 완료"
        selected = review.selected_code or (review.approved_codes[0] if review.approved_codes else "NONE")
        self._notify_text(
            format_candidate_review_message(
                strategy="SWING",
                shortlisted_codes=review.shortlisted_codes,
                selected_code=selected,
                approved_codes=review.approved_codes,
                summary=summary,
            )
        )
        for path in review.chart_paths:
            self._notify_file(path, caption="[스윙][LLM][차트]")
        return review.approved_codes, True

    def _recover_failed_buy_attempt(
        self,
        *,
        code: str,
        strategy_type: str,
        now: datetime,
        regime: str,
    ) -> tuple[FillResult | None, OrderPayload | None]:
        synced_result = self._sync_broker_filled_position(
            code=code,
            strategy_type=strategy_type,
            now=now,
            regime=regime,
        )
        if synced_result is not None:
            return synced_result, None

        pending_order = self._find_pending_buy_order(code=code)
        if pending_order is not None:
            self.state.pending_entry_orders[str(code).strip()] = str(strategy_type).strip().upper()
            order_id = str(pending_order.get("order_id") or "")
            order_qty = int(parse_numeric(pending_order.get("qty")) or 0)
            remaining_qty = int(parse_numeric(pending_order.get("remaining_qty")) or 0)
            order_price = parse_numeric(pending_order.get("price"))
            self._notify_text(
                format_pending_entry_message(
                    strategy=strategy_type,
                    code=code,
                    order_id=order_id or "",
                    qty=order_qty,
                    remaining_qty=remaining_qty,
                    price=int(order_price) if order_price else 0,
                )
            )
            return None, pending_order

        return None, None

    def _sync_broker_filled_position(
        self,
        *,
        code: str,
        strategy_type: str,
        now: datetime,
        regime: str,
    ) -> FillResult | None:
        normalized_code = str(code or "").strip()
        if not normalized_code:
            return None

        try:
            broker_positions = self.api.positions() or []
        except Exception:
            logger.warning("broker position recheck failed code=%s", normalized_code, exc_info=True)
            return None

        for item in broker_positions:
            broker_code = str(item.get("code") or item.get("pdno") or "").strip()
            qty = int(parse_numeric(item.get("qty") or item.get("hldg_qty")) or 0)
            if broker_code != normalized_code or qty <= 0:
                continue

            avg_price = parse_numeric(item.get("avg_price") or item.get("pchs_avg_pric"))
            current_price = parse_numeric(item.get("current_price") or item.get("prpr"))
            resolved_price = float(avg_price or current_price or 0.0)
            if resolved_price <= 0:
                quote = self.api.quote(normalized_code)
                resolved_price = float(parse_numeric(quote.get("price")) or 0.0)
            if resolved_price <= 0:
                return None

            existing = self.state.open_positions.get(normalized_code)
            if existing is None:
                self.state.open_positions[normalized_code] = PositionState(
                    type=strategy_type,
                    entry_time=now.isoformat(timespec="seconds"),
                    entry_price=resolved_price,
                    qty=qty,
                    highest_price=resolved_price,
                    entry_date=self.state.trade_date,
                    locked_profit_pct=None,
                    bars_held=0,
                )
                if strategy_type == "S":
                    self.state.swing_entries_today += 1
                    self.state.swing_entries_week += 1
                elif strategy_type == "T":
                    self.state.day_entries_today += 1
                self.state.blacklist_today.add(normalized_code)
                self._journal(
                    "STATE_RECONCILE_ADD",
                    asof_date=self.state.trade_date,
                    code=normalized_code,
                    qty=qty,
                    avg_price=resolved_price,
                    reason="BROKER_POSITION_FOUND_AFTER_ENTRY_ATTEMPT",
                    strategy_type=strategy_type,
                    regime=regime,
                )
            else:
                existing.qty = qty
                existing.entry_price = resolved_price
                existing.highest_price = max(float(existing.highest_price or 0.0), resolved_price)

            self.state.pending_entry_orders.pop(normalized_code, None)

            return FillResult(
                code=normalized_code,
                side="BUY",
                qty=qty,
                avg_price=resolved_price,
                reason="BROKER_SYNC",
                raw=dict(item) if isinstance(item, dict) else None,
            )

        return None

    def _find_pending_buy_order(self, *, code: str) -> OrderPayload | None:
        normalized_code = str(code or "").strip()
        if not normalized_code:
            return None

        try:
            open_orders = self.api.open_orders() or []
        except Exception:
            logger.warning("open_orders recheck failed code=%s", normalized_code, exc_info=True)
            return None

        for order in open_orders:
            order_code = str(order.get("code") or order.get("pdno") or "").strip()
            if order_code != normalized_code:
                continue
            side = str(order.get("side") or order.get("sll_buy_dvsn_cd") or "").strip().lower()
            if side not in {"buy", "02"}:
                continue
            remaining_qty = parse_numeric(order.get("remaining_qty") or order.get("psbl_qty"))
            if remaining_qty is not None and remaining_qty <= 0:
                continue
            return dict(order)
        return None

    def _refresh_pending_entry_orders(self) -> None:
        if not self.state.pending_entry_orders:
            return

        try:
            open_orders = self.api.open_orders() or []
        except Exception:
            logger.warning("open_orders refresh failed for pending entry sync", exc_info=True)
            return

        pending_codes: set[str] = set()
        for order in open_orders:
            order_code = str(order.get("code") or order.get("pdno") or "").strip()
            if not order_code:
                continue
            side = str(order.get("side") or order.get("sll_buy_dvsn_cd") or "").strip().lower()
            if side not in {"buy", "02"}:
                continue
            remaining_qty = parse_numeric(order.get("remaining_qty") or order.get("psbl_qty"))
            if remaining_qty is not None and remaining_qty <= 0:
                continue
            pending_codes.add(order_code)

        for code in list(self.state.pending_entry_orders):
            if code in self.state.open_positions or code in pending_codes:
                continue
            self.state.pending_entry_orders.pop(code, None)
