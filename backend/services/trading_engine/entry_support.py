from __future__ import annotations

from .intraday import passes_day_intraday_confirmation
from .notification_text import format_candidate_review_message
from .utils import parse_numeric


def apply_day_intraday_confirmation(bot, ranked_codes: list[str], *, logger) -> list[str]:
    if not ranked_codes or not bot.config.day_use_intraday_confirmation:
        return ranked_codes

    filtered_codes: list[str] = []
    for code in ranked_codes:
        ok, meta = passes_day_intraday_confirmation_for_code(bot, code=code, logger=logger)
        if ok:
            filtered_codes.append(code)
            continue

        bot._journal(
            "DAY_CANDIDATE_FILTERED",
            asof_date=bot.state.trade_date,
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


def passes_day_intraday_confirmation_for_code(bot, *, code: str, logger) -> tuple[bool, dict[str, object]]:
    return passes_day_intraday_confirmation(
        bot.api,
        trade_date=bot.state.trade_date,
        code=code,
        config=bot.config,
        logger=logger,
    )


def resolve_day_lock_retrace_gap_pct(bot, *, code: str, logger) -> float | None:
    multiplier = max(0.0, float(getattr(bot.config, "day_lock_volatility_gap_multiplier", 0.0)))
    if multiplier <= 0:
        return None

    _, meta = passes_day_intraday_confirmation_for_code(bot, code=code, logger=logger)
    recent_range_pct = parse_numeric(meta.get("recent_range_pct"))
    if recent_range_pct is None or recent_range_pct <= 0:
        return None

    adaptive_gap_pct = (float(recent_range_pct) / 100.0) * multiplier
    return max(float(bot.config.day_lock_retrace_gap_pct), adaptive_gap_pct)


def apply_day_chart_review(
    bot,
    *,
    ranked_codes: list[str],
    candidates,
    quotes,
    review_fn,
) -> tuple[list[str], bool]:
    if not ranked_codes or not bot.config.day_chart_review_enabled:
        return ranked_codes, False

    review = review_fn(
        api=bot.api,
        trade_date=bot.state.trade_date,
        ranked_codes=ranked_codes,
        candidates=candidates,
        quotes=quotes,
        config=bot.config,
        output_dir=bot.config.output_dir,
    )
    if review is None:
        return ranked_codes, False

    bot._journal(
        "DAY_CHART_REVIEW",
        asof_date=bot.state.trade_date,
        shortlisted_codes=",".join(review.shortlisted_codes),
        approved_codes=",".join(review.approved_codes),
        selected_code=review.selected_code,
        summary=review.summary,
    )
    summary = review.summary or "차트 구조 기준으로 shortlist 재검토 완료"
    selected = review.selected_code or (review.approved_codes[0] if review.approved_codes else "NONE")
    bot._notify_text(
        format_candidate_review_message(
            strategy="DAY",
            shortlisted_codes=review.shortlisted_codes,
            selected_code=selected,
            approved_codes=review.approved_codes,
            summary=summary,
        )
    )
    for path in review.chart_paths:
        bot._notify_file(path, caption="[단타][LLM][차트]")
    return review.approved_codes, True


def apply_swing_chart_review(
    bot,
    *,
    ranked_codes: list[str],
    candidates,
    quotes,
    review_fn,
) -> tuple[list[str], bool]:
    if not ranked_codes or not bot.config.swing_chart_review_enabled:
        return ranked_codes, False
    if any(position.type == "S" for position in bot.state.open_positions.values()):
        return ranked_codes, False

    review = review_fn(
        api=bot.api,
        trade_date=bot.state.trade_date,
        ranked_codes=ranked_codes,
        candidates=candidates,
        quotes=quotes,
        config=bot.config,
        output_dir=bot.config.output_dir,
    )
    if review is None:
        return ranked_codes, False

    bot._journal(
        "SWING_CHART_REVIEW",
        asof_date=bot.state.trade_date,
        shortlisted_codes=",".join(review.shortlisted_codes),
        approved_codes=",".join(review.approved_codes),
        selected_code=review.selected_code,
        summary=review.summary,
    )
    summary = review.summary or "차트 구조 기준으로 swing shortlist 재검토 완료"
    selected = review.selected_code or (review.approved_codes[0] if review.approved_codes else "NONE")
    bot._notify_text(
        format_candidate_review_message(
            strategy="SWING",
            shortlisted_codes=review.shortlisted_codes,
            selected_code=selected,
            approved_codes=review.approved_codes,
            summary=summary,
        )
    )
    for path in review.chart_paths:
        bot._notify_file(path, caption="[스윙][LLM][차트]")
    return review.approved_codes, True
