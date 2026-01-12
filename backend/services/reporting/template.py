from __future__ import annotations

from datetime import date, timedelta
import html
from typing import Any

from ..duckdb_refine import refine_portfolio_for_ai
from .periods import parse_report_query
from ..news.refiner import refine_game_trends_with_duckdb


def build_telegram_steam_trend_message(query_text: str | None) -> str:
    """
    DuckDB 정제 데이터를 기반으로 Steam 게임 트렌드 리포트만 생성한다.
    """
    normalized = (query_text or "").strip()
    return f"<b>🎮 Steam 게임 트렌드 리포트</b>\n\n" + refine_game_trends_with_duckdb(normalized)


def format_telegram_report(
    refined: dict[str, Any],
    top_assets: int = 5,
    top_categories: int = 5,
    top_spending: int = 5,
) -> str:
    period = refined.get("period", {}) or {}
    label = period.get("label") or ""
    start_date = period.get("start_date") or ""
    end_date = period.get("end_date") or ""
    period_range = _format_period_range(start_date, end_date)

    summary = refined.get("portfolio_summary", {}) or {}
    benchmark = refined.get("benchmark", {}) or {}
    cashflow = refined.get("cashflow_summary", {}) or {}
    expense = refined.get("expense_summary", {}) or {}

    total_value = summary.get("total_value") or 0
    total_invested = summary.get("total_invested") or 0
    total_unrealized_profit = summary.get("total_unrealized_profit") or 0
    total_realized_profit = summary.get("total_realized_profit") or 0

    portfolio_return_pct = benchmark.get("portfolio_return_pct")
    if portfolio_return_pct is None and total_invested:
        portfolio_return_pct = (total_value / total_invested - 1) * 100

    lines: list[str] = []
    header_label = html.escape(label) if label else "리포트"
    lines.append(f"<b>📊 리포트 {header_label}</b>")
    if period_range:
        lines.append(f"기간: {period_range}")

    lines.append("")
    lines.append("<b>포트폴리오 요약</b>")
    lines.append(f"총자산: {_format_money(total_value)}")
    lines.append(f"투자원금: {_format_money(total_invested)}")
    lines.append(f"평가손익: {_format_money(total_unrealized_profit)} ({_format_percent(portfolio_return_pct)})")
    lines.append(f"실현손익: {_format_money(total_realized_profit)}")

    benchmark_name = benchmark.get("name")
    benchmark_return = benchmark.get("return_pct")
    benchmark_diff = benchmark.get("diff_pct")
    if benchmark_name:
        safe_name = html.escape(str(benchmark_name))
        lines.append(
            f"벤치마크 {safe_name}: {_format_percent(benchmark_return)}"
            f" (차이 {_format_percent(benchmark_diff)})"
        )

    trade_activity = (refined.get("trade_activity") or {}).get("data") or []
    if trade_activity:
        lines.append("")
        lines.append("<b>매매 활동</b>")
        for item in trade_activity:
            label = _trade_label(item.get("type"))
            trade_count = item.get("trade_count") or 0
            total_value = item.get("total_value") or 0
            realized = item.get("realized_pnl") or 0
            line = f"{label}: {trade_count}건 {_format_money(total_value)}"
            if realized:
                line += f" (실현손익 {_format_money(realized)})"
            lines.append(line)

    assets = refined.get("asset_analytics") or []
    if assets:
        lines.append("")
        lines.append("<b>상위 자산</b>")
        for idx, asset in enumerate(assets[:top_assets], 1):
            name = html.escape(str(asset.get("name") or "자산"))
            ticker = asset.get("ticker")
            label = f"{name} ({html.escape(str(ticker))})" if ticker else name
            value = asset.get("current_value") or 0
            return_pct = asset.get("return_pct")
            return_text = f" ({_format_percent(return_pct)})" if return_pct is not None else ""
            lines.append(f"{idx}. {label} {_format_money(value)}{return_text}")

    lines.append("")
    lines.append("<b>현금흐름</b>")
    lines.append(
        "입금: "
        f"{_format_money(cashflow.get('total_deposits') or 0)} / "
        "출금: "
        f"{_format_money(cashflow.get('total_withdrawals') or 0)} / "
        "순유입: "
        f"{_format_money(cashflow.get('net_flow') or 0)}"
    )
    if cashflow.get("total_dividends"):
        lines.append(f"배당: {_format_money(cashflow.get('total_dividends') or 0)}")

    lines.append("")
    lines.append("<b>가계부 요약</b>")
    lines.append(
        "수입: "
        f"{_format_money(expense.get('total_income') or 0)} / "
        "지출: "
        f"{_format_money(expense.get('total_spending') or 0)} / "
        "순저축: "
        f"{_format_money(expense.get('net_savings') or 0)}"
    )

    spending = refined.get("spending_by_category") or []
    if spending:
        lines.append("지출 TOP 카테고리")
        for item in spending[:top_categories]:
            category = html.escape(str(item.get("category") or "미분류"))
            amount = _format_money(item.get("total_amount") or 0, absolute=True)
            lines.append(f"- {category}: {amount}")

    top_items = refined.get("top_spending_items") or []
    if top_items:
        lines.append("지출 TOP 항목")
        for item in top_items[:top_spending]:
            merchant = html.escape(str(item.get("merchant") or "미상"))
            category = html.escape(str(item.get("category") or "미분류"))
            amount = _format_money(item.get("amount") or 0, absolute=True)
            date_str = str(item.get("date") or "")
            if date_str:
                lines.append(f"- {merchant} ({category}) {amount} | {date_str}")
            else:
                lines.append(f"- {merchant} ({category}) {amount}")

    return "\n".join(lines).strip()


def _format_money(value: float | int | None, absolute: bool = False) -> str:
    if value is None:
        value = 0
    sign = "-" if value < 0 and not absolute else ""
    return f"{sign}{abs(value):,.0f}원"


def _format_percent(value: float | int | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}%"


def _format_period_range(start: str, end: str) -> str:
    if not start or not end:
        return ""
    try:
        start_date = date.fromisoformat(start)
        end_date = date.fromisoformat(end) - timedelta(days=1)
        return f"{start_date.isoformat()} ~ {end_date.isoformat()}"
    except ValueError:
        return f"{start} ~ {end}"


def _trade_label(trade_type: Any) -> str:
    mapping = {
        "BUY": "매수",
        "SELL": "매도",
        "DIVIDEND": "배당",
        "SPLIT": "액면분할",
    }
    return mapping.get(str(trade_type).upper(), str(trade_type or "거래"))
