from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from .execution import enter_position
from .intraday import passes_day_intraday_confirmation
from .risk import can_enter
from .utils import parse_numeric

logger = logging.getLogger(__name__)


def _bot_module():
    from . import bot as bot_module

    return bot_module


class BotEntryFlowMixin:
    def _try_enter_swing(
        self,
        *,
        now: datetime,
        regime: str,
        candidates: Any,
        quotes: dict[str, Any],
        news_signal: Any | None = None,
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
            if not review_applied:
                self._maybe_notify_swing_skip(
                    now=now,
                    regime=regime,
                    reason="NO_SWING_PICK",
                    candidates=candidates,
                )
            return

        result = enter_position(
            self.api,
            self.state,
            position_type="S",
            code=code,
            cash_ratio=self.config.swing_cash_ratio,
            budget_cash_cap=self._strategy_budget_cash_cap(cash_ratio=self.config.swing_cash_ratio),
            asof_date=self.state.trade_date,
            now=now,
            order_type=self.config.swing_entry_order_type,
        )
        if not result:
            self._pass("SWING_ENTRY_FAILED", regime)
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
        self._notify_text(f"[ENTRY][S] {code} qty={result.qty} avg={result.avg_price:.0f} regime={regime}")

    def _try_enter_day(
        self,
        *,
        now: datetime,
        regime: str,
        candidates: Any,
        quotes: dict[str, Any],
        news_signal: Any | None = None,
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
            return

        result = None
        code = ""
        for ranked_code in ranked_codes:
            attempt = enter_position(
                self.api,
                self.state,
                position_type="T",
                code=ranked_code,
                cash_ratio=self.config.day_cash_ratio,
                budget_cash_cap=self._strategy_budget_cash_cap(cash_ratio=self.config.day_cash_ratio),
                asof_date=self.state.trade_date,
                now=now,
                order_type=self.config.day_entry_order_type,
            )
            if attempt:
                result = attempt
                code = ranked_code
                break
        if not result:
            self._pass("DAY_ENTRY_FAILED", regime)
            return

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
        self._notify_text(f"[ENTRY][T] {code} qty={result.qty} avg={result.avg_price:.0f} regime={regime}")

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
    ) -> tuple[bool, dict[str, Any]]:
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
        candidates: Any,
        quotes: dict[str, Any],
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
            f"[DAY][LLM] 후보={','.join(review.shortlisted_codes) or 'NONE'} "
            f"선택={selected} 승인={','.join(review.approved_codes) or 'NONE'} {summary}"
        )
        for path in review.chart_paths:
            self._notify_file(path, caption="[DAY][LLM][CHART]")
        return review.approved_codes, True

    def _apply_swing_chart_review(
        self,
        *,
        ranked_codes: list[str],
        candidates: Any,
        quotes: dict[str, Any],
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
            f"[SWING][LLM] 후보={','.join(review.shortlisted_codes) or 'NONE'} "
            f"선택={selected} 승인={','.join(review.approved_codes) or 'NONE'} {summary}"
        )
        for path in review.chart_paths:
            self._notify_file(path, caption="[SWING][LLM][CHART]")
        return review.approved_codes, True
