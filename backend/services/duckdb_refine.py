"""
DuckDB-based analytical data refinement service.

This module provides a high-performance analytical layer between the SQLite
operational database and AI report generation. It uses DuckDB's columnar
processing to efficiently compute complex aggregations and metrics.
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any

import duckdb

# Default path to the SQLite database
_DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "storage" / "db" / "portfolio.db"


def get_db_path() -> str:
    """Return the path to the SQLite database file."""
    return os.environ.get("DATABASE_PATH", str(_DEFAULT_DB_PATH))


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

    Args:
        year: Optional year filter (defaults to current year)
        month: Optional month filter (1-12)
        quarter: Optional quarter filter (1-4)

    Returns:
        A dictionary containing refined portfolio analytics:
        - period: Time period information
        - portfolio_summary: High-level portfolio metrics
        - asset_analytics: Per-asset performance breakdown
        - monthly_trend: Time-series data for trends
        - category_breakdown: Allocation by category
        - cashflow_summary: Deposit/withdrawal analysis
    """
    db_path = get_db_path()

    # Determine date range
    if year is None:
        year = date.today().year

    if month is not None:
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1)
        else:
            end_date = date(year, month + 1, 1)
        period_label = f"{year}-{month:02d}"
    elif quarter is not None:
        start_month = (quarter - 1) * 3 + 1
        start_date = date(year, start_month, 1)
        if quarter == 4:
            end_date = date(year + 1, 1, 1)
        else:
            end_date = date(year, start_month + 3, 1)
        period_label = f"{year} Q{quarter}"
    elif half is not None:
        if half == 1:
            start_date = date(year, 1, 1)
            end_date = date(year, 7, 1)
            period_label = f"{year} H1"
        else:
            start_date = date(year, 7, 1)
            end_date = date(year + 1, 1, 1)
            period_label = f"{year} H2"
    else:
        start_date = date(year, 1, 1)
        end_date = date(year + 1, 1, 1)
        period_label = str(year)

    # Connect to DuckDB (in-memory) and attach SQLite
    # Escape single quotes in path to prevent SQL syntax errors
    con = duckdb.connect(":memory:")
    escaped_path = db_path.replace("'", "''")
    con.execute(f"ATTACH '{escaped_path}' AS sqlite_db (TYPE SQLITE, READ_ONLY)")

    # Determine if we're analyzing a historical period
    is_historical = month is not None or quarter is not None or half is not None or year != date.today().year

    asset_filter = "deleted_at IS NULL AND (category IS NULL OR category != '부동산')"

    # ========== Portfolio Summary (Operational Assets Only) ==========
    # Exclude real estate from operational portfolio to avoid report pollution.
    portfolio_summary = con.execute(f"""
        SELECT
            COUNT(*) as total_assets,
            COALESCE(SUM(amount * current_price), 0) as total_value,
            COALESCE(SUM(amount * COALESCE(purchase_price, current_price)), 0) as total_invested,
            COALESCE(SUM(realized_profit), 0) as total_realized_profit,
            COALESCE(SUM(amount * current_price) - SUM(amount * COALESCE(purchase_price, current_price)), 0) as total_unrealized_profit
        FROM sqlite_db.assets
        WHERE {asset_filter}
    """).fetchone()

    # ========== Asset Analytics (CURRENT STATE, Top 20 by value) ==========
    # ⚠️ NOTE: Shows CURRENT portfolio holdings, NOT holdings during the specified period
    # Individual asset snapshots are not stored historically
    asset_analytics = con.execute("""
        SELECT
            id,
            name,
            ticker,
            category,
            currency,
            amount,
            current_price,
            purchase_price,
            amount * current_price as current_value,
            amount * COALESCE(purchase_price, current_price) as invested_value,
            (amount * current_price) - (amount * COALESCE(purchase_price, current_price)) as unrealized_pnl,
            CASE
                WHEN amount * COALESCE(purchase_price, current_price) > 0
                THEN ((amount * current_price) / (amount * COALESCE(purchase_price, current_price)) - 1) * 100
                ELSE 0
            END as return_pct,
            realized_profit,
            index_group
        FROM sqlite_db.assets
        WHERE deleted_at IS NULL AND (category IS NULL OR category != '부동산')
        ORDER BY current_value DESC
        LIMIT 20
    """).fetchall()

    asset_columns = [
        "id", "name", "ticker", "category", "currency", "amount",
        "current_price", "purchase_price", "current_value", "invested_value",
        "unrealized_pnl", "return_pct", "realized_profit", "index_group"
    ]

    # ========== Category Breakdown ==========
    category_breakdown = con.execute("""
        SELECT
            category,
            COUNT(*) as asset_count,
            SUM(amount * current_price) as total_value,
            SUM(amount * COALESCE(purchase_price, current_price)) as total_invested,
            SUM(amount * current_price) - SUM(amount * COALESCE(purchase_price, current_price)) as unrealized_pnl
        FROM sqlite_db.assets
        WHERE deleted_at IS NULL AND (category IS NULL OR category != '부동산')
        GROUP BY category
        ORDER BY total_value DESC
    """).fetchall()

    category_columns = ["category", "asset_count", "total_value", "total_invested", "unrealized_pnl"]

    # ========== Index Group Breakdown ==========
    index_breakdown = con.execute("""
        SELECT
            COALESCE(index_group, '미분류') as index_group,
            COUNT(*) as asset_count,
            SUM(amount * current_price) as total_value
        FROM sqlite_db.assets
        WHERE deleted_at IS NULL AND (category IS NULL OR category != '부동산')
        GROUP BY index_group
        ORDER BY total_value DESC
    """).fetchall()

    index_columns = ["index_group", "asset_count", "total_value"]

    # ========== Trade Activity (within period) ==========
    trade_activity = con.execute(f"""
        SELECT
            type,
            COUNT(*) as trade_count,
            SUM(quantity * price) as total_value,
            SUM(COALESCE(realized_delta, 0)) as realized_pnl
        FROM sqlite_db.trades
        WHERE timestamp >= '{start_date}' AND timestamp < '{end_date}'
        GROUP BY type
    """).fetchall()

    trade_columns = ["type", "trade_count", "total_value", "realized_pnl"]

    # ========== Trade Impact by Category / Index Group ==========
    category_trade_impact = con.execute(f"""
        SELECT
            COALESCE(a.category, '미분류') as category,
            COUNT(*) as trade_count,
            SUM(CASE WHEN t.type = 'BUY' THEN t.quantity * t.price ELSE 0 END) as buy_value,
            SUM(CASE WHEN t.type = 'SELL' THEN t.quantity * t.price ELSE 0 END) as sell_value,
            SUM(COALESCE(t.realized_delta, 0)) as realized_pnl,
            SUM(CASE WHEN t.type = 'BUY' THEN t.quantity * t.price ELSE 0 END)
            - SUM(CASE WHEN t.type = 'SELL' THEN t.quantity * t.price ELSE 0 END) as net_value
        FROM sqlite_db.trades t
        LEFT JOIN sqlite_db.assets a ON t.asset_id = a.id
        WHERE t.timestamp >= '{start_date}' AND t.timestamp < '{end_date}'
          AND t.type IN ('BUY', 'SELL')
        GROUP BY COALESCE(a.category, '미분류')
        ORDER BY (buy_value + sell_value) DESC
    """).fetchall()

    category_trade_columns = [
        "category", "trade_count", "buy_value", "sell_value", "net_value", "realized_pnl"
    ]

    index_trade_impact = con.execute(f"""
        SELECT
            COALESCE(a.index_group, '미분류') as index_group,
            COUNT(*) as trade_count,
            SUM(CASE WHEN t.type = 'BUY' THEN t.quantity * t.price ELSE 0 END) as buy_value,
            SUM(CASE WHEN t.type = 'SELL' THEN t.quantity * t.price ELSE 0 END) as sell_value,
            SUM(COALESCE(t.realized_delta, 0)) as realized_pnl,
            SUM(CASE WHEN t.type = 'BUY' THEN t.quantity * t.price ELSE 0 END)
            - SUM(CASE WHEN t.type = 'SELL' THEN t.quantity * t.price ELSE 0 END) as net_value
        FROM sqlite_db.trades t
        LEFT JOIN sqlite_db.assets a ON t.asset_id = a.id
        WHERE t.timestamp >= '{start_date}' AND t.timestamp < '{end_date}'
          AND t.type IN ('BUY', 'SELL')
        GROUP BY COALESCE(a.index_group, '미분류')
        ORDER BY (buy_value + sell_value) DESC
    """).fetchall()

    index_trade_columns = [
        "index_group", "trade_count", "buy_value", "sell_value", "net_value", "realized_pnl"
    ]

    # ========== Cashflow Summary (within period) ==========
    # XIRR convention: negative = deposits (money into portfolio), positive = withdrawals (money out)
    cashflow_summary = con.execute(f"""
        SELECT
            COUNT(*) as total_transactions,
            SUM(CASE WHEN amount < 0 AND description NOT LIKE '%배당%' AND description NOT LIKE '%DIV%' THEN ABS(amount) ELSE 0 END) as total_deposits,
            SUM(CASE WHEN amount >= 0 THEN amount ELSE 0 END) as total_withdrawals,
            SUM(amount) as net_flow
        FROM sqlite_db.external_cashflows
        WHERE date >= '{start_date}' AND date < '{end_date}'
    """).fetchone()

    # ========== Dividend Summary ==========
    # Look for dividends in:
    # 1. external_cashflows (inflows with '배당' or 'DIV')
    # 2. trades (type = 'DIVIDEND')
    dividend_summary = con.execute(f"""
        SELECT COALESCE(SUM(amount), 0) FROM (
            SELECT ABS(amount) as amount FROM sqlite_db.external_cashflows
            WHERE date >= '{start_date}' AND date < '{end_date}'
            AND (description LIKE '%배당%' OR description LIKE '%DIV%')
            AND amount < 0
            UNION ALL
            SELECT (quantity * price) as amount FROM sqlite_db.trades
            WHERE timestamp >= '{start_date}' AND timestamp < '{end_date}'
            AND type = 'DIVIDEND'
        )
    """).fetchone()

    # ========== Monthly Snapshot Trend (with comparison) ==========
    # To calculate performance, we also need the snapshot just BEFORE the start_date
    prev_snapshot = con.execute(f"""
        SELECT total_value, total_invested, unrealized_profit_total
        FROM sqlite_db.portfolio_snapshots
        WHERE snapshot_at < '{start_date}'
        ORDER BY snapshot_at DESC
        LIMIT 1
    """).fetchone()
    
    prev_value = prev_snapshot[0] if prev_snapshot else 0
    prev_invested = prev_snapshot[1] if prev_snapshot else 0

    monthly_trend_raw = con.execute(f"""
        SELECT
            strftime('%Y-%m', snapshot_at) as month,
            MAX(total_value) as end_value,
            MAX(total_invested) as end_invested,
            MAX(unrealized_profit_total) as unrealized_pnl
        FROM sqlite_db.portfolio_snapshots
        WHERE snapshot_at >= '{start_date}' AND snapshot_at < '{end_date}'
        GROUP BY strftime('%Y-%m', snapshot_at)
        ORDER BY month
    """).fetchall()

    monthly_trend = []
    current_prev_val = prev_value
    current_prev_inv = prev_invested
    
    for row in monthly_trend_raw:
        m_val = row[1]
        m_inv = row[2]
        monthly_trend.append({
            "month": row[0],
            "start_value": current_prev_val,
            "end_value": m_val,
            "start_invested": current_prev_inv,
            "end_invested": m_inv,
            "unrealized_pnl_at_end": row[3],
            "value_change": m_val - current_prev_val,
            "invested_change": m_inv - current_prev_inv
        })
        current_prev_val = m_val
        current_prev_inv = m_inv

    # No need for to_dict_list for monthly_trend as it's already a list of dicts
    # trend_columns = ["month", "end_value", "end_invested", "unrealized_pnl"]

    # ========== Currency Exposure ==========
    currency_exposure = con.execute("""
        SELECT
            currency,
            COUNT(*) as asset_count,
            SUM(amount * current_price) as total_value
        FROM sqlite_db.assets
        WHERE deleted_at IS NULL AND (category IS NULL OR category != '부동산')
        GROUP BY currency
    """).fetchall()

    currency_columns = ["currency", "asset_count", "total_value"]

    # ========== Expense/Income Summary (from bank records) ==========
    # In 'expenses' table: positive = income (salary, etc.), negative = spending (shopping, etc.)
    expense_summary = con.execute(f"""
        SELECT
            COALESCE(SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END), 0) as total_income,
            COALESCE(SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END), 0) as total_spending
        FROM sqlite_db.expenses
        WHERE date >= '{start_date}' AND date < '{end_date}'
        AND deleted_at IS NULL
    """).fetchone()

    # ========== Spending by Category ==========
    spending_by_category = con.execute(f"""
        SELECT
            category,
            SUM(ABS(amount)) as total_amount
        FROM sqlite_db.expenses
        WHERE date >= '{start_date}' AND date < '{end_date}' AND amount < 0
        AND deleted_at IS NULL
        GROUP BY category
        ORDER BY total_amount DESC
    """).fetchall()
    spending_columns = ["category", "total_amount"]
    
    # ========== Top Spending Items (Detailed roasting) ==========
    top_spending_items = con.execute(f"""
        SELECT
            merchant,
            amount,
            category,
            date
        FROM sqlite_db.expenses
        WHERE date >= '{start_date}' AND date < '{end_date}' AND amount < 0
        AND deleted_at IS NULL
        ORDER BY amount ASC  -- Largest negative first
        LIMIT 10
    """).fetchall()
    item_columns = ["merchant", "amount", "category", "date"]

    # ========== Benchmark Info ==========
    benchmark_info = con.execute("""
        SELECT
            benchmark_name,
            benchmark_return,
            benchmark_updated_at
        FROM sqlite_db.settings
        ORDER BY id ASC
        LIMIT 1
    """).fetchone()
    
    # ========== News Context (Economy/Finance) ==========
    news_context = con.execute(f"""
        SELECT 
            strftime(published_at, '%m/%d %H:%M') as time,
            game_tag,
            title
        FROM sqlite_db.game_news
        WHERE published_at >= '{start_date}' AND published_at < '{end_date}'
          AND game_tag IN ('Economy', 'Tech/Semiconductor', 'FX', 'Fed/Macro', 'LoL', 'Valorant')
        ORDER BY published_at DESC
        LIMIT 20
    """).fetchall()
    news_columns = ["time", "tag", "title"]

    con.close()

    # Build response
    def to_dict_list(rows, columns):
        return [dict(zip(columns, row)) for row in rows]

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
        "_important_note": "portfolio_summary and asset_analytics show CURRENT holdings, NOT holdings during the analysis period. For period-specific data, use trade_activity, cashflow_summary, expense_summary, and monthly_trend." if is_historical else None,
        "period": {
            "label": period_label,
            "year": year,
            "month": month,
            "quarter": quarter,
            "half": half,
            "start_date": str(start_date),
            "end_date": str(end_date),
            "is_historical_period": is_historical,
        },
        "portfolio_summary": {
            "_note": "현재 운용 포트폴리오 상태(부동산 제외)이며, 요청 기간과는 무관합니다." if is_historical else "운용 포트폴리오 기준(부동산 제외)입니다.",
            "total_assets": portfolio_summary[0] if portfolio_summary else 0,
            "total_value": portfolio_summary[1] if portfolio_summary else 0,
            "total_invested": portfolio_summary[2] if portfolio_summary else 0,
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
