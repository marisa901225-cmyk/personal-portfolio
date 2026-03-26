from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .collector import NewsCollector as NewsCollector

__all__ = ["NewsCollector"]


def __getattr__(name: str):
    if name == "NewsCollector":
        from .collector import NewsCollector

        return NewsCollector
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
