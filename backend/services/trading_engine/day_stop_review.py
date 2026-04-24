from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Literal

from ..llm.service import LLMService
from .config import TradeEngineConfig
from .state import PositionState
from .utils import parse_numeric

logger = logging.getLogger(__name__)

DayStopDecision = Literal["EXIT", "HOLD"]

_DAY_STOP_REVIEW_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "day_stop_review",
        "schema": {
            "type": "object",
            "properties": {
                "decision": {"type": "string", "enum": ["EXIT", "HOLD"]},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "reason": {"type": "string", "maxLength": 240},
            },
            "required": ["decision", "confidence", "reason"],
            "additionalProperties": False,
        },
    },
}


@dataclass(slots=True)
class DayStopReviewResult:
    decision: DayStopDecision
    confidence: float
    reason: str
    route: str
    raw_response: dict[str, object]


def is_day_stop_review_candidate(
    *,
    config: TradeEngineConfig,
    position: PositionState,
    pnl_pct: float,
    intraday_meta: dict[str, object],
    already_reviewed: bool,
) -> bool:
    if not bool(getattr(config, "day_stop_llm_review_enabled", False)):
        return False
    if already_reviewed or position.type != "T":
        return False
    if pnl_pct <= float(getattr(config, "day_stop_llm_hard_stop_pct", -0.022)):
        return False

    day_change_pct = parse_numeric(intraday_meta.get("day_change_pct"))
    if day_change_pct is None:
        return False
    if day_change_pct < float(getattr(config, "day_stop_llm_min_day_change_pct", 12.0)):
        return False

    retrace_from_high_pct = parse_numeric(intraday_meta.get("retrace_from_high_pct"))
    if retrace_from_high_pct is not None and retrace_from_high_pct < float(
        getattr(config, "day_stop_llm_max_retrace_from_high_pct", -3.0)
    ):
        return False

    return True


def review_day_stop_with_llm(
    *,
    code: str,
    position: PositionState,
    quote_price: float,
    intraday_meta: dict[str, object],
    config: TradeEngineConfig,
) -> DayStopReviewResult | None:
    """Ask the configured LLM whether a day-trade stop looks like a pullback hold."""
    llm = LLMService.get_instance()
    if not _has_llm_backend(llm):
        return None

    messages = _build_messages(
        code=code,
        position=position,
        quote_price=quote_price,
        intraday_meta=intraday_meta,
        config=config,
    )

    try:
        if bool(getattr(config, "day_stop_llm_review_use_paid", False)) and _paid_available(llm):
            raw = llm.generate_paid_chat(
                messages,
                max_tokens=220,
                temperature=0.0,
                model=getattr(config, "day_stop_llm_review_model", None),
                reasoning_effort=getattr(config, "day_stop_llm_review_reasoning_effort", "low"),
                response_format=_DAY_STOP_REVIEW_RESPONSE_FORMAT,
            )
        else:
            raw = llm.generate_chat(
                messages,
                max_tokens=220,
                temperature=0.0,
                response_format=_DAY_STOP_REVIEW_RESPONSE_FORMAT,
                allow_paid_fallback=False,
            )
    except Exception:
        logger.warning("day stop LLM review failed code=%s", code, exc_info=True)
        return None

    parsed = _parse_review_response(raw)
    if not parsed:
        logger.warning("day stop LLM review parse failed code=%s raw=%s", code, (raw or "")[:400])
        return None

    decision = str(parsed.get("decision") or "").strip().upper()
    if decision not in {"EXIT", "HOLD"}:
        return None

    confidence = parse_numeric(parsed.get("confidence"))
    confidence = max(0.0, min(1.0, float(confidence if confidence is not None else 0.0)))
    min_hold_confidence = float(getattr(config, "day_stop_llm_hold_confidence_min", 0.55))
    if decision == "HOLD" and confidence < min_hold_confidence:
        decision = "EXIT"

    route = str(getattr(llm, "_last_route", None) or "unknown")
    return DayStopReviewResult(
        decision=decision,  # type: ignore[arg-type]
        confidence=confidence,
        reason=str(parsed.get("reason") or "").strip()[:240],
        route=route,
        raw_response=dict(parsed),
    )


def _build_messages(
    *,
    code: str,
    position: PositionState,
    quote_price: float,
    intraday_meta: dict[str, object],
    config: TradeEngineConfig,
) -> list[dict[str, str]]:
    payload = {
        "code": code,
        "strategy": position.type,
        "entry_price": round(float(position.entry_price), 4),
        "highest_price": round(float(position.highest_price or position.entry_price), 4),
        "current_price": round(float(quote_price), 4),
        "stop_loss_pct": round(float(config.day_stop_loss_pct) * 100.0, 4),
        "hard_stop_pct": round(float(config.day_stop_llm_hard_stop_pct) * 100.0, 4),
        "intraday": {
            key: intraday_meta.get(key)
            for key in (
                "reason",
                "day_change_pct",
                "window_change_pct",
                "last_bar_change_pct",
                "retrace_from_high_pct",
                "recent_range_pct",
                "bars",
            )
            if key in intraday_meta
        },
    }
    system = (
        "You are a Korean intraday trading risk guard. Decide whether a triggered day-trade stop "
        "is a fast-rising stock pullback worth holding for one more monitor cycle. "
        "Return HOLD only when the pullback is shallow, momentum is still constructive, and the "
        "risk/reward of immediate selling is poor. If uncertain, choose EXIT."
    )
    user = (
        "단타 손절선이 닿았습니다. 급등주 눌림목으로 1회 보류할지 판단하세요.\n"
        "규칙: HOLD는 한 번만 허용됩니다. 애매하거나 데이터가 약하면 EXIT입니다.\n"
        f"데이터:\n{json.dumps(payload, ensure_ascii=False, sort_keys=True)}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _has_llm_backend(llm: LLMService) -> bool:
    settings = getattr(llm, "settings", None)
    if settings is None:
        return False
    return bool(
        (hasattr(settings, "is_remote_configured") and settings.is_remote_configured())
        or _paid_available(llm)
    )


def _paid_available(llm: LLMService) -> bool:
    settings = getattr(llm, "settings", None)
    return bool(
        getattr(llm, "paid_backend", None)
        and settings is not None
        and hasattr(settings, "is_paid_configured")
        and settings.is_paid_configured()
    )


def _parse_review_response(raw: str | None) -> dict[str, object] | None:
    if not raw:
        return None
    text = str(raw).strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None
