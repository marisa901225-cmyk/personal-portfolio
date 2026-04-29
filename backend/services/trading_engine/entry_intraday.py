from __future__ import annotations

from .intraday import passes_day_intraday_confirmation
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


__all__ = [
    "apply_day_intraday_confirmation",
    "passes_day_intraday_confirmation_for_code",
    "resolve_day_lock_retrace_gap_pct",
]
