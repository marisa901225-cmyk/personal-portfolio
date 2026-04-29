from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

ReviewPayload: TypeAlias = dict[str, object]
ReviewMessage: TypeAlias = dict[str, object]


@dataclass(slots=True)
class DayChartReviewResult:
    shortlisted_codes: list[str]
    approved_codes: list[str]
    selected_code: str | None
    summary: str
    chart_paths: list[str]
    raw_response: ReviewPayload | None = None


@dataclass(slots=True)
class ReviewAsset:
    code: str
    meta_text: str
    chart_path: str


__all__ = [
    "DayChartReviewResult",
    "ReviewAsset",
    "ReviewMessage",
    "ReviewPayload",
]
