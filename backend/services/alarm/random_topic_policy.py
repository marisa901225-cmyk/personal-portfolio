from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Callable, Optional

import holidays

from ..llm_service import LLMService

logger = logging.getLogger(__name__)

_DEFAULT_SESSION_TOKENS_THRESHOLD = 40_000


def _random_topic_session_state_path() -> str:
    default_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "random_topic_llm_session_state.json"))
    return os.getenv("RANDOM_TOPIC_LLM_SESSION_STATE_FILE", default_path)


def _load_random_topic_session_state() -> dict:
    path = _random_topic_session_state_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except FileNotFoundError:
        return {}
    except Exception as exc:
        logger.warning("Failed to load random topic LLM session state: %s", exc)
    return {}


def _write_random_topic_session_state(state: dict) -> None:
    path = _random_topic_session_state_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.warning("Failed to write random topic LLM session state: %s", exc)


def _session_tokens_threshold() -> int:
    raw = os.getenv("RANDOM_TOPIC_LLM_RESET_THRESHOLD_TOKENS", str(_DEFAULT_SESSION_TOKENS_THRESHOLD)).strip()
    try:
        threshold = int(raw)
    except ValueError:
        return _DEFAULT_SESSION_TOKENS_THRESHOLD
    return max(1, threshold)


def _extract_session_tokens(metrics: object) -> Optional[int]:
    if isinstance(metrics, (int, float)):
        return max(0, int(metrics))
    if not isinstance(metrics, dict):
        return None

    for key in ("context_tokens", "total_tokens", "prompt_tokens"):
        value = metrics.get(key)
        if isinstance(value, (int, float)):
            return max(0, int(value))
    return None


def _hourly_reset_llm_context(
    now: datetime,
    *,
    llm_service_cls=LLMService,
) -> None:
    state = _load_random_topic_session_state()
    session_tokens = _extract_session_tokens(state)
    threshold = _session_tokens_threshold()

    if session_tokens is None or session_tokens < threshold:
        return

    reset_ok = bool(llm_service_cls.get_instance().reset_context())
    if not reset_ok:
        logger.warning(
            "Random topic LLM reset skipped after threshold hit: session_tokens=%s threshold=%s",
            session_tokens,
            threshold,
        )
        return

    reset_count = int(state.get("reset_count", 0) or 0) + 1
    _write_random_topic_session_state(
        {
            "context_tokens": 0,
            "total_tokens": 0,
            "updated_at": now.isoformat(timespec="seconds"),
            "last_reset_at": now.isoformat(timespec="seconds"),
            "last_reset_reason": f"threshold:{threshold}",
            "reset_count": reset_count,
        }
    )
    logger.info("Random topic LLM context reset performed at %s tokens (threshold=%s).", session_tokens, threshold)


def record_random_topic_llm_usage(metrics: object, *, now: Optional[datetime] = None) -> None:
    session_tokens = _extract_session_tokens(metrics)
    if session_tokens is None:
        return

    base_now = now or datetime.now()
    state = _load_random_topic_session_state()
    prev_context_tokens = _extract_session_tokens(state) or 0
    prev_total_tokens = 0
    if isinstance(state, dict) and isinstance(state.get("total_tokens"), (int, float)):
        prev_total_tokens = max(0, int(state["total_tokens"]))
    current_total_tokens = int(metrics.get("total_tokens", 0)) if isinstance(metrics, dict) and isinstance(metrics.get("total_tokens"), (int, float)) else session_tokens
    next_state = {
        "context_tokens": max(prev_context_tokens, session_tokens),
        "total_tokens": max(prev_total_tokens, current_total_tokens),
        "updated_at": base_now.isoformat(timespec="seconds"),
        "last_reset_at": state.get("last_reset_at"),
        "last_reset_reason": state.get("last_reset_reason"),
        "reset_count": int(state.get("reset_count", 0) or 0),
    }
    _write_random_topic_session_state(next_state)


@lru_cache(maxsize=8)
def _kr_holidays_for_year(year: int):
    return holidays.country_holidays("KR", years=[year])


def _is_kr_public_holiday(now: datetime) -> bool:
    return now.date() in _kr_holidays_for_year(now.year)


def _should_send_random_topic(
    now: datetime,
    *,
    load_last_random_topic_sent_at: Callable[[], Optional[datetime]],
    min_gap_minutes: int = 12,
) -> bool:
    if now.weekday() >= 5:
        return False
    if _is_kr_public_holiday(now):
        return False
    if now.hour > 18 or (now.hour == 18 and now.minute > 0):
        return False
    if now.minute % 10 == 0:
        return True
    last_sent = load_last_random_topic_sent_at()
    return bool(last_sent and (now - last_sent) >= timedelta(minutes=min_gap_minutes))
