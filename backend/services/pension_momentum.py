from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
import logging
from math import sqrt
from statistics import pstdev
from typing import Protocol

from backend.services.prompt_loader import load_prompt
from backend.services.trading_engine.day_chart_review import (
    CHART_REVIEW_RESPONSE_FORMAT,
    parse_review_response,
)

from .pension_rebalancing import pct_return


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PensionMomentumCandidate:
    code: str
    name: str
    score: float
    eligible: bool
    current_price: int
    daily_ma20: float
    daily_ma60: float
    weekly_ma10: float
    weekly_ma20: float
    return_13w_pct: float
    return_26w_pct: float
    drawdown_26w_pct: float
    volatility_20d_pct: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class PensionMomentumReview:
    selected_code: str
    approved_codes: list[str]
    summary: str
    route: str


class _LLMSettings(Protocol):
    def is_paid_configured(self) -> bool: ...

    def is_remote_configured(self) -> bool: ...


class PensionMomentumReviewer(Protocol):
    settings: _LLMSettings

    def generate_paid_chat(self, messages: list[dict], **kwargs: object) -> str: ...

    def generate_chat(self, messages: list[dict], **kwargs: object) -> str: ...


def _normalized_prices(daily_prices: list[tuple[str, int]]) -> list[tuple[str, int]]:
    by_date: dict[str, int] = {}
    for raw_date, raw_price in daily_prices:
        date_key = "".join(character for character in str(raw_date) if character.isdigit())[:8]
        price = int(raw_price)
        if len(date_key) == 8 and price > 0:
            by_date[date_key] = price
    return sorted(by_date.items())


def _weekly_closes(prices: list[tuple[str, int]]) -> list[int]:
    by_week: dict[tuple[int, int], int] = {}
    for date_key, price in prices:
        parsed = datetime.strptime(date_key, "%Y%m%d").date()
        iso_year, iso_week, _ = parsed.isocalendar()
        by_week[(iso_year, iso_week)] = price
    return [by_week[key] for key in sorted(by_week)]


def _mean(values: list[int]) -> float:
    return sum(values) / len(values) if values else 0.0


def _period_return(values: list[int], periods: int) -> float:
    if len(values) <= periods:
        return 0.0
    return pct_return(float(values[-periods - 1]), float(values[-1]))


def _annualized_volatility(values: list[int], periods: int = 20) -> float:
    sample = values[-(periods + 1) :]
    if len(sample) < 2:
        return 0.0
    returns = [(current / previous) - 1.0 for previous, current in zip(sample, sample[1:]) if previous > 0]
    return pstdev(returns) * sqrt(252.0) * 100.0 if len(returns) >= 2 else 0.0


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def analyze_pension_momentum_candidate(
    *,
    code: str,
    name: str,
    daily_prices: list[tuple[str, int]],
) -> PensionMomentumCandidate:
    prices = _normalized_prices(daily_prices)
    closes = [price for _, price in prices]
    weekly = _weekly_closes(prices)
    if len(closes) < 60 or len(weekly) < 20:
        return PensionMomentumCandidate(
            code=code,
            name=name,
            score=-100.0,
            eligible=False,
            current_price=closes[-1] if closes else 0,
            daily_ma20=_mean(closes[-20:]),
            daily_ma60=_mean(closes[-60:]),
            weekly_ma10=_mean(weekly[-10:]),
            weekly_ma20=_mean(weekly[-20:]),
            return_13w_pct=_period_return(weekly, 13),
            return_26w_pct=_period_return(weekly, 26),
            drawdown_26w_pct=0.0,
            volatility_20d_pct=_annualized_volatility(closes),
            reasons=("INSUFFICIENT_HISTORY",),
        )

    current_price = closes[-1]
    daily_ma20 = _mean(closes[-20:])
    daily_ma60 = _mean(closes[-60:])
    weekly_ma10 = _mean(weekly[-10:])
    weekly_ma20 = _mean(weekly[-20:])
    return_13w_pct = _period_return(weekly, 13)
    return_26w_pct = _period_return(weekly, 26)
    recent_high = max(weekly[-26:])
    drawdown_26w_pct = pct_return(float(recent_high), float(current_price))
    volatility_20d_pct = _annualized_volatility(closes)

    reasons: list[str] = []
    if current_price <= weekly_ma20:
        reasons.append("BELOW_WEEKLY_MA20")
    if weekly_ma10 <= weekly_ma20:
        reasons.append("WEEKLY_TREND_BROKEN")
    if return_13w_pct < -5.0:
        reasons.append("WEAK_13W_MOMENTUM")
    if drawdown_26w_pct <= -18.0:
        reasons.append("DEEP_26W_DRAWDOWN")
    if volatility_20d_pct > 70.0:
        reasons.append("EXCESSIVE_VOLATILITY")

    score = 0.0
    score += 25.0 if current_price > weekly_ma20 else -25.0
    score += 20.0 if weekly_ma10 > weekly_ma20 else -20.0
    score += 10.0 if current_price > daily_ma20 else -10.0
    score += 10.0 if daily_ma20 > daily_ma60 else -10.0
    score += _clamp(return_13w_pct, -20.0, 30.0) * 0.8
    score += _clamp(return_26w_pct, -30.0, 50.0) * 0.4
    score -= min(12.0, max(0.0, volatility_20d_pct - 25.0) * 0.4)
    score -= min(12.0, max(0.0, abs(drawdown_26w_pct) - 8.0) * 0.5)

    return PensionMomentumCandidate(
        code=code,
        name=name,
        score=round(score, 4),
        eligible=not reasons,
        current_price=current_price,
        daily_ma20=daily_ma20,
        daily_ma60=daily_ma60,
        weekly_ma10=weekly_ma10,
        weekly_ma20=weekly_ma20,
        return_13w_pct=return_13w_pct,
        return_26w_pct=return_26w_pct,
        drawdown_26w_pct=drawdown_26w_pct,
        volatility_20d_pct=volatility_20d_pct,
        reasons=tuple(reasons),
    )


def rank_pension_momentum_candidates(
    candidates: list[PensionMomentumCandidate],
) -> list[PensionMomentumCandidate]:
    return sorted(candidates, key=lambda candidate: (candidate.eligible, candidate.score), reverse=True)


def _review_messages(candidates: list[PensionMomentumCandidate]) -> list[dict]:
    payload = {
        "task": "연금 성장주 모멘텀 최종 검토",
        "rules": {
            "candidate_discovery": "forbidden",
            "weight_decision": "forbidden",
            "allowed_decisions": ["ENTER", "UNSURE", "PASS"],
        },
        "candidates": [asdict(candidate) for candidate in candidates],
    }
    return [
        {"role": "system", "content": load_prompt("pension_momentum_review_system")},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def review_pension_momentum_candidates(
    candidates: list[PensionMomentumCandidate],
    *,
    llm: PensionMomentumReviewer | None = None,
    model: str = "gpt-5.5",
    reasoning_effort: str = "low",
) -> PensionMomentumReview:
    shortlist = [candidate for candidate in rank_pension_momentum_candidates(candidates) if candidate.eligible][:3]
    if not shortlist:
        return PensionMomentumReview(
            "",
            [],
            "정량 장기추세 기준을 통과한 성장주 후보가 없습니다.",
            "no_eligible",
        )

    if llm is None:
        from backend.services.llm.service import LLMService

        llm = LLMService.get_instance()

    messages = _review_messages(shortlist)
    if llm.settings.is_paid_configured():
        raw = llm.generate_paid_chat(
            messages,
            max_tokens=700,
            temperature=0.1,
            model=model,
            reasoning_effort=reasoning_effort,
            response_format=CHART_REVIEW_RESPONSE_FORMAT,
        )
        route = "paid"
    elif llm.settings.is_remote_configured():
        raw = llm.generate_chat(
            messages,
            max_tokens=700,
            temperature=0.1,
            allow_paid_fallback=False,
            response_format=CHART_REVIEW_RESPONSE_FORMAT,
        )
        route = "local"
    else:
        return PensionMomentumReview("", [], "AI 검토 백엔드가 설정되지 않았습니다.", "no_backend")

    parsed = parse_review_response(raw)
    if not parsed:
        logger.warning("pension momentum AI review parse failed raw=%s", (raw or "")[:400])
        return PensionMomentumReview(
            "",
            [],
            "AI 검토 응답을 해석하지 못했습니다.",
            f"{route}_parse_failed",
        )

    shortlist_codes = {candidate.code for candidate in shortlist}
    approved_codes: list[str] = []
    decisions = parsed.get("candidates") or []
    if isinstance(decisions, list):
        for decision in decisions:
            if not isinstance(decision, dict):
                continue
            code = str(decision.get("code") or "").strip()
            verdict = str(decision.get("decision") or "").strip().upper()
            if code in shortlist_codes and verdict in {"ENTER", "UNSURE"}:
                approved_codes.append(code)

    selected_code = str(parsed.get("selected_code") or "").strip()
    if selected_code not in approved_codes:
        selected_code = ""
    summary = str(parsed.get("summary") or "").strip()
    return PensionMomentumReview(selected_code, approved_codes, summary, route)


__all__ = [
    "PensionMomentumCandidate",
    "PensionMomentumReview",
    "analyze_pension_momentum_candidate",
    "rank_pension_momentum_candidates",
    "review_pension_momentum_candidates",
]
