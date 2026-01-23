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
    
    # 가맹점명을 카테고리 기반 익명화 (클라우드 LLM 전송 시 개인정보 보호)
    anonymized_rows = []
    category_counters: dict[str, int] = {}
    for row in rows:
        merchant, amount, category, date_val = row
        cat_key = category or "기타"
        category_counters[cat_key] = category_counters.get(cat_key, 0) + 1
        # "카페 A", "식비 B" 형태로 익명화
        label = chr(64 + category_counters[cat_key])  # A, B, C, ...
        anon_merchant = f"{cat_key} {label}"
        anonymized_rows.append((anon_merchant, amount, category, date_val))
    
    columns = ["merchant", "amount", "category", "date"]
    return anonymized_rows, columns



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


# --- News Stats Optimization (OPT-001) ---

def fetch_news_stats_by_tag(con, start_date: date, end_date: date) -> tuple[list[tuple], list[str]]:
    """
    태그별 뉴스 수 집계 (최적화된 쿼리).
    매번 전체 스캔 대신 미리 집계된 결과 반환.
    """
    rows = con.execute(
        f"""
        SELECT
            game_tag,
            COUNT(*) as article_count,
            MIN(published_at) as first_article,
            MAX(published_at) as last_article
        FROM sqlite_db.game_news
        WHERE published_at >= '{start_date}' AND published_at < '{end_date}'
        GROUP BY game_tag
        ORDER BY article_count DESC
        """
    ).fetchall()
    columns = ["tag", "count", "first_at", "last_at"]
    return rows, columns


def create_news_stats_summary_table(con) -> None:
    """
    뉴스 통계 요약 테이블 생성 (일별 집계용).
    수집 사이클 후 호출하여 pre-calculate.
    """
    con.execute("""
        CREATE TABLE IF NOT EXISTS sqlite_db.news_daily_stats (
            stat_date DATE NOT NULL,
            game_tag VARCHAR(50) NOT NULL,
            article_count INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (stat_date, game_tag)
        )
    """)


def upsert_news_daily_stats(con, stat_date: date) -> int:
    """
    특정 날짜의 뉴스 통계를 pre-calculate하여 저장.
    Returns: 업데이트된 태그 수.
    """
    # 해당 날짜의 태그별 카운트 계산
    rows = con.execute(
        f"""
        SELECT
            game_tag,
            COUNT(*) as cnt
        FROM sqlite_db.game_news
        WHERE DATE(published_at) = '{stat_date}'
        GROUP BY game_tag
        """
    ).fetchall()
    
    # Upsert logic
    for tag, count in rows:
        con.execute(f"""
            INSERT INTO sqlite_db.news_daily_stats (stat_date, game_tag, article_count, updated_at)
            VALUES ('{stat_date}', '{tag}', {count}, CURRENT_TIMESTAMP)
            ON CONFLICT (stat_date, game_tag) DO UPDATE SET
                article_count = {count},
                updated_at = CURRENT_TIMESTAMP
        """)
    
    return len(rows)


def fetch_news_stats_optimized(con, start_date: date, end_date: date) -> tuple[list[tuple], list[str]]:
    """
    Pre-calculated 통계 테이블에서 읽기 (빠름).
    테이블이 없으면 fallback으로 직접 집계.
    """
    try:
        rows = con.execute(
            f"""
            SELECT
                game_tag,
                SUM(article_count) as total_count
            FROM sqlite_db.news_daily_stats
            WHERE stat_date >= '{start_date}' AND stat_date < '{end_date}'
            GROUP BY game_tag
            ORDER BY total_count DESC
            """
        ).fetchall()
        if rows:
            return rows, ["tag", "count"]
    except Exception:
        pass  # Table doesn't exist, fallback
    
    # Fallback to raw aggregation
    return fetch_news_stats_by_tag(con, start_date, end_date)

