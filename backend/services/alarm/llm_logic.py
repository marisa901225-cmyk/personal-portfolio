# backend/services/alarm/llm_logic.py
"""Compatibility layer that keeps the legacy import path on top of v2."""

from __future__ import annotations

from typing import Any

from . import llm_logic_v2 as _impl
from .random_categories import _RANDOM_TOPIC_STATE_FILE

_LOCAL_ONLY_NAMES = {
    "_impl",
    "_LOCAL_ONLY_NAMES",
    "_sync_impl",
    "_copy_impl_symbol",
    "_RANDOM_TOPIC_STATE_FILE",
    "summarize_with_llm",
    "summarize_expenses_with_llm",
}


def _copy_impl_symbol(name: str) -> None:
    if name.startswith("__") or name in _LOCAL_ONLY_NAMES:
        return
    globals()[name] = getattr(_impl, name)


for _name in dir(_impl):
    _copy_impl_symbol(_name)


def _sync_impl() -> None:
    for name, value in list(globals().items()):
        if name.startswith("__") or name in _LOCAL_ONLY_NAMES:
            continue
        if hasattr(_impl, name):
            setattr(_impl, name, value)


async def summarize_with_llm(*args: Any, **kwargs: Any):
    _sync_impl()
    return await _impl.summarize_with_llm(*args, **kwargs)


async def summarize_expenses_with_llm(*args: Any, **kwargs: Any):
    _sync_impl()
    return await _impl.summarize_expenses_with_llm(*args, **kwargs)


del _name

