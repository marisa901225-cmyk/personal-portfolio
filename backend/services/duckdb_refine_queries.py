from __future__ import annotations

from datetime import date
from typing import Iterable

ASSET_FILTER = "deleted_at IS NULL AND (category IS NULL OR category != '부동산')"


def to_dict_list(rows: Iterable[tuple], columns: list[str]) -> list[dict]:
    return [dict(zip(columns, row)) for row in rows]


def fetch_portfolio_summary(con, asset_filter: str = ASSET_FILTER) -> tuple | None:
    return con.execute(
        f"""
        SELECT
            COUNT(*) as total_assets,
            COALESCE(SUM(amount * current_price), 0) as total_value,
            COALESCE(SUM(amount * COALESCE(purchase_price, current_price)), 0) as total_invested,
            COALESCE(SUM(realized_profit), 0) as total_realized_profit,
            COALESCE(SUM(amount * current_price) - SUM(amount * COALESCE(purchase_price, current_price)), 0) as total_unrealized_profit
        FROM sqlite_db.assets
        WHERE {asset_filter}
        """
    ).fetchone()


def fetch_asset_analytics(con, asset_filter: str = ASSET_FILTER) -> tuple[list[tuple], list[str]]:
    rows = con.execute(
        f"""
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
        WHERE {asset_filter}
        ORDER BY current_value DESC
        LIMIT 20
        """
    ).fetchall()

    columns = [
        "id", "name", "ticker", "category", "currency", "amount",
        "current_price", "purchase_price", "current_value", "invested_value",
        "unrealized_pnl", "return_pct", "realized_profit", "index_group",
    ]
    return rows, columns


def fetch_category_breakdown(con, asset_filter: str = ASSET_FILTER) -> tuple[list[tuple], list[str]]:
    rows = con.execute(
        f"""
        SELECT
            category,
            COUNT(*) as asset_count,
            SUM(amount * current_price) as total_value,
            SUM(amount * COALESCE(purchase_price, current_price)) as total_invested,
            SUM(amount * current_price) - SUM(amount * COALESCE(purchase_price, current_price)) as unrealized_pnl
        FROM sqlite_db.assets
        WHERE {asset_filter}
        GROUP BY category
        ORDER BY total_value DESC
        """
    ).fetchall()

    columns = ["category", "asset_count", "total_value", "total_invested", "unrealized_pnl"]
    return rows, columns


def fetch_index_breakdown(con, asset_filter: str = ASSET_FILTER) -> tuple[list[tuple], list[str]]:
    rows = con.execute(
        f"""
        SELECT
            COALESCE(index_group, '미분류') as index_group,
            COUNT(*) as asset_count,
            SUM(amount * current_price) as total_value
        FROM sqlite_db.assets
        WHERE {asset_filter}
        GROUP BY index_group
        ORDER BY total_value DESC
        """
    ).fetchall()

    columns = ["index_group", "asset_count", "total_value"]
    return rows, columns


def fetch_trade_activity(con, start_date: date, end_date: date) -> tuple[list[tuple], list[str]]:
    rows = con.execute(
        f"""
        SELECT
            type,
            COUNT(*) as trade_count,
            SUM(quantity * price) as total_value,
            SUM(COALESCE(realized_delta, 0)) as realized_pnl
        FROM sqlite_db.trades
        WHERE timestamp >= '{start_date}' AND timestamp < '{end_date}'
        GROUP BY type
        """
    ).fetchall()
    columns = ["type", "trade_count", "total_value", "realized_pnl"]
    return rows, columns


def fetch_category_trade_impact(con, start_date: date, end_date: date) -> tuple[list[tuple], list[str]]:
    rows = con.execute(
        f"""
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
        """
    ).fetchall()

    columns = ["category", "trade_count", "buy_value", "sell_value", "net_value", "realized_pnl"]
    return rows, columns


def fetch_index_trade_impact(con, start_date: date, end_date: date) -> tuple[list[tuple], list[str]]:
    rows = con.execute(
        f"""
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
        """
    ).fetchall()

    columns = ["index_group", "trade_count", "buy_value", "sell_value", "net_value", "realized_pnl"]
    return rows, columns


def fetch_cashflow_summary(con, start_date: date, end_date: date) -> tuple | None:
    return con.execute(
        f"""
        SELECT
            COUNT(*) as total_transactions,
            SUM(CASE WHEN amount < 0 AND description NOT LIKE '%배당%' AND description NOT LIKE '%DIV%' THEN ABS(amount) ELSE 0 END) as total_deposits,
            SUM(CASE WHEN amount >= 0 THEN amount ELSE 0 END) as total_withdrawals,
            SUM(amount) as net_flow
        FROM sqlite_db.external_cashflows
        WHERE date >= '{start_date}' AND date < '{end_date}'
        """
    ).fetchone()


def fetch_dividend_summary(con, start_date: date, end_date: date) -> tuple | None:
    return con.execute(
        f"""
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
        """
    ).fetchone()


def fetch_prev_snapshot(con, start_date: date) -> tuple | None:
    return con.execute(
        f"""
        SELECT total_value, total_invested, unrealized_profit_total
        FROM sqlite_db.portfolio_snapshots
        WHERE snapshot_at < '{start_date}'
        ORDER BY snapshot_at DESC
        LIMIT 1
        """
    ).fetchone()


def fetch_monthly_trend_raw(con, start_date: date, end_date: date) -> list[tuple]:
    return con.execute(
        f"""
        SELECT
            strftime('%Y-%m', snapshot_at) as month,
            MAX(total_value) as end_value,
            MAX(total_invested) as end_invested,
            MAX(unrealized_profit_total) as unrealized_pnl
        FROM sqlite_db.portfolio_snapshots
        WHERE snapshot_at >= '{start_date}' AND snapshot_at < '{end_date}'
        GROUP BY strftime('%Y-%m', snapshot_at)
        ORDER BY month
        """
    ).fetchall()


def fetch_currency_exposure(con, asset_filter: str = ASSET_FILTER) -> tuple[list[tuple], list[str]]:
    rows = con.execute(
        f"""
        SELECT
            currency,
            COUNT(*) as asset_count,
            SUM(amount * current_price) as total_value
        FROM sqlite_db.assets
        WHERE {asset_filter}
        GROUP BY currency
        """
    ).fetchall()

    columns = ["currency", "asset_count", "total_value"]
    return rows, columns


def fetch_expense_summary(con, start_date: date, end_date: date) -> tuple | None:
    return con.execute(
        f"""
        SELECT
            COALESCE(SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END), 0) as total_income,
            COALESCE(SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END), 0) as total_spending
        FROM sqlite_db.expenses
        WHERE date >= '{start_date}' AND date < '{end_date}'
        AND deleted_at IS NULL
        """
    ).fetchone()


def fetch_spending_by_category(con, start_date: date, end_date: date) -> tuple[list[tuple], list[str]]:
    rows = con.execute(
        f"""
        SELECT
            category,
            SUM(ABS(amount)) as total_amount
        FROM sqlite_db.expenses
        WHERE date >= '{start_date}' AND date < '{end_date}' AND amount < 0
        AND deleted_at IS NULL
        GROUP BY category
        ORDER BY total_amount DESC
        """
    ).fetchall()
    columns = ["category", "total_amount"]
    return rows, columns


def fetch_top_spending_items(con, start_date: date, end_date: date) -> tuple[list[tuple], list[str]]:
    rows = con.execute(
        f"""
        SELECT
            merchant,
            amount,
            category,
            date
        FROM sqlite_db.expenses
        WHERE date >= '{start_date}' AND date < '{end_date}' AND amount < 0
        AND deleted_at IS NULL
        ORDER BY amount ASC
        LIMIT 10
        """
    ).fetchall()
    columns = ["merchant", "amount", "category", "date"]
    return rows, columns


def fetch_benchmark_info(con) -> tuple | None:
    return con.execute(
        """
        SELECT
            benchmark_name,
            benchmark_return,
            benchmark_updated_at
        FROM sqlite_db.settings
        ORDER BY id ASC
        LIMIT 1
        """
    ).fetchone()


def fetch_news_context(con, start_date: date, end_date: date) -> tuple[list[tuple], list[str]]:
    rows = con.execute(
        f"""
        SELECT
            strftime(published_at, '%m/%d %H:%M') as time,
            game_tag,
            title
        FROM sqlite_db.game_news
        WHERE published_at >= '{start_date}' AND published_at < '{end_date}'
          AND game_tag IN ('Economy', 'Tech/Semiconductor', 'FX', 'Fed/Macro', 'LoL', 'Valorant')
        ORDER BY published_at DESC
        LIMIT 20
        """
    ).fetchall()
    columns = ["time", "tag", "title"]
    return rows, columns
