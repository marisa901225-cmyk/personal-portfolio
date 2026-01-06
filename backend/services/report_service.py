"""
Report Service - Business logic for AI report generation.

Extracted from routers/report_ai.py for reusability and cleaner architecture.
"""
from __future__ import annotations

from datetime import date, datetime
import json
import logging
import os
import re
from typing import TYPE_CHECKING

from ..schemas import ReportPeriod

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# System prompt for AI report generation
AI_REPORT_SYSTEM_PROMPT = """너는 Ailey & Bailey 듀오의 가계부+투자 리포트 작성자야.

Ailey는 공감적 코치로서 칭찬과 격려, 쉬운 비유를 사용해 요약해.
Bailey는 냉정한 악마의 변호인으로서 리스크와 약점을 짚어줘.

규칙:
- 한국어 반말로 작성해.
- 섹션 제목은 '###'로 시작해.
- 표, 코드블록, 백틱은 쓰지 마.
- 데이터에 없는 내용은 추정하지 말고 '데이터 없음'이라고 적어.
- 숫자는 데이터 값을 그대로 사용하고, 단위/부호 의미를 설명해.

출력 형식:
### 한줄 요약
### Ailey 코멘트
### Bailey 코멘트
### 투자 요약
### 가계부 요약
### 리스크/개선 포인트
### 다음 액션 (3개, 번호 목록)
"""


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    """Shift month by delta, handling year rollover."""
    total = (year * 12) + (month - 1) + delta
    next_year = total // 12
    next_month = (total % 12) + 1
    return next_year, next_month


def normalize_two_digit_year(year: int) -> int:
    """Convert 2-digit year to 4-digit (e.g., 25 -> 2025)."""
    return 2000 + year if year < 100 else year


def parse_report_query(query: str, today: date) -> tuple[int | None, int | None, int | None, int | None, str | None]:
    """
    Parse natural language query to extract period parameters.
    
    Returns:
        (year, month, quarter, half, error_message)
        error_message is None on success
    """
    normalized = query.strip()
    if not normalized:
        return None, None, None, None, "요청 문장이 비어있어. 예: 2025년 6월 리포트"

    year = None
    month = None
    quarter = None
    half = None
    matched = False

    # Relative year keywords
    if "올해" in normalized or "이번해" in normalized or "이번 해" in normalized:
        year = today.year
        matched = True
    if "작년" in normalized or "전년" in normalized:
        year = today.year - 1
        matched = True
    if "내년" in normalized:
        year = today.year + 1
        matched = True

    # Year-month pattern (e.g., 2025년 6월, 2025-06)
    year_month_match = re.search(r"(\d{2,4})\s*[년\-/\.]\s*(\d{1,2})\s*월?", normalized)
    if year_month_match:
        year = normalize_two_digit_year(int(year_month_match.group(1)))
        month = int(year_month_match.group(2))
        matched = True

    # Year only pattern
    year_match = re.search(r"(\d{2,4})\s*년", normalized)
    if year_match:
        year = normalize_two_digit_year(int(year_match.group(1)))
        matched = True

    # Relative month keywords
    if "이번달" in normalized or "이번 달" in normalized:
        year = year or today.year
        month = today.month
        matched = True
    if "지난달" in normalized or "지난 달" in normalized or "전월" in normalized:
        base_year = year or today.year
        base_month = today.month
        year, month = shift_month(base_year, base_month, -1)
        matched = True
    if "다음달" in normalized or "다음 달" in normalized:
        base_year = year or today.year
        base_month = today.month
        year, month = shift_month(base_year, base_month, 1)
        matched = True

    # Month only pattern
    month_match = re.search(r"(\d{1,2})\s*월", normalized)
    if month_match:
        month = int(month_match.group(1))
        matched = True

    # Quarter keywords
    if "이번분기" in normalized or "이번 분기" in normalized:
        year = year or today.year
        quarter = ((today.month - 1) // 3) + 1
        matched = True
    if "지난분기" in normalized or "지난 분기" in normalized or "전분기" in normalized:
        base_year = year or today.year
        base_quarter = ((today.month - 1) // 3) + 1
        if base_quarter == 1:
            year = base_year - 1
            quarter = 4
        else:
            year = base_year
            quarter = base_quarter - 1
        matched = True
    if "다음분기" in normalized or "다음 분기" in normalized:
        base_year = year or today.year
        base_quarter = ((today.month - 1) // 3) + 1
        if base_quarter == 4:
            year = base_year + 1
            quarter = 1
        else:
            year = base_year
            quarter = base_quarter + 1
        matched = True

    # Quarter patterns (Q1, 1분기)
    quarter_match = re.search(r"(?:Q|q)([1-4])", normalized)
    if quarter_match:
        quarter = int(quarter_match.group(1))
        matched = True
    quarter_ko_match = re.search(r"([1-4])\s*분기", normalized)
    if quarter_ko_match:
        quarter = int(quarter_ko_match.group(1))
        matched = True

    # Half-year keywords
    if "상반기" in normalized or "전반기" in normalized:
        year = year or today.year
        half = 1
        matched = True
    if "하반기" in normalized or "후반기" in normalized:
        year = year or today.year
        half = 2
        matched = True

    # Annual keywords
    if "연간" in normalized or "전체" in normalized:
        month = None
        quarter = None
        half = None
        matched = True

    if not matched:
        return None, None, None, None, (
            "요청에서 기간을 찾지 못했어. "
            "예: 2025년 6월 리포트 / 2025년 2분기 리포트 / 올해 연간 리포트 / 지난달 리포트"
        )

    # Validation: only one period type allowed
    if month is not None and quarter is not None:
        return year, None, None, None, "월과 분기를 동시에 요청할 수 없어. 둘 중 하나만 선택해줘."
    if month is not None and half is not None:
        return year, None, None, None, "월과 반기를 동시에 요청할 수 없어. 둘 중 하나만 선택해줘."
    if quarter is not None and half is not None:
        return year, None, None, None, "분기와 반기를 동시에 요청할 수 없어. 둘 중 하나만 선택해줘."

    if year is None:
        year = today.year

    return year, month, quarter, half, None


def resolve_period(year: int, month: int | None, quarter: int | None, half: int | None) -> ReportPeriod:
    """
    Resolve period parameters to actual date range.
    
    Raises:
        ValueError: if multiple period types are specified
    """
    if sum(value is not None for value in (month, quarter, half)) > 1:
        raise ValueError("use either month, quarter, or half")

    if month is not None:
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1)
        else:
            end_date = date(year, month + 1, 1)
    elif quarter is not None:
        start_month = (quarter - 1) * 3 + 1
        start_date = date(year, start_month, 1)
        if quarter == 4:
            end_date = date(year + 1, 1, 1)
        else:
            end_date = date(year, start_month + 3, 1)
    elif half is not None:
        if half == 1:
            start_date = date(year, 1, 1)
            end_date = date(year, 7, 1)
        elif half == 2:
            start_date = date(year, 7, 1)
            end_date = date(year + 1, 1, 1)
        else:
            raise ValueError("half must be 1 or 2")
    else:
        start_date = date(year, 1, 1)
        end_date = date(year + 1, 1, 1)

    return ReportPeriod(
        year=year,
        month=month,
        quarter=quarter,
        half=half,
        start_date=start_date,
        end_date=end_date,
    )


def merge_expense_summaries(
    summaries: list[dict],
    year: int,
    quarter: int | None,
    half: int | None,
) -> dict:
    """Merge multiple monthly expense summaries into one."""
    total_expense = sum(s.get("total_expense", 0) for s in summaries)
    total_income = sum(s.get("total_income", 0) for s in summaries)
    fixed_expense = sum(s.get("fixed_expense", 0) for s in summaries)

    category_map: dict[str, float] = {}
    for summary in summaries:
        for item in summary.get("category_breakdown", []):
            category = item.get("category")
            amount = item.get("amount", 0)
            if category:
                category_map[category] = category_map.get(category, 0) + amount

    method_map: dict[str, float] = {}
    for summary in summaries:
        for item in summary.get("method_breakdown", []):
            method = item.get("method")
            amount = item.get("amount", 0)
            if method:
                method_map[method] = method_map.get(method, 0) + amount

    return {
        "period": {"year": year, "month": None, "quarter": quarter, "half": half},
        "total_expense": total_expense,
        "total_income": total_income,
        "net": total_income - total_expense,
        "fixed_expense": fixed_expense,
        "fixed_ratio": (fixed_expense / total_expense) * 100 if total_expense else 0,
        "category_breakdown": [
            {"category": k, "amount": v}
            for k, v in sorted(category_map.items(), key=lambda x: x[1], reverse=True)
        ],
        "method_breakdown": [
            {"method": k, "amount": v}
            for k, v in sorted(method_map.items(), key=lambda x: x[1], reverse=True)
        ],
        "transaction_count": sum(s.get("transaction_count", 0) for s in summaries),
    }


def get_ai_config(
    period: ReportPeriod,
    model: str | None = None,
    max_tokens: int | None = None,
) -> tuple[str, str, str, int, float]:
    """
    Get AI API configuration from environment.
    
    Returns:
        (base_url, api_key, model, max_tokens, temperature)
        
    Raises:
        ValueError: if API key is not configured
    """
    base_url = os.getenv("AI_REPORT_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    api_key = os.getenv("AI_REPORT_API_KEY")
    default_model = os.getenv("AI_REPORT_MODEL", "gpt-5.2")
    yearly_model = os.getenv("AI_REPORT_MODEL_YEARLY", "gpt-5.2-pro")
    temperature = float(os.getenv("AI_REPORT_TEMPERATURE", "0.3"))
    default_tokens = int(os.getenv("AI_REPORT_MAX_TOKENS", "8000"))

    if not api_key:
        raise ValueError("AI_REPORT_API_KEY is not configured")

    selected_model = model or (
        yearly_model if period.month is None and period.quarter is None and period.half is None else default_model
    )
    selected_tokens = max_tokens or default_tokens
    return base_url, api_key, selected_model, selected_tokens, temperature


def format_sse(event: str, data: str) -> str:
    """Format data as Server-Sent Event."""
    lines = data.splitlines() or [""]
    payload = "\n".join([f"data: {line}" for line in lines])
    return f"event: {event}\n{payload}\n\n"


def build_report_prompt(period: ReportPeriod, refined_data: dict, expense_summary: dict) -> str:
    """Build the prompt for AI report generation."""
    payload = {
        "period": period.model_dump(mode="json"),
        "portfolio_refined": refined_data,
        "expense_summary": expense_summary,
    }
    return f"아래 데이터로 리포트를 작성해.\n\n{json.dumps(payload, ensure_ascii=False, default=str)}"
