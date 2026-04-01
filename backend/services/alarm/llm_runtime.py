from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .llm_refiner import STOP_TOKENS, clean_meta_headers

_RE_WS = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class _LLMRunOptions:
    max_tokens: int
    temperature: float
    enable_thinking: bool
    extra_kwargs: Dict[str, Any]


def _dedupe_keep_order(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for value in items:
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _build_stop_tokens(extra: Optional[List[str]] = None) -> List[str]:
    base = list(STOP_TOKENS or [])
    if extra:
        base.extend(extra)
    return _dedupe_keep_order(base)


def _filter_llm_kwargs(llm_kwargs: Dict[str, Any], exclude: Tuple[str, ...]) -> Dict[str, Any]:
    return {key: value for key, value in (llm_kwargs or {}).items() if key not in exclude}


def _resolve_llm_options(
    llm_kwargs: Dict[str, Any],
    *,
    default_max_tokens: int,
    default_temperature: float,
) -> _LLMRunOptions:
    return _LLMRunOptions(
        max_tokens=int(llm_kwargs.get("max_tokens", default_max_tokens)),
        temperature=float(llm_kwargs.get("temperature", default_temperature)),
        enable_thinking=bool(llm_kwargs.get("enable_thinking", False)),
        extra_kwargs=_filter_llm_kwargs(
            llm_kwargs,
            exclude=("max_tokens", "temperature", "enable_thinking", "stop"),
        ),
    )


def _postprocess_llm_text(text: str) -> str:
    text = clean_meta_headers(text or "")
    return text.strip()


def _compact_reason(reason: str, limit: int = 140) -> str:
    return _RE_WS.sub(" ", (reason or "")).strip()[:limit]
