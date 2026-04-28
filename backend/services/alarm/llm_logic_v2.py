# backend/services/alarm/llm_logic_v2.py
"""Refactored v2 of alarm LLM logic with the same public API."""

from __future__ import annotations

import logging
import random
from datetime import datetime
from typing import Dict, List, Optional

from .alarm_summary_service import _AlarmSummaryDeps, _generate_alarm_summary_async as _generate_alarm_summary_async_impl
from .expense_summary_service import summarize_expenses_with_llm as _summarize_expenses_with_llm_impl
from .llm_refiner import (
    STOP_TOKENS,
    clean_meta_headers,
    dump_llm_draft,
    generate_with_main_llm_async,
    refine_draft_with_light_llm_async,
)
from .llm_runtime import (
    _LLMRunOptions,
    _build_stop_tokens,
    _compact_reason,
    _postprocess_llm_text,
    _resolve_llm_options,
)
from .notification_formatter import _build_notification_list
from .random_categories import (
    get_all_categories,
    get_category_keywords,
    get_formats,
    get_openers,
    get_twists,
    get_voices,
    has_category_anchor,
    load_last_random_topic_sent_at,
    load_recent_categories,
    pick_keywords_for_constraints,
    save_last_random_topic_sent_at,
    save_recent_category,
)
from .random_topic_policy import (
    _hourly_reset_llm_context as _hourly_reset_llm_context_impl,
    record_random_topic_llm_usage as _record_random_topic_llm_usage_impl,
    _should_send_random_topic as _should_send_random_topic_impl,
)
from .random_topic_service import (
    _RandomMessagePayload,
    _RandomTopicDeps,
    _RandomTopicPlan,
    _default_random_title,
    _generate_random_message_payload_async as _generate_random_message_payload_async_impl,
)
from .sanitizer import get_korean_ratio, sanitize_llm_output
from ..llm_service import LLMService
from ..prompt_loader import load_prompt

logger = logging.getLogger(__name__)


def _hourly_reset_llm_context(now: datetime) -> None:
    _hourly_reset_llm_context_impl(now, llm_service_cls=LLMService)


def _should_send_random_topic(now: datetime) -> bool:
    return _should_send_random_topic_impl(
        now,
        load_last_random_topic_sent_at=load_last_random_topic_sent_at,
    )


def _make_random_topic_deps() -> _RandomTopicDeps:
    def _record_main_llm_usage_tokens() -> None:
        metrics = getattr(LLMService.get_instance(), "consume_last_remote_token_metrics", lambda: None)()
        _record_random_topic_llm_usage_impl(metrics)

    return _RandomTopicDeps(
        get_all_categories=get_all_categories,
        get_formats=get_formats,
        get_openers=get_openers,
        get_twists=get_twists,
        get_voices=get_voices,
        has_category_anchor=has_category_anchor,
        load_last_random_topic_sent_at=load_last_random_topic_sent_at,
        load_recent_categories=load_recent_categories,
        pick_keywords_for_constraints=pick_keywords_for_constraints,
        save_last_random_topic_sent_at=save_last_random_topic_sent_at,
        save_recent_category=save_recent_category,
        get_category_keywords=get_category_keywords,
        load_prompt=load_prompt,
        get_korean_ratio=get_korean_ratio,
        dump_llm_draft=dump_llm_draft,
        generate_with_main_llm_async=generate_with_main_llm_async,
        refine_draft_with_light_llm_async=refine_draft_with_light_llm_async,
        resolve_llm_options=_resolve_llm_options,
        build_stop_tokens=_build_stop_tokens,
        postprocess_llm_text=_postprocess_llm_text,
        compact_reason=_compact_reason,
        hourly_reset_llm_context=_hourly_reset_llm_context,
        record_main_llm_usage_tokens=_record_main_llm_usage_tokens,
        last_used_paid=lambda: bool(LLMService.get_instance().last_used_paid()),
        random_module=random,
    )


def _make_alarm_summary_deps() -> _AlarmSummaryDeps:
    return _AlarmSummaryDeps(
        build_stop_tokens=_build_stop_tokens,
        resolve_llm_options=_resolve_llm_options,
        generate_with_main_llm_async=generate_with_main_llm_async,
        dump_llm_draft=dump_llm_draft,
        sanitize_llm_output=sanitize_llm_output,
        postprocess_llm_text=_postprocess_llm_text,
        get_korean_ratio=get_korean_ratio,
    )


async def _generate_random_message_payload_async(
    now: datetime,
    model: Optional[str] = None,
    **llm_kwargs,
) -> Optional[_RandomMessagePayload]:
    return await _generate_random_message_payload_async_impl(
        now,
        deps=_make_random_topic_deps(),
        model=model,
        **llm_kwargs,
    )


async def _generate_random_message_async(
    now: datetime,
    model: Optional[str] = None,
    **llm_kwargs,
) -> Optional[str]:
    payload = await _generate_random_message_payload_async(now, model=model, **llm_kwargs)
    return payload.body if payload else None


async def _generate_alarm_summary_async(
    items: List[dict],
    prompt_content: str,
    model: Optional[str] = None,
    **llm_kwargs,
) -> Optional[str]:
    return await _generate_alarm_summary_async_impl(
        items,
        prompt_content,
        deps=_make_alarm_summary_deps(),
        model=model,
        **llm_kwargs,
    )


async def summarize_with_llm(items: List[dict], model: Optional[str] = None, **llm_kwargs) -> Optional[str]:
    llm_service = LLMService.get_instance()
    if not llm_service.is_loaded():
        if not items:
            return None
        notification_list = _build_notification_list(items)
        return "\n".join(notification_list) if notification_list else None

    if not items:
        now = datetime.now()
        if not _should_send_random_topic(now):
            return None
        return await _generate_random_message_async(now, model=model, **llm_kwargs)

    notification_list = _build_notification_list(items)
    if not notification_list:
        return None

    notifications_str = "\n".join(notification_list)
    prompt_content = load_prompt("alarm_summary", notifications=notifications_str) or f"알림 요약:\n{notifications_str}"
    return await _generate_alarm_summary_async(items, prompt_content, model=model, **llm_kwargs)


async def generate_random_message_payload(
    now: Optional[datetime] = None,
    model: Optional[str] = None,
    **llm_kwargs,
) -> Optional[Dict[str, str]]:
    llm_service = LLMService.get_instance()
    if not llm_service.is_loaded():
        return None

    base_now = now or datetime.now()
    if not _should_send_random_topic(base_now):
        return None

    payload = await _generate_random_message_payload_async(base_now, model=model, **llm_kwargs)
    if not payload:
        return None
    return {"title": payload.title, "body": payload.body}


async def summarize_expenses_with_llm(expenses: List[dict]) -> str:
    return await _summarize_expenses_with_llm_impl(
        expenses,
        llm_service_cls=LLMService,
        generate_with_main_llm_async=generate_with_main_llm_async,
        build_stop_tokens=_build_stop_tokens,
    )


__all__ = [
    "generate_random_message_payload",
    "summarize_with_llm",
    "summarize_expenses_with_llm",
]
