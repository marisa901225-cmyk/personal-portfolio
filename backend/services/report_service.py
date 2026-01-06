"""
Report Service - Business logic for report generation.

이 서비스는 리포트 관련 모든 비즈니스 로직을 담당합니다:
- 기본 리포트 데이터 조립
- 기간별 집계 (월/분기/연간)
- AI 리포트 생성
- 저장된 리포트 CRUD

라우터는 이 서비스를 호출하고 HTTP 예외 매핑만 담당합니다.
"""
from __future__ import annotations

import httpx
import logging
import os
import json
import re
from datetime import date, datetime
from typing import List, Optional, AsyncGenerator

from sqlalchemy.orm import Session

from ..core.models import (
    AiReport,
    Asset,
    ExternalCashflow,
    FxTransaction,
    PortfolioSnapshot,
    Setting,
    Trade,
    User,
)
from ..core.schemas import (
    ExternalCashflowRead,
    MonthlyReportSummary,
    PortfolioResponse,
    QuarterlyReportSummary,
    ReportActivitySummary,
    ReportPeriod,
    ReportResponse,
    ReportAiResponse,
    ReportAiTextResponse,
    TopAssetSummary,
)
from ..services.portfolio import (
    calculate_summary,
    to_asset_read,
    to_fx_transaction_read,
    to_snapshot_read,
    to_trade_read,
)
from ..services.settings_service import to_settings_read
from ..services.duckdb_refine import refine_portfolio_for_ai

logger = logging.getLogger(__name__)


# ============================================
# AI Report Constants
# ============================================

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


# ============================================
# Report Core Logic (from report_core.py)
# ============================================

def get_user(db: Session) -> Optional[User]:
    """첫 번째 사용자를 조회한다."""
    return db.query(User).order_by(User.id.asc()).first()


def get_report_data(
    db: Session,
    year: Optional[int] = None,
    month: Optional[int] = None,
    quarter: Optional[int] = None,
) -> ReportResponse:
    """
    년/월/분기 파라미터를 받아 기간을 계산하고 리포트 데이터를 조회한다.
    (라우터에 있던 기간 계산 로직을 서비스로 이동)
    """
    start_date = None
    end_date = None
    if year is not None:
        if month is not None:
            # 월간
            start_date = date(year, month, 1)
            if month == 12:
                end_date = date(year + 1, 1, 1)
            else:
                end_date = date(year, month + 1, 1)
        elif quarter is not None:
            # 분기
            start_month = (quarter - 1) * 3 + 1
            start_date = date(year, start_month, 1)
            if quarter == 4:
                end_date = date(year + 1, 1, 1)
            else:
                end_date = date(year, start_month + 3, 1)
        else:
            # 연간
            start_date = date(year, 1, 1)
            end_date = date(year + 1, 1, 1)

    return build_report(db, start_date, end_date)


def get_quarterly_summaries(db: Session, year: int) -> List[QuarterlyReportSummary]:
    """특정 연도의 분기별 요약을 집계한다. (라우터 로직 이동)"""
    user = get_user(db)
    monthly = build_monthly_summaries(db, user, year)
    summaries = []
    for quarter in range(1, 5):
        start_month = (quarter - 1) * 3 + 1
        months = [start_month, start_month + 1, start_month + 2]
        activity = aggregate_activity(monthly, months)
        summaries.append(
            QuarterlyReportSummary(
                year=year,
                quarter=quarter,
                trade_count=activity.trade_count,
                trade_buy_value=activity.trade_buy_value,
                trade_sell_value=activity.trade_sell_value,
                cashflow_count=activity.cashflow_count,
                cashflow_total=activity.cashflow_total,
                fx_transaction_count=activity.fx_transaction_count,
                snapshot_count=activity.snapshot_count,
            )
        )
    return summaries


def build_monthly_summaries(
    db: Session,
    user: User | None,
    year: int,
) -> dict[int, MonthlyReportSummary]:
    """
    특정 연도의 월별 활동 요약을 생성한다.
    
    Returns:
        {월: MonthlyReportSummary} 딕셔너리
    """
    summaries = {
        month: MonthlyReportSummary(year=year, month=month)
        for month in range(1, 13)
    }
    if not user:
        return summaries

    start_date = date(year, 1, 1)
    end_date = date(year + 1, 1, 1)
    start_dt = datetime(year, 1, 1)
    end_dt = datetime(year + 1, 1, 1)

    trades = (
        db.query(Trade)
        .filter(
            Trade.user_id == user.id,
            Trade.timestamp >= start_dt,
            Trade.timestamp < end_dt,
        )
        .all()
    )
    for trade in trades:
        month = trade.timestamp.month
        summary = summaries[month]
        summary.trade_count += 1
        trade_value = trade.quantity * trade.price
        if trade.type == "BUY":
            summary.trade_buy_value += trade_value
        elif trade.type == "SELL":
            summary.trade_sell_value += trade_value

    cashflows = (
        db.query(ExternalCashflow)
        .filter(
            ExternalCashflow.user_id == user.id,
            ExternalCashflow.date >= start_date,
            ExternalCashflow.date < end_date,
        )
        .all()
    )
    for cashflow in cashflows:
        month = cashflow.date.month
        summary = summaries[month]
        summary.cashflow_count += 1
        summary.cashflow_total += cashflow.amount

    fx_transactions = (
        db.query(FxTransaction)
        .filter(
            FxTransaction.user_id == user.id,
            FxTransaction.trade_date >= start_date,
            FxTransaction.trade_date < end_date,
        )
        .all()
    )
    for record in fx_transactions:
        month = record.trade_date.month
        summaries[month].fx_transaction_count += 1

    snapshots = (
        db.query(PortfolioSnapshot)
        .filter(
            PortfolioSnapshot.user_id == user.id,
            PortfolioSnapshot.snapshot_at >= start_dt,
            PortfolioSnapshot.snapshot_at < end_dt,
        )
        .all()
    )
    for snapshot in snapshots:
        month = snapshot.snapshot_at.month
        summaries[month].snapshot_count += 1

    return summaries


def aggregate_activity(
    summaries: dict[int, MonthlyReportSummary],
    months: list[int],
) -> ReportActivitySummary:
    """월별 요약을 지정된 월들에 대해 집계한다."""
    activity = ReportActivitySummary()
    for month in months:
        summary = summaries.get(month)
        if not summary:
            continue
        activity.trade_count += summary.trade_count
        activity.trade_buy_value += summary.trade_buy_value
        activity.trade_sell_value += summary.trade_sell_value
        activity.cashflow_count += summary.cashflow_count
        activity.cashflow_total += summary.cashflow_total
        activity.fx_transaction_count += summary.fx_transaction_count
        activity.snapshot_count += summary.snapshot_count
    return activity


# ============================================
# Period Parsing & Validation
# ============================================

def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    """월을 delta만큼 이동 (연도 롤오버 처리)."""
    total = (year * 12) + (month - 1) + delta
    next_year = total // 12
    next_month = (total % 12) + 1
    return next_year, next_month


def normalize_two_digit_year(year: int) -> int:
    """2자리 연도를 4자리로 변환 (예: 25 -> 2025)."""
    return 2000 + year if year < 100 else year


def parse_report_query(query: str, today: date) -> tuple[int | None, int | None, int | None, int | None, str | None]:
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


def resolve_period(year: int, month: int | None, quarter: int | None, half: int | None) -> ReportPeriod:
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


# ============================================
# Expense Summary Helpers
# ============================================

def merge_expense_summaries(
    summaries: list[dict],
    year: int,
    quarter: int | None,
    half: int | None,
) -> dict:
    """여러 월별 지출 요약을 하나로 병합한다."""
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


# ============================================
# AI Report Helpers
# ============================================

def get_ai_config(
    period: ReportPeriod,
    model: str | None = None,
    max_tokens: int | None = None,
) -> tuple[str, str, str, int, float]:
    """
    AI API 설정을 환경변수에서 가져온다.
    
    Returns:
        (base_url, api_key, model, max_tokens, temperature)
        
    Raises:
        ValueError: API 키가 설정되지 않은 경우
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
    """데이터를 Server-Sent Event 형식으로 포맷한다."""
    lines = data.splitlines() or [""]
    payload = "\n".join([f"data: {line}" for line in lines])
    return f"event: {event}\n{payload}\n\n"


def build_report_prompt(period: ReportPeriod, refined_data: dict, expense_summary: dict) -> str:
    """AI 리포트 생성용 프롬프트를 생성한다."""
    payload = {
        "period": period.model_dump(mode="json"),
        "portfolio_refined": refined_data,
        "expense_summary": expense_summary,
    }
    return f"아래 데이터로 리포트를 작성해.\n\n{json.dumps(payload, ensure_ascii=False, default=str)}"


# ============================================
# AI Report Logic (Core Integration)
# ============================================

def resolve_ai_report_prompt(
    db: Session,
    year: Optional[int] = None,
    month: Optional[int] = None,
    quarter: Optional[int] = None,
    query: Optional[str] = None,
) -> tuple[ReportPeriod, str]:
    """
    AI 리포트 생성을 위한 입력을 해석하고 최종 프롬프트를 생성한다.
    (라우터의 복잡한 로직을 모두 서비스로 이동)
    """
    from ..services.expense_service import get_expense_summary
    
    today = date.today()
    resolved_year = year
    resolved_month = month
    resolved_quarter = quarter
    resolved_half = None

    if query:
        parsed_year, parsed_month, parsed_quarter, parsed_half, parse_error = parse_report_query(query, today)
        if parse_error:
            raise ValueError(parse_error)
        resolved_year = parsed_year or resolved_year or today.year
        resolved_month = parsed_month
        resolved_quarter = parsed_quarter
        resolved_half = parsed_half

    if resolved_year is None:
        raise ValueError("연도 정보가 필요해. 예: 2025년 6월 리포트")

    period = resolve_period(resolved_year, resolved_month, resolved_quarter, resolved_half)

    # DuckDB 정제 로직 호출
    refined = refine_portfolio_for_ai(
        year=period.year,
        month=period.month,
        quarter=period.quarter,
        half=period.half,
    )
    
    # 지출 요약 합산 로직
    if period.quarter is not None:
        start_month = (period.quarter - 1) * 3 + 1
        months = [start_month, start_month + 1, start_month + 2]
        summaries = [get_expense_summary(db, year=period.year, month=m) for m in months]
        expense_summary = merge_expense_summaries(summaries, period.year, period.quarter, None)
    elif period.half is not None:
        months = list(range(1, 7)) if period.half == 1 else list(range(7, 13))
        summaries = [get_expense_summary(db, year=period.year, month=m) for m in months]
        expense_summary = merge_expense_summaries(summaries, period.year, None, period.half)
    else:
        expense_summary = get_expense_summary(db, year=period.year, month=period.month)

    prompt = build_report_prompt(period, refined, expense_summary)
    return period, prompt


def get_refined_report_data(
    year: Optional[int] = None,
    month: Optional[int] = None,
    quarter: Optional[int] = None,
) -> dict:
    """DuckDB 정제 데이터를 반환한다."""
    if month is not None and quarter is not None:
        raise ValueError("use either month or quarter, not both")
    return refine_portfolio_for_ai(year=year, month=month, quarter=quarter)


async def generate_ai_report_text(
    period: ReportPeriod,
    prompt: str,
    model: Optional[str] = None,
    max_tokens: Optional[int] = None,
) -> ReportAiTextResponse:
    """AI API 호출 (Non-streaming)."""
    base_url, api_key, selected_model, selected_tokens, temperature = get_ai_config(period, model, max_tokens)

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": selected_model,
                "messages": [
                    {"role": "system", "content": AI_REPORT_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "temperature": temperature,
                "max_completion_tokens": selected_tokens,
            },
            timeout=60.0,
        )
    
    if response.status_code >= 400:
        raise RuntimeError(f"AI API request failed: {response.text}")

    data = response.json()
    report_text = data["choices"][0]["message"]["content"].strip()
    
    return ReportAiTextResponse(
        generated_at=datetime.utcnow(),
        period=period,
        report=report_text,
        model=selected_model,
    )


async def generate_ai_report_stream(
    period: ReportPeriod,
    prompt: str,
    model: Optional[str] = None,
    max_tokens: Optional[int] = None,
) -> AsyncGenerator[str, None]:
    """AI API 호출 (Streaming)."""
    base_url, api_key, selected_model, selected_tokens, temperature = get_ai_config(period, model, max_tokens)
    generated_at = datetime.utcnow()

    # Meta 정보 먼저 전달
    meta_payload = json.dumps(
        {
            "generated_at": generated_at.isoformat(),
            "period": period.model_dump(mode="json"),
            "model": selected_model,
        },
        ensure_ascii=False,
    )
    yield format_sse("meta", meta_payload)
    
    async with httpx.AsyncClient() as client:
        try:
            async with client.stream(
                "POST",
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": selected_model,
                    "messages": [
                        {"role": "system", "content": AI_REPORT_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": temperature,
                    "max_completion_tokens": selected_tokens,
                    "stream": True,
                },
                timeout=120.0,
            ) as response:
                if response.status_code >= 400:
                    yield format_sse("error", f"AI report request failed: {await response.aread()}")
                    return

                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        payload = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    
                    choice = (payload.get("choices") or [{}])[0]
                    delta = ""
                    if "delta" in choice:
                        delta = choice["delta"].get("content") or ""
                    elif "message" in choice:
                        delta = choice["message"].get("content") or ""
                    
                    if delta:
                        yield format_sse("chunk", delta)
        except Exception as exc:
            yield format_sse("error", f"AI request failed: {str(exc)}")
            return

    yield format_sse("done", "[DONE]")


def get_ai_report_metrics(
    db: Session,
    year: int,
    month: Optional[int] = None,
    quarter: Optional[int] = None,
    top_n: int = 10,
) -> ReportAiResponse:
    """AI 리포트 화면용 통계 데이터 및 Top 자산 집계."""
    period = resolve_period(year, month, quarter, None)
    user = get_user(db)
    monthly = build_monthly_summaries(db, user, year)
    
    if month is not None:
        activity = aggregate_activity(monthly, [month])
    elif quarter is not None:
        start_month = (quarter - 1) * 3 + 1
        activity = aggregate_activity(monthly, [start_month, start_month + 1, start_month + 2])
    else:
        activity = aggregate_activity(monthly, list(range(1, 13)))

    if not user:
        summary = calculate_summary([], [])
        return ReportAiResponse(
            generated_at=datetime.utcnow(),
            period=period,
            summary=summary,
            activity=activity,
            top_assets=[],
        )

    assets = (
        db.query(Asset)
        .filter(Asset.user_id == user.id, Asset.deleted_at.is_(None))
        .order_by(Asset.id.asc())
        .all()
    )
    cashflows = (
        db.query(ExternalCashflow)
        .filter(
            ExternalCashflow.user_id == user.id,
            ExternalCashflow.date >= period.start_date,
            ExternalCashflow.date < period.end_date,
        )
        .all()
    )
    
    # Cashflow metrics
    deposit_total = 0.0
    withdrawal_total = 0.0
    for cashflow in cashflows:
        if cashflow.amount < 0:
            deposit_total += abs(cashflow.amount)
        else:
            withdrawal_total += cashflow.amount

    activity.cashflow_total = sum(c.amount for c in cashflows)
    activity.deposit_total = deposit_total
    activity.withdrawal_total = withdrawal_total
    activity.net_flow = deposit_total - withdrawal_total
    activity.invested_principal = activity.net_flow
    activity.net_buy = activity.trade_buy_value - activity.trade_sell_value
    
    summary = calculate_summary(assets, cashflows)

    # Top assets
    top_assets = []
    for asset in assets:
        value = asset.amount * asset.current_price
        invested = asset.amount * (asset.purchase_price or asset.current_price)
        unrealized_profit = value - invested
        unrealized_profit_rate = (unrealized_profit / invested * 100) if invested > 0 else None
        top_assets.append(
            TopAssetSummary(
                id=asset.id,
                name=asset.name,
                ticker=asset.ticker,
                category=asset.category,
                currency=asset.currency,
                amount=asset.amount,
                current_price=asset.current_price,
                purchase_price=asset.purchase_price,
                value=value,
                invested=invested,
                unrealized_profit=unrealized_profit,
                unrealized_profit_rate=unrealized_profit_rate,
            )
        )
    top_assets.sort(key=lambda item: item.value, reverse=True)

    return ReportAiResponse(
        generated_at=datetime.utcnow(),
        period=period,
        summary=summary,
        activity=activity,
        top_assets=top_assets[:top_n],
    )


# ============================================
# Saved Report CRUD (from report_saved.py)
# ============================================

def list_saved_reports(db: Session) -> list[dict]:
    """저장된 AI 리포트 목록을 조회한다."""
    user = get_user(db)
    if not user:
        return []

    reports = (
        db.query(AiReport)
        .filter(AiReport.user_id == user.id)
        .order_by(AiReport.generated_at.desc())
        .all()
    )
    return [
        {
            "id": r.id,
            "period_year": r.period_year,
            "period_month": r.period_month,
            "period_quarter": r.period_quarter,
            "period_half": r.period_half,
            "query": r.query,
            "report": r.report,
            "model": r.model,
            "generated_at": r.generated_at.isoformat(),
            "created_at": r.created_at.isoformat(),
        }
        for r in reports
    ]


def save_report(db: Session, payload: dict) -> dict:
    """
    AI 리포트를 저장한다.
    
    Raises:
        ValueError: 사용자가 없는 경우
    """
    user = get_user(db)
    if not user:
        raise ValueError("사용자가 없습니다.")

    generated_at_str = payload.get("generated_at")
    if generated_at_str:
        try:
            generated_at = datetime.fromisoformat(generated_at_str.replace("Z", "+00:00"))
        except ValueError:
            generated_at = datetime.utcnow()
    else:
        generated_at = datetime.utcnow()

    report = AiReport(
        user_id=user.id,
        period_year=payload.get("period_year", datetime.utcnow().year),
        period_month=payload.get("period_month"),
        period_quarter=payload.get("period_quarter"),
        period_half=payload.get("period_half"),
        query=payload.get("query", ""),
        report=payload.get("report", ""),
        model=payload.get("model"),
        generated_at=generated_at,
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    return {
        "id": report.id,
        "period_year": report.period_year,
        "period_month": report.period_month,
        "period_quarter": report.period_quarter,
        "period_half": report.period_half,
        "query": report.query,
        "report": report.report,
        "model": report.model,
        "generated_at": report.generated_at.isoformat(),
        "created_at": report.created_at.isoformat(),
    }


def delete_saved_report(db: Session, report_id: int) -> dict:
    """
    저장된 AI 리포트를 삭제한다.
    
    Raises:
        ValueError: 사용자가 없는 경우
        LookupError: 리포트를 찾을 수 없는 경우
    """
    user = get_user(db)
    if not user:
        raise ValueError("사용자가 없습니다.")

    report = (
        db.query(AiReport)
        .filter(AiReport.id == report_id, AiReport.user_id == user.id)
        .first()
    )
    if not report:
        raise LookupError("리포트를 찾을 수 없습니다.")

    db.delete(report)
    db.commit()

    return {"message": "삭제되었습니다.", "id": report_id}


# ============================================
# Private Helpers (Extracted from report_core)
# ============================================

def build_report(
    db: Session,
    start_date: Optional[date],
    end_date: Optional[date],
) -> ReportResponse:
    """기간에 해당하는 데이터를 조립한다."""
    user = get_user(db)
    if not user:
        summary = calculate_summary([], [])
        return ReportResponse(
            generated_at=datetime.utcnow(),
            portfolio=PortfolioResponse(assets=[], trades=[], summary=summary),
            snapshots=[],
            fx_transactions=[],
            external_cashflows=[],
            settings=None,
        )

    start_dt = None
    end_dt = None
    if start_date and end_date:
        start_dt = datetime(start_date.year, start_date.month, start_date.day)
        end_dt = datetime(end_date.year, end_date.month, end_date.day)

    assets = (
        db.query(Asset)
        .filter(Asset.user_id == user.id, Asset.deleted_at.is_(None))
        .order_by(Asset.id.asc())
        .all()
    )
    
    trades_query = db.query(Trade).filter(Trade.user_id == user.id)
    if start_dt and end_dt:
        trades_query = trades_query.filter(
            Trade.timestamp >= start_dt,
            Trade.timestamp < end_dt,
        )
    trades = trades_query.order_by(Trade.timestamp.asc()).all()

    snapshots_query = db.query(PortfolioSnapshot).filter(PortfolioSnapshot.user_id == user.id)
    if start_dt and end_dt:
        snapshots_query = snapshots_query.filter(
            PortfolioSnapshot.snapshot_at >= start_dt,
            PortfolioSnapshot.snapshot_at < end_dt,
        )
    snapshots = snapshots_query.order_by(PortfolioSnapshot.snapshot_at.asc()).all()

    fx_query = db.query(FxTransaction).filter(FxTransaction.user_id == user.id)
    if start_date and end_date:
        fx_query = fx_query.filter(
            FxTransaction.trade_date >= start_date,
            FxTransaction.trade_date < end_date,
        )
    fx_transactions = fx_query.order_by(
        FxTransaction.trade_date.asc(),
        FxTransaction.id.asc(),
    ).all()

    cashflows_query = db.query(ExternalCashflow).filter(ExternalCashflow.user_id == user.id)
    if start_date and end_date:
        cashflows_query = cashflows_query.filter(
            ExternalCashflow.date >= start_date,
            ExternalCashflow.date < end_date,
        )
    external_cashflows = cashflows_query.order_by(
        ExternalCashflow.date.asc(),
        ExternalCashflow.id.asc(),
    ).all()
    
    setting = (
        db.query(Setting)
        .filter(Setting.user_id == user.id)
        .order_by(Setting.id.asc())
        .first()
    )

    summary = calculate_summary(assets, external_cashflows)

    return ReportResponse(
        generated_at=datetime.utcnow(),
        portfolio=PortfolioResponse(
            assets=[to_asset_read(a) for a in assets],
            trades=[to_trade_read(t) for t in trades],
            summary=summary,
        ),
        snapshots=[to_snapshot_read(s) for s in snapshots],
        fx_transactions=[to_fx_transaction_read(r) for r in fx_transactions],
        external_cashflows=[ExternalCashflowRead.model_validate(c) for c in external_cashflows],
        settings=to_settings_read(setting) if setting else None,
    )
