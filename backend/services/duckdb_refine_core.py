from __future__ import annotations

from datetime import date
from typing import Any

import duckdb

from .duckdb_refine_config import get_db_path
from .duckdb_refine_queries import (
    ASSET_FILTER,
    fetch_asset_analytics,
    fetch_benchmark_info,
    fetch_cashflow_summary,
    fetch_category_breakdown,
    fetch_category_trade_impact,
    fetch_currency_exposure,
    fetch_dividend_summary,
    fetch_expense_summary,
    fetch_index_breakdown,
    fetch_index_trade_impact,
    fetch_monthly_trend_raw,
    fetch_news_context,
    fetch_portfolio_summary,
    fetch_prev_snapshot,
    fetch_spending_by_category,
    fetch_top_spending_items,
    fetch_trade_activity,
    to_dict_list,
)
from .reporting.periods import format_period_label, is_historical_period, resolve_period


def refine_portfolio_for_ai(
    year: int | None = None,
    month: int | None = None,
    quarter: int | None = None,
    half: int | None = None,
) -> dict[str, Any]:
    """
    Refine portfolio data using DuckDB for AI consumption.

    This function reads data from the SQLite database, processes it using
    DuckDB's analytical engine, and returns a refined, AI-friendly structure
    with pre-calculated metrics.
    """
    if year is None:
        year = date.today().year

    period = resolve_period(year, month, quarter, half)
    period_label = format_period_label(period)

    # Determine if we're analyzing a historical period
    is_historical = is_historical_period(period)

    # Connect to DuckDB (in-memory) and attach SQLite
    db_path = get_db_path()
    con = duckdb.connect(":memory:")
    escaped_path = db_path.replace("'", "''")
    con.execute(f"ATTACH '{escaped_path}' AS sqlite_db (TYPE SQLITE, READ_ONLY)")

    try:
        # ========== Portfolio Summary (Operational Assets Only) ==========
        portfolio_summary = fetch_portfolio_summary(con, ASSET_FILTER)

        # ========== Asset Analytics (CURRENT STATE, Top 20 by value) ==========
        asset_analytics, asset_columns = fetch_asset_analytics(con, ASSET_FILTER)

        # ========== Category Breakdown ==========
        category_breakdown, category_columns = fetch_category_breakdown(con, ASSET_FILTER)

        # ========== Index Group Breakdown ==========
        index_breakdown, index_columns = fetch_index_breakdown(con, ASSET_FILTER)

        # ========== Trade Activity (within period) ==========
        trade_activity, trade_columns = fetch_trade_activity(con, period.start_date, period.end_date)

        # ========== Trade Impact by Category / Index Group ==========
        category_trade_impact, category_trade_columns = fetch_category_trade_impact(
            con, period.start_date, period.end_date
        )
        index_trade_impact, index_trade_columns = fetch_index_trade_impact(
            con, period.start_date, period.end_date
        )

        # ========== Cashflow Summary (within period) ==========
        cashflow_summary = fetch_cashflow_summary(con, period.start_date, period.end_date)

        # ========== Dividend Summary ==========
        dividend_summary = fetch_dividend_summary(con, period.start_date, period.end_date)

        # ========== Monthly Snapshot Trend (with comparison) ==========
        prev_snapshot = fetch_prev_snapshot(con, period.start_date)
        prev_value = prev_snapshot[0] if prev_snapshot else 0
        prev_invested = prev_snapshot[1] if prev_snapshot else 0

        monthly_trend_raw = fetch_monthly_trend_raw(con, period.start_date, period.end_date)
        monthly_trend = []
        current_prev_val = prev_value
        current_prev_inv = prev_invested

        for row in monthly_trend_raw:
            m_val = row[1]
            m_inv = row[2]
            monthly_trend.append(
                {
                    "month": row[0],
                    "start_value": current_prev_val,
                    "end_value": m_val,
                    "start_invested": current_prev_inv,
                    "end_invested": m_inv,
                    "unrealized_pnl_at_end": row[3],
                    "value_change": m_val - current_prev_val,
                    "invested_change": m_inv - current_prev_inv,
                }
            )
            current_prev_val = m_val
            current_prev_inv = m_inv

        # ========== Currency Exposure ==========
        currency_exposure, currency_columns = fetch_currency_exposure(con, ASSET_FILTER)

        # ========== Expense/Income Summary (from bank records) ==========
        expense_summary = fetch_expense_summary(con, period.start_date, period.end_date)

        # ========== Spending by Category ==========
        spending_by_category, spending_columns = fetch_spending_by_category(
            con, period.start_date, period.end_date
        )

        # ========== Top Spending Items ==========
        top_spending_items, item_columns = fetch_top_spending_items(
            con, period.start_date, period.end_date
        )

        # ========== Benchmark Info ==========
        benchmark_info = fetch_benchmark_info(con)

        # ========== News Context (Economy/Finance) ==========
        news_context, news_columns = fetch_news_context(con, period.start_date, period.end_date)
    finally:
        con.close()

    total_value = portfolio_summary[1] if portfolio_summary else 0
    total_invested = portfolio_summary[2] if portfolio_summary else 0
    portfolio_return_pct = None
    if total_invested:
        portfolio_return_pct = round((total_value / total_invested - 1) * 100, 2)

    benchmark_name = benchmark_info[0] if benchmark_info else None
    benchmark_return = benchmark_info[1] if benchmark_info else None
    benchmark_updated_at = None
    if benchmark_info and benchmark_info[2]:
        raw_updated_at = benchmark_info[2]
        benchmark_updated_at = raw_updated_at.isoformat() if hasattr(raw_updated_at, "isoformat") else str(raw_updated_at)
    benchmark_diff_pct = None
    if portfolio_return_pct is not None and benchmark_return is not None:
        benchmark_diff_pct = round(portfolio_return_pct - benchmark_return, 2)

    return {
        "refined_by": "DuckDB",
        "_important_note": (
            "portfolio_summary and asset_analytics show CURRENT holdings, NOT holdings during the analysis period. "
            "For period-specific data, use trade_activity, cashflow_summary, expense_summary, and monthly_trend."
        )
        if is_historical
        else None,
        "period": {
            "label": period_label,
            "year": period.year,
            "month": period.month,
            "quarter": period.quarter,
            "half": period.half,
            "start_date": str(period.start_date),
            "end_date": str(period.end_date),
            "is_historical_period": is_historical,
        },
        "portfolio_summary": {
            "_note": (
                "현재 운용 포트폴리오 상태(부동산 제외)이며, 요청 기간과는 무관합니다."
                if is_historical
                else "운용 포트폴리오 기준(부동산 제외)입니다."
            ),
            "total_assets": portfolio_summary[0] if portfolio_summary else 0,
            "total_value": total_value,
            "total_invested": total_invested,
            "total_realized_profit": portfolio_summary[3] if portfolio_summary else 0,
            "total_unrealized_profit": portfolio_summary[4] if portfolio_summary else 0,
        },
        "benchmark": {
            "name": benchmark_name,
            "return_pct": benchmark_return,
            "updated_at": benchmark_updated_at,
            "portfolio_return_pct": portfolio_return_pct,
            "diff_pct": benchmark_diff_pct,
        },
        "asset_analytics": to_dict_list(asset_analytics, asset_columns),
        "category_breakdown": [
            {**d, "weight_pct": round(d["total_value"] / total_value * 100, 2) if total_value > 0 else 0}
            for d in to_dict_list(category_breakdown, category_columns)
        ],
        "index_breakdown": [
            {**d, "weight_pct": round(d["total_value"] / total_value * 100, 2) if total_value > 0 else 0}
            for d in to_dict_list(index_breakdown, index_columns)
        ],
        "trade_activity": {
            "_note": f"Trade activity during {period_label}",
            "data": to_dict_list(trade_activity, trade_columns),
        },
        "category_trade_impact": to_dict_list(category_trade_impact, category_trade_columns),
        "index_trade_impact": to_dict_list(index_trade_impact, index_trade_columns),
        "cashflow_summary": {
            "_note": f"Cashflow activity during {period_label}",
            "total_transactions": cashflow_summary[0] if cashflow_summary else 0,
            "total_deposits": cashflow_summary[1] if cashflow_summary else 0,
            "total_withdrawals": cashflow_summary[2] if cashflow_summary else 0,
            "net_flow": cashflow_summary[3] if cashflow_summary else 0,
            "total_dividends": dividend_summary[0] if dividend_summary else 0,
        },
        "expense_summary": {
            "_note": f"Income and spending during {period_label}",
            "total_income": expense_summary[0] if expense_summary else 0,
            "total_spending": expense_summary[1] if expense_summary else 0,
            "net_savings": (expense_summary[0] - expense_summary[1]) if expense_summary else 0,
        },
        "spending_by_category": to_dict_list(spending_by_category, spending_columns),
        "top_spending_items": to_dict_list(top_spending_items, item_columns),
        "monthly_trend": monthly_trend,
        "currency_exposure": [
            {**d, "weight_pct": round(d["total_value"] / total_value * 100, 2) if total_value > 0 else 0}
            for d in to_dict_list(currency_exposure, currency_columns)
        ],
        "news_context": to_dict_list(news_context, news_columns),
    }
