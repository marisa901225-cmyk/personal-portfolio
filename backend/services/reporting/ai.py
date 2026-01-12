from __future__ import annotations

import json
import os
from datetime import date, datetime
from typing import AsyncGenerator, Optional

import httpx
from sqlalchemy.orm import Session

from ...core.models import Asset, ExternalCashflow
from ...core.schemas import ReportAiResponse, ReportAiTextResponse, ReportPeriod, TopAssetSummary
from ...services.portfolio import calculate_summary
from .core import aggregate_activity, build_monthly_summaries, get_user
from .expenses import merge_expense_summaries
from .periods import parse_report_query, resolve_period

AI_REPORT_SYSTEM_PROMPT = """너는 Ailey & Bailey 듀오의 가계부+투자 리포트 작성자야.

Ailey는 공감적 코치로서 칭찬과 격려, 쉬운 비유를 사용해 요약해.
Bailey는 냉정한 악마의 변호인으로서 리스크와 약점을 짚어줘.

규칙:
- 한국어 반말로 작성해.
- 섹션 제목은 '###'로 시작해.
- 모든 섹션은 불렛포인트(번호 포함) 대신 부드러운 서술형 문장으로 작성해줘.
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
### 다음 액션 (부드러운 문장으로 추천)
"""


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
    from ...services.expense_service import get_expense_summary

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

    # DuckDB 정제 로직 호출 (lazy import to avoid circular import)
    from ...services.duckdb_refine import refine_portfolio_for_ai
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
    # Lazy import to avoid circular import
    from ...services.duckdb_refine import refine_portfolio_for_ai
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
