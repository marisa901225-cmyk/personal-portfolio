from __future__ import annotations

from datetime import date, datetime
import json
import os
import re
from typing import List

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth import verify_api_token
from ..db import get_db
from ..models import (
    AiReport,
    Asset,
    ExternalCashflow,
    FxTransaction,
    PortfolioSnapshot,
    Setting,
    Trade,
    User,
)
from ..routers.settings import _to_settings_read
from ..schemas import (
    ExternalCashflowRead,
    MonthlyReportSummary,
    PortfolioResponse,
    QuarterlyReportSummary,
    ReportActivitySummary,
    ReportAiResponse,
    ReportAiTextResponse,
    ReportPeriod,
    ReportResponse,
    TopAssetSummary,
)
from ..services.portfolio import (
    calculate_summary,
    to_asset_read,
    to_fx_transaction_read,
    to_snapshot_read,
    to_trade_read,
)

router = APIRouter(prefix="/api", tags=["report"], dependencies=[Depends(verify_api_token)])

_AI_REPORT_SYSTEM_PROMPT = """너는 Ailey & Bailey 듀오의 가계부+투자 리포트 작성자야.

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
### 확인 질문 (2개, 번호 목록)
"""


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    total = (year * 12) + (month - 1) + delta
    next_year = total // 12
    next_month = (total % 12) + 1
    return next_year, next_month


def _normalize_two_digit_year(year: int) -> int:
    return 2000 + year if year < 100 else year


def _parse_report_query(query: str, today: date) -> tuple[int | None, int | None, int | None, int | None, str | None]:
    normalized = query.strip()
    if not normalized:
        return None, None, None, None, "요청 문장이 비어있어. 예: 2025년 6월 리포트"

    year = None
    month = None
    quarter = None
    half = None
    matched = False

    if "올해" in normalized or "이번해" in normalized or "이번 해" in normalized:
        year = today.year
        matched = True
    if "작년" in normalized or "전년" in normalized:
        year = today.year - 1
        matched = True
    if "내년" in normalized:
        year = today.year + 1
        matched = True

    year_month_match = re.search(r"(\d{2,4})\s*[년\-/\.]\s*(\d{1,2})\s*월?", normalized)
    if year_month_match:
        year = _normalize_two_digit_year(int(year_month_match.group(1)))
        month = int(year_month_match.group(2))
        matched = True

    year_match = re.search(r"(\d{2,4})\s*년", normalized)
    if year_match:
        year = _normalize_two_digit_year(int(year_match.group(1)))
        matched = True

    if "이번달" in normalized or "이번 달" in normalized:
        year = year or today.year
        month = today.month
        matched = True
    if "지난달" in normalized or "지난 달" in normalized or "전월" in normalized:
        base_year = year or today.year
        base_month = today.month
        year, month = _shift_month(base_year, base_month, -1)
        matched = True
    if "다음달" in normalized or "다음 달" in normalized:
        base_year = year or today.year
        base_month = today.month
        year, month = _shift_month(base_year, base_month, 1)
        matched = True

    month_match = re.search(r"(\d{1,2})\s*월", normalized)
    if month_match:
        month = int(month_match.group(1))
        matched = True

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

    quarter_match = re.search(r"(?:Q|q)([1-4])", normalized)
    if quarter_match:
        quarter = int(quarter_match.group(1))
        matched = True
    quarter_ko_match = re.search(r"([1-4])\s*분기", normalized)
    if quarter_ko_match:
        quarter = int(quarter_ko_match.group(1))
        matched = True

    if "상반기" in normalized or "전반기" in normalized:
        year = year or today.year
        half = 1
        matched = True
    if "하반기" in normalized or "후반기" in normalized:
        year = year or today.year
        half = 2
        matched = True

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

    if month is not None and quarter is not None:
        return year, None, None, None, "월과 분기를 동시에 요청할 수 없어. 둘 중 하나만 선택해줘."
    if month is not None and half is not None:
        return year, None, None, None, "월과 반기를 동시에 요청할 수 없어. 둘 중 하나만 선택해줘."
    if quarter is not None and half is not None:
        return year, None, None, None, "분기와 반기를 동시에 요청할 수 없어. 둘 중 하나만 선택해줘."

    if year is None:
        year = today.year

    return year, month, quarter, half, None


def _resolve_period(year: int, month: int | None, quarter: int | None, half: int | None) -> ReportPeriod:
    if sum(value is not None for value in (month, quarter, half)) > 1:
        raise HTTPException(status_code=400, detail="use either month, quarter, or half")

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
            raise HTTPException(status_code=400, detail="half must be 1 or 2")
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


def _merge_expense_summaries(
    summaries: list[dict],
    year: int,
    quarter: int | None,
    half: int | None,
) -> dict:
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


def _build_report(
    db: Session,
    start_date: date | None,
    end_date: date | None,
) -> ReportResponse:
    user = db.query(User).order_by(User.id.asc()).first()
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
        settings=_to_settings_read(setting) if setting else None,
    )


def _aggregate_activity(
    summaries: dict[int, MonthlyReportSummary],
    months: list[int],
) -> ReportActivitySummary:
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


def _build_monthly_summaries(
    db: Session,
    user: User | None,
    year: int,
) -> dict[int, MonthlyReportSummary]:
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


@router.get("/report", response_model=ReportResponse)
def get_report(
    year: int | None = Query(None, ge=1970),
    month: int | None = Query(None, ge=1, le=12),
    db: Session = Depends(get_db),
) -> ReportResponse:
    if month is not None and year is None:
        raise HTTPException(status_code=400, detail="year is required when month is set")

    start_date = None
    end_date = None
    if year is not None:
        if month is None:
            start_date = date(year, 1, 1)
            end_date = date(year + 1, 1, 1)
        else:
            start_date = date(year, month, 1)
            if month == 12:
                end_date = date(year + 1, 1, 1)
            else:
                end_date = date(year, month + 1, 1)

    return _build_report(db, start_date, end_date)


@router.get("/report/yearly", response_model=ReportResponse)
def get_report_yearly(
    year: int = Query(..., ge=1970),
    db: Session = Depends(get_db),
) -> ReportResponse:
    start_date = date(year, 1, 1)
    end_date = date(year + 1, 1, 1)
    return _build_report(db, start_date, end_date)


@router.get("/report/monthly", response_model=ReportResponse)
def get_report_monthly(
    year: int = Query(..., ge=1970),
    month: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
) -> ReportResponse:
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1)
    else:
        end_date = date(year, month + 1, 1)
    return _build_report(db, start_date, end_date)


@router.get("/report/quarterly", response_model=ReportResponse)
def get_report_quarterly(
    year: int = Query(..., ge=1970),
    quarter: int = Query(..., ge=1, le=4),
    db: Session = Depends(get_db),
) -> ReportResponse:
    start_month = (quarter - 1) * 3 + 1
    start_date = date(year, start_month, 1)
    if quarter == 4:
        end_date = date(year + 1, 1, 1)
    else:
        end_date = date(year, start_month + 3, 1)
    return _build_report(db, start_date, end_date)


@router.get("/report/monthly/summary", response_model=List[MonthlyReportSummary])
def get_monthly_report_summary(
    year: int = Query(..., ge=1970),
    db: Session = Depends(get_db),
) -> List[MonthlyReportSummary]:
    user = db.query(User).order_by(User.id.asc()).first()
    summaries = _build_monthly_summaries(db, user, year)
    return [summaries[month] for month in range(1, 13)]


@router.get("/report/quarterly/summary", response_model=List[QuarterlyReportSummary])
def get_quarterly_report_summary(
    year: int = Query(..., ge=1970),
    db: Session = Depends(get_db),
) -> List[QuarterlyReportSummary]:
    user = db.query(User).order_by(User.id.asc()).first()
    monthly = _build_monthly_summaries(db, user, year)
    summaries = []
    for quarter in range(1, 5):
        start_month = (quarter - 1) * 3 + 1
        months = [start_month, start_month + 1, start_month + 2]
        activity = _aggregate_activity(monthly, months)
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
    else:
        start_date = date(year, 1, 1)
        end_date = date(year + 1, 1, 1)

    period = ReportPeriod(
        year=year,
        month=month,
        quarter=quarter,
        start_date=start_date,
        end_date=end_date,
    )

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
            ExternalCashflow.date >= start_date,
            ExternalCashflow.date < end_date,
        )
        .all()
    )
    cashflow_count = len(cashflows)
    cashflow_total = 0.0
    deposit_total = 0.0
    withdrawal_total = 0.0
    for cashflow in cashflows:
        # XIRR Convention: Negative = Deposit (Inflow), Positive = Withdrawal (Outflow)
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

    top_assets = []
    for asset in assets:
        value = asset.amount * asset.current_price
        invested = asset.amount * (asset.purchase_price or asset.current_price)
        unrealized_profit = value - invested
        if invested > 0:
            unrealized_profit_rate = unrealized_profit / invested * 100
        else:
            unrealized_profit_rate = None
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
    today = date.today()
    resolved_year = year
    resolved_month = month
    resolved_quarter = quarter

    if query:
        parsed_year, parsed_month, parsed_quarter, parsed_half, parse_error = _parse_report_query(query, today)
        if parse_error:
            raise HTTPException(status_code=400, detail=parse_error)
        resolved_year = parsed_year or resolved_year or today.year
        resolved_month = parsed_month
        resolved_quarter = parsed_quarter
        resolved_half = parsed_half
    else:
        resolved_half = None

    if resolved_year is None:
        raise HTTPException(status_code=400, detail="연도 정보가 필요해. 예: 2025년 6월 리포트")

    if resolved_month is not None and not (1 <= resolved_month <= 12):
        raise HTTPException(status_code=400, detail="월 값이 이상해. 1~12월로 입력해줘.")
    if resolved_quarter is not None and not (1 <= resolved_quarter <= 4):
        raise HTTPException(status_code=400, detail="분기 값이 이상해. 1~4분기로 입력해줘.")

    period = _resolve_period(resolved_year, resolved_month, resolved_quarter, resolved_half)

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
        summaries = [
            get_expense_summary(year=period.year, month=month_item, db=db)
            for month_item in months
        ]
        expense_summary = _merge_expense_summaries(summaries, period.year, period.quarter, None)
    elif period.half is not None:
        months = list(range(1, 7)) if period.half == 1 else list(range(7, 13))
        summaries = [
            get_expense_summary(year=period.year, month=month_item, db=db)
            for month_item in months
        ]
        expense_summary = _merge_expense_summaries(summaries, period.year, None, period.half)
    else:
        expense_summary = get_expense_summary(year=period.year, month=period.month, db=db)

    payload = {
        "period": period.model_dump(mode="json"),
        "portfolio_refined": refined,
        "expense_summary": expense_summary,
    }
    prompt = f"아래 데이터로 리포트를 작성해.\n\n{json.dumps(payload, ensure_ascii=False, default=str)}"

    base_url = os.getenv("AI_REPORT_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    api_key = os.getenv("AI_REPORT_API_KEY")
    default_model = os.getenv("AI_REPORT_MODEL", "gpt-5.2")
    yearly_model = os.getenv("AI_REPORT_MODEL_YEARLY", "gpt-5.2-pro")
    temperature = float(os.getenv("AI_REPORT_TEMPERATURE", "0.3"))
    default_tokens = int(os.getenv("AI_REPORT_MAX_TOKENS", "8000"))

    if not api_key:
        raise HTTPException(status_code=500, detail="AI_REPORT_API_KEY is not configured")

    selected_model = model or (
        yearly_model if period.month is None and period.quarter is None and period.half is None else default_model
    )
    selected_tokens = max_tokens or default_tokens

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
                    {"role": "system", "content": _AI_REPORT_SYSTEM_PROMPT},
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
        raise HTTPException(
            status_code=502,
            detail=f"AI report request failed: {response.text}",
        )

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


@router.get("/report/refined")
def get_refined_report(
    year: int | None = Query(None, ge=1970),
    month: int | None = Query(None, ge=1, le=12),
    quarter: int | None = Query(None, ge=1, le=4),
) -> dict:
    """
    DuckDB 기반 고성능 분석 레이어를 통해 정제된 포트폴리오 데이터를 반환합니다.

    이 엔드포인트는 로컬 AI가 포트폴리오 분석 리포트를 생성할 때 사용하기에
    최적화된 구조로 데이터를 전처리하여 반환합니다.

    - 카테고리/지수 그룹별 비중 분석
    - 자산별 수익률 및 상세 메트릭
    - 월별 트렌드 데이터
    - 입출금 요약
    - 통화별 노출도

    모든 계산은 DuckDB의 컬럼 기반 분석 엔진으로 수행되어 빠릅니다.
    """
    from ..services.duckdb_refine import refine_portfolio_for_ai

    if month is not None and quarter is not None:
        raise HTTPException(status_code=400, detail="use either month or quarter, not both")

    try:
        return refine_portfolio_for_ai(year=year, month=month, quarter=quarter)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"DuckDB refinement failed: {exc}") from exc


# --- Saved AI Reports ---


@router.get("/report/saved")
def get_saved_reports(
    db: Session = Depends(get_db),
) -> list[dict]:
    """저장된 AI 리포트 목록 조회 (최신순)"""
    user = db.query(User).order_by(User.id.asc()).first()
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


@router.post("/report/saved")
def save_report(
    payload: dict,
    db: Session = Depends(get_db),
) -> dict:
    """AI 리포트 저장"""
    user = db.query(User).order_by(User.id.asc()).first()
    if not user:
        raise HTTPException(status_code=400, detail="사용자가 없습니다.")

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


@router.delete("/report/saved/{report_id}")
def delete_saved_report(
    report_id: int,
    db: Session = Depends(get_db),
) -> dict:
    """저장된 AI 리포트 삭제"""
    user = db.query(User).order_by(User.id.asc()).first()
    if not user:
        raise HTTPException(status_code=400, detail="사용자가 없습니다.")

    report = (
        db.query(AiReport)
        .filter(AiReport.id == report_id, AiReport.user_id == user.id)
        .first()
    )
    if not report:
        raise HTTPException(status_code=404, detail="리포트를 찾을 수 없습니다.")

    db.delete(report)
    db.commit()

    return {"message": "삭제되었습니다.", "id": report_id}
