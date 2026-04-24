from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import pandas as pd

from .candidate_notifications import (
    maybe_build_candidate_notifications,
    maybe_build_swing_skip_notification,
)
from .notification_text import format_chart_review_skip_message

if TYPE_CHECKING:
    from .strategy import Candidates


class BotNotificationsMixin:
    def _notify_text(self, msg: str) -> None:
        self.notifier.enqueue_text(msg)

    def _notify_file(self, path: str, caption: str | None = None) -> None:
        self.notifier.enqueue_file(path, caption=caption)

    def _notify_chart_review_skip(
        self,
        *,
        strategy_label: str,
        reason: str,
        code: str | None = None,
    ) -> None:
        self._notify_text(
            format_chart_review_skip_message(
                strategy=strategy_label,
                reason=reason,
                code=code,
            )
        )

    def _maybe_notify_candidates(
        self,
        now: datetime,
        candidates: Candidates,
        regime: str,
        display_candidates: pd.DataFrame | None = None,
    ) -> None:
        updated_idx, messages = maybe_build_candidate_notifications(
            now=now,
            candidates=candidates,
            regime=regime,
            config=self.config,
            last_notified_window_idx=self._last_notified_window_idx,
            display_candidates=display_candidates,
        )
        self._last_notified_window_idx = updated_idx
        for message in messages:
            self._notify_text(message)

    def _build_notification_candidates(self, *, candidates: Candidates | None, ranked_codes: list[str]) -> pd.DataFrame:
        if not ranked_codes or candidates is None:
            return pd.DataFrame()

        popular = getattr(candidates, "popular", None)
        if popular is None or getattr(popular, "empty", True):
            return pd.DataFrame()

        pool = popular.copy()
        if "code" not in pool.columns:
            return pd.DataFrame()

        ordered_frames: list[pd.DataFrame] = []
        seen: set[str] = set()
        for code in ranked_codes:
            code_str = str(code)
            if not code_str or code_str in seen:
                continue
            rows = pool[pool["code"].astype(str) == code_str]
            if rows.empty:
                continue
            ordered_frames.append(rows.head(1))
            seen.add(code_str)

        if not ordered_frames:
            return pd.DataFrame()
        return pd.concat(ordered_frames, ignore_index=True)

    def _maybe_notify_swing_skip(
        self,
        *,
        now: datetime,
        regime: str,
        reason: str,
        candidates: Candidates,
    ) -> None:
        if any(position.type == "S" for position in self.state.open_positions.values()):
            return

        updated_idx, message = maybe_build_swing_skip_notification(
            now=now,
            trade_date=self.state.trade_date,
            regime=regime,
            config=self.config,
            last_notified_window_idx=self._last_swing_skip_notified_window_idx,
            reason=reason,
            model_count=len(candidates.model),
            etf_count=len(candidates.etf),
        )
        self._last_swing_skip_notified_window_idx = updated_idx
        if message:
            self._notify_text(message)

    def _reset_intraday_notification_state(self, trade_date: str) -> None:
        if self._last_notification_trade_date == trade_date:
            return
        self._last_notification_trade_date = trade_date
        self._last_notified_window_idx = None
        self._last_swing_skip_notified_window_idx = None
