from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from ...core.models import (
    Asset,
    ExternalCashflow,
    FxTransaction,
    PortfolioSnapshot,
    Setting,
    Trade,
    User,
)
from ...core.schemas import (
    ExternalCashflowRead,
    MonthlyReportSummary,
    PortfolioResponse,
    QuarterlyReportSummary,
    ReportActivitySummary,
    ReportResponse,
)
from ...services.portfolio import (
    calculate_summary,
    to_asset_read,
    to_fx_transaction_read,
    to_snapshot_read,
    to_trade_read,
)
from ...services.settings_service import to_settings_read
from .periods import resolve_period


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
    if year is None:
        return build_report(db, None, None)

    period = resolve_period(year, month, quarter, None)
    return build_report(db, period.start_date, period.end_date)


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
