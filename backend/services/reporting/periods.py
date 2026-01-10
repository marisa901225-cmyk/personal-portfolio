from __future__ import annotations

import re
from datetime import date

from ...core.schemas import ReportPeriod


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    """월을 delta만큼 이동 (연도 롤오버 처리)."""
    total = (year * 12) + (month - 1) + delta
    next_year = total // 12
    next_month = (total % 12) + 1
    return next_year, next_month


def normalize_two_digit_year(year: int) -> int:
    """2자리 연도를 4자리로 변환 (예: 25 -> 2025)."""
    return 2000 + year if year < 100 else year


def parse_report_query(
    query: str,
    today: date,
) -> tuple[int | None, int | None, int | None, int | None, str | None]:
    """
    자연어 쿼리에서 기간 파라미터를 추출한다.

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


def resolve_period(
    year: int,
    month: int | None,
    quarter: int | None,
    half: int | None,
) -> ReportPeriod:
    """
    기간 파라미터를 실제 날짜 범위로 변환한다.

    Raises:
        ValueError: 여러 기간 타입이 지정된 경우
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


def format_period_label(period: ReportPeriod) -> str:
    if period.month is not None:
        return f"{period.year}-{period.month:02d}"
    if period.quarter is not None:
        return f"{period.year} Q{period.quarter}"
    if period.half is not None:
        return f"{period.year} H{period.half}"
    return str(period.year)


def is_historical_period(period: ReportPeriod, today: date | None = None) -> bool:
    if today is None:
        today = date.today()
    return (
        period.month is not None
        or period.quarter is not None
        or period.half is not None
        or period.year != today.year
    )
