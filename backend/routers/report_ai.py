from __future__ import annotations

from datetime import date, datetime
import json

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..auth import verify_api_token
from ..db import get_db
from ..models import Asset, ExternalCashflow, User
from ..schemas import ReportAiResponse, ReportAiTextResponse, ReportPeriod, TopAssetSummary
from ..services.portfolio import calculate_summary
from ..services.report_service import (
    AI_REPORT_SYSTEM_PROMPT,
    parse_report_query,
    resolve_period,
    merge_expense_summaries,
    get_ai_config,
    format_sse,
    build_report_prompt,
)
from .report_core import _aggregate_activity, _build_monthly_summaries

router = APIRouter(prefix="/api", tags=["report"], dependencies=[Depends(verify_api_token)])


def _resolve_ai_report_input(
    year: int | None,
    month: int | None,
    quarter: int | None,
    query: str | None,
    db: Session,
) -> tuple[ReportPeriod, str]:
    """Resolve input parameters and build report prompt."""
    today = date.today()
    resolved_year = year
    resolved_month = month
    resolved_quarter = quarter
    resolved_half = None

    if query:
        parsed_year, parsed_month, parsed_quarter, parsed_half, parse_error = parse_report_query(query, today)
        if parse_error:
            raise HTTPException(status_code=400, detail=parse_error)
        resolved_year = parsed_year or resolved_year or today.year
        resolved_month = parsed_month
        resolved_quarter = parsed_quarter
        resolved_half = parsed_half

    if resolved_year is None:
        raise HTTPException(status_code=400, detail="연도 정보가 필요해. 예: 2025년 6월 리포트")

    if resolved_month is not None and not (1 <= resolved_month <= 12):
        raise HTTPException(status_code=400, detail="월 값이 이상해. 1~12월로 입력해줘.")
    if resolved_quarter is not None and not (1 <= resolved_quarter <= 4):
        raise HTTPException(status_code=400, detail="분기 값이 이상해. 1~4분기로 입력해줘.")

    try:
        period = resolve_period(resolved_year, resolved_month, resolved_quarter, resolved_half)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    from ..services.duckdb_refine import refine_portfolio_for_ai
    from ..routers.expenses import get_expense_summary

    refined = refine_portfolio_for_ai(
        year=period.year,
        month=period.month,
        quarter=period.quarter,
        half=period.half,
    )
    
    if period.quarter is not None:
        start_month = (period.quarter - 1) * 3 + 1
        months = [start_month, start_month + 1, start_month + 2]
        summaries = [get_expense_summary(year=period.year, month=m, db=db) for m in months]
        expense_summary = merge_expense_summaries(summaries, period.year, period.quarter, None)
    elif period.half is not None:
        months = list(range(1, 7)) if period.half == 1 else list(range(7, 13))
        summaries = [get_expense_summary(year=period.year, month=m, db=db) for m in months]
        expense_summary = merge_expense_summaries(summaries, period.year, None, period.half)
    else:
        expense_summary = get_expense_summary(year=period.year, month=period.month, db=db)

    prompt = build_report_prompt(period, refined, expense_summary)
    return period, prompt


def _resolve_ai_report_config(
    period: ReportPeriod,
    model: str | None,
    max_tokens: int | None,
) -> tuple[str, str, str, int, float]:
    """Get AI configuration, raising HTTPException on error."""
    try:
        return get_ai_config(period, model, max_tokens)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/report/ai", response_model=ReportAiResponse)
def get_report_ai(
    year: int = Query(..., ge=1970),
    month: int | None = Query(None, ge=1, le=12),
    quarter: int | None = Query(None, ge=1, le=4),
    top_n: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
) -> ReportAiResponse:
    if month is not None and quarter is not None:
        raise HTTPException(status_code=400, detail="use either month or quarter, not both")

    try:
        period = resolve_period(year, month, quarter, None)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    user = db.query(User).order_by(User.id.asc()).first()
    monthly = _build_monthly_summaries(db, user, year)
    
    if month is not None:
        activity = _aggregate_activity(monthly, [month])
    elif quarter is not None:
        start_month = (quarter - 1) * 3 + 1
        activity = _aggregate_activity(monthly, [start_month, start_month + 1, start_month + 2])
    else:
        activity = _aggregate_activity(monthly, list(range(1, 13)))

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
    
    # Calculate cashflow metrics
    cashflow_count = len(cashflows)
    deposit_total = 0.0
    withdrawal_total = 0.0
    for cashflow in cashflows:
        if cashflow.amount < 0:
            deposit_total += abs(cashflow.amount)
        else:
            withdrawal_total += cashflow.amount

    activity.cashflow_count = cashflow_count
    activity.cashflow_total = sum(c.amount for c in cashflows)
    activity.deposit_total = deposit_total
    activity.withdrawal_total = withdrawal_total
    activity.net_flow = deposit_total - withdrawal_total
    activity.invested_principal = activity.net_flow
    activity.net_buy = activity.trade_buy_value - activity.trade_sell_value
    
    summary = calculate_summary(assets, cashflows)

    # Build top assets list
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


@router.get("/report/ai/text", response_model=ReportAiTextResponse)
def get_report_ai_text(
    year: int | None = Query(None, ge=1970),
    month: int | None = Query(None, ge=1, le=12),
    quarter: int | None = Query(None, ge=1, le=4),
    query: str | None = Query(None),
    model: str | None = Query(None),
    max_tokens: int | None = Query(None, ge=256, le=10000),
    db: Session = Depends(get_db),
) -> ReportAiTextResponse:
    period, prompt = _resolve_ai_report_input(year, month, quarter, query, db)
    base_url, api_key, selected_model, selected_tokens, temperature = _resolve_ai_report_config(
        period, model, max_tokens
    )

    try:
        response = httpx.post(
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
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail="AI report request failed") from exc

    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"AI report request failed: {response.text}")

    try:
        data = response.json()
        report_text = data["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        raise HTTPException(status_code=502, detail="AI report response parsing failed") from exc

    if not report_text:
        raise HTTPException(status_code=502, detail="AI report response was empty")

    return ReportAiTextResponse(
        generated_at=datetime.utcnow(),
        period=period,
        report=report_text,
        model=selected_model,
    )


@router.get("/report/ai/text/stream")
def get_report_ai_text_stream(
    year: int | None = Query(None, ge=1970),
    month: int | None = Query(None, ge=1, le=12),
    quarter: int | None = Query(None, ge=1, le=4),
    query: str | None = Query(None),
    model: str | None = Query(None),
    max_tokens: int | None = Query(None, ge=256, le=10000),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    period, prompt = _resolve_ai_report_input(year, month, quarter, query, db)
    base_url, api_key, selected_model, selected_tokens, temperature = _resolve_ai_report_config(
        period, model, max_tokens
    )
    generated_at = datetime.utcnow()

    def event_stream():
        meta_payload = json.dumps(
            {
                "generated_at": generated_at.isoformat(),
                "period": period.model_dump(mode="json"),
                "model": selected_model,
            },
            ensure_ascii=False,
        )
        yield format_sse("meta", meta_payload)
        
        try:
            with httpx.stream(
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
                    yield format_sse("error", f"AI report request failed: {response.text}")
                    return

                for line in response.iter_lines():
                    if not line:
                        continue
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        payload = json.loads(data)
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
        except httpx.RequestError:
            yield format_sse("error", "AI report request failed")
            return

        yield format_sse("done", "[DONE]")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get("/report/refined")
def get_refined_report(
    year: int | None = Query(None, ge=1970),
    month: int | None = Query(None, ge=1, le=12),
    quarter: int | None = Query(None, ge=1, le=4),
) -> dict:
    """
    DuckDB 기반 고성능 분석 레이어를 통해 정제된 포트폴리오 데이터를 반환합니다.
    """
    from ..services.duckdb_refine import refine_portfolio_for_ai

    if month is not None and quarter is not None:
        raise HTTPException(status_code=400, detail="use either month or quarter, not both")

    try:
        return refine_portfolio_for_ai(year=year, month=month, quarter=quarter)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"DuckDB refinement failed: {exc}") from exc
