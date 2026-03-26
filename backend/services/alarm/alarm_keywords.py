"""Shared keyword constants for alarm filtering and summary validation."""

from __future__ import annotations

# Used by sanitizer grounding checks only for highly domain-specific cases.
# Keep this list conservative so generic delivery/status words do not let
# hallucinated lines slip through as "grounded".
SUMMARY_GROUNDING_KEYWORDS: tuple[str, ...] = (
    "결제",
    "송금",
    "입금",
    "출금",
    "카톡",
    "문자",
    "영수증",
    "기상청",
    "공지",
)

# Used by count-only summary validation to avoid rejecting terse but still
# meaningful lines like "배송 2건" or "결제 1건".
COUNT_ONLY_EXCEPTION_KEYWORDS: tuple[str, ...] = (
    "배송",
    "택배",
    "배달",
    "업데이트",
    "도착",
    "완료",
    "결제",
    "충전",
    "메시지",
)

# Used when extracting strong grounding tokens so generic status prefixes do
# not count as evidence by themselves.
GENERIC_PREFIXES_TO_IGNORE: tuple[str, ...] = (
    "배달",
    "완료",
    "알림",
    "메시지",
    "확인",
    "오늘",
    "내일",
    "어제",
    "전송",
)
