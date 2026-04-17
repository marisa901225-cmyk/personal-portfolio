from __future__ import annotations

import logging
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Callable, Optional

import holidays

from ..llm_service import LLMService

logger = logging.getLogger(__name__)


def _hourly_reset_llm_context(
    now: datetime,
    *,
    llm_service_cls=LLMService,
) -> None:
    if now.minute == 0:
        llm_service_cls.get_instance().reset_context()
        logger.info("Hourly LLM context reset performed.")


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
