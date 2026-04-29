from __future__ import annotations

from .day_stop_review import (
    is_day_overnight_carry_candidate,
    is_day_stop_review_candidate,
    review_day_overnight_carry_with_llm,
    review_day_stop_with_llm,
)
from .intraday import passes_day_intraday_confirmation
from .utils import parse_numeric


def should_hold_day_stop_after_llm(
    bot,
    *,
    code: str,
    pos,
    quote_price: float,
    pnl_pct: float,
    reason: str,
    now,
    logger,
    review_day_stop_with_llm_fn=review_day_stop_with_llm,
) -> bool:
    del now
    if reason != "SL" or pos.type != "T":
        return False

    review_key = day_stop_llm_review_key(code=code, pos=pos)
    already_reviewed = review_key in bot.state.day_stop_llm_reviewed_positions
    intraday_meta = day_stop_intraday_meta(bot, code=code, logger=logger)
    if not is_day_stop_review_candidate(
        config=bot.config,
        position=pos,
        pnl_pct=pnl_pct,
        intraday_meta=intraday_meta,
        already_reviewed=already_reviewed,
    ):
        return False

    bot.state.day_stop_llm_reviewed_positions.add(review_key)
    review = review_day_stop_with_llm_fn(
        code=code,
        position=pos,
        quote_price=quote_price,
        intraday_meta=intraday_meta,
        config=bot.config,
    )
    journal_day_stop_llm_review(
        bot,
        code=code,
        review=review,
        intraday_meta=intraday_meta,
    )
    return review is not None and review.decision == "HOLD"


def should_carry_day_force_exit(
    bot,
    *,
    code: str,
    pos,
    quote_price: float,
    reason: str,
    logger,
    review_day_overnight_carry_with_llm_fn=review_day_overnight_carry_with_llm,
) -> bool:
    if reason != "FORCE" or pos.type != "T":
        return False

    review_key = day_stop_llm_review_key(code=code, pos=pos)
    carried_date = bot.state.day_overnight_carry_positions.get(review_key)
    if carried_date == bot.state.trade_date:
        return True
    if carried_date:
        return False

    already_reviewed = review_key in bot.state.day_overnight_carry_reviewed_positions
    if not is_day_overnight_carry_candidate(
        config=bot.config,
        position=pos,
        quote_price=quote_price,
        trade_date=bot.state.trade_date,
        already_carried=already_reviewed,
    ):
        return False

    intraday_meta = day_stop_intraday_meta(bot, code=code, logger=logger)
    bot.state.day_overnight_carry_reviewed_positions.add(review_key)
    review = review_day_overnight_carry_with_llm_fn(
        code=code,
        position=pos,
        quote_price=quote_price,
        intraday_meta=intraday_meta,
        config=bot.config,
    )
    journal_day_overnight_carry_review(
        bot,
        code=code,
        review=review,
        intraday_meta=intraday_meta,
    )
    if review is None or review.decision != "CARRY":
        return False

    bot.state.day_overnight_carry_positions[review_key] = bot.state.trade_date
    return True


def day_stop_intraday_meta(bot, *, code: str, logger) -> dict[str, object]:
    try:
        _, meta = passes_day_intraday_confirmation(
            bot.api,
            trade_date=bot.state.trade_date,
            code=code,
            config=bot.config,
            logger=logger,
        )
        return dict(meta)
    except Exception:
        logger.warning("day stop intraday meta failed code=%s", code, exc_info=True)
        return {"reason": "FETCH_FAILED"}


def resolve_day_stop_loss_pct(bot, *, code: str, logger) -> float | None:
    multiplier = max(
        0.0,
        float(getattr(bot.config, "day_stop_loss_volatility_multiplier", 0.0)),
    )
    if multiplier <= 0:
        return None

    meta = day_stop_intraday_meta(bot, code=code, logger=logger)
    recent_range_pct = parse_numeric(meta.get("recent_range_pct"))
    if recent_range_pct is None or recent_range_pct <= 0:
        return None

    base_stop_abs = abs(float(bot.config.day_stop_loss_pct))
    max_stop_abs = max(
        base_stop_abs,
        abs(float(getattr(bot.config, "day_stop_loss_max_pct", bot.config.day_stop_loss_pct))),
    )
    if max_stop_abs <= 0:
        return None

    adaptive_stop_abs = (float(recent_range_pct) / 100.0) * multiplier
    stop_abs = min(max(base_stop_abs, adaptive_stop_abs), max_stop_abs)
    return -stop_abs


def journal_day_stop_llm_review(
    bot,
    *,
    code: str,
    review,
    intraday_meta: dict[str, object],
) -> None:
    decision = review.decision if review is not None else "EXIT"
    bot._journal(
        "DAY_STOP_LLM_REVIEW",
        asof_date=bot.state.trade_date,
        code=code,
        decision=decision,
        confidence=round(float(review.confidence), 4) if review is not None else 0.0,
        route=review.route if review is not None else "unavailable",
        review_reason=review.reason if review is not None else "LLM_UNAVAILABLE_OR_INVALID",
        intraday_reason=str(intraday_meta.get("reason") or ""),
        day_change_pct=intraday_meta.get("day_change_pct"),
        window_change_pct=intraday_meta.get("window_change_pct"),
        last_bar_change_pct=intraday_meta.get("last_bar_change_pct"),
        retrace_from_high_pct=intraday_meta.get("retrace_from_high_pct"),
    )


def journal_day_overnight_carry_review(
    bot,
    *,
    code: str,
    review,
    intraday_meta: dict[str, object],
) -> None:
    decision = review.decision if review is not None else "EXIT"
    bot._journal(
        "DAY_OVERNIGHT_CARRY_REVIEW",
        asof_date=bot.state.trade_date,
        code=code,
        decision=decision,
        confidence=round(float(review.confidence), 4) if review is not None else 0.0,
        route=review.route if review is not None else "unavailable",
        review_reason=review.reason if review is not None else "LLM_UNAVAILABLE_OR_INVALID",
        intraday_reason=str(intraday_meta.get("reason") or ""),
        day_change_pct=intraday_meta.get("day_change_pct"),
        window_change_pct=intraday_meta.get("window_change_pct"),
        last_bar_change_pct=intraday_meta.get("last_bar_change_pct"),
        retrace_from_high_pct=intraday_meta.get("retrace_from_high_pct"),
    )


def day_stop_llm_review_key(*, code: str, pos) -> str:
    return f"{str(code).strip()}:{str(getattr(pos, 'entry_time', '')).strip()}"


__all__ = [
    "day_stop_intraday_meta",
    "day_stop_llm_review_key",
    "journal_day_overnight_carry_review",
    "journal_day_stop_llm_review",
    "resolve_day_stop_loss_pct",
    "should_carry_day_force_exit",
    "should_hold_day_stop_after_llm",
]
