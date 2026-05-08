from __future__ import annotations

import argparse
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from backend.services.trading_engine.google_calendar import record_profit_to_google_calendar
from backend.services.trading_engine.runtime import get_or_create_bot

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="KIS 기간손익을 Google Calendar 손익 기록으로 백필한다.")
    parser.add_argument("--start", default="20260227", help="조회 시작일 YYYYMMDD")
    parser.add_argument("--end", default=_today_kst(), help="조회 종료일 YYYYMMDD")
    parser.add_argument("--code", default="", help="특정 종목 코드만 조회할 때 사용")
    parser.add_argument("--dry-run", action="store_true", help="Calendar에 쓰지 않고 조회 결과만 출력")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    bot = get_or_create_bot()
    if bot is None:
        raise SystemExit("trading engine bot is not available; check TRADING_ENGINE_ENABLED and KIS config")
    if not hasattr(bot.api, "period_profit"):
        raise SystemExit("trading api does not support period_profit")

    rows = bot.api.period_profit(start_date=args.start, end_date=args.end, code=args.code)
    rows = sorted(rows, key=lambda row: str(row.get("trade_date") or ""))
    written = 0
    for row in rows:
        trade_date = str(row.get("trade_date") or "").strip()
        realized_pnl = float(row.get("realized_pnl") or 0)
        pnl_rate = row.get("pnl_rate")
        rate = float(pnl_rate) if pnl_rate is not None else None
        if not trade_date:
            continue
        print(_format_preview_line(trade_date=trade_date, realized_pnl=realized_pnl, pnl_rate=rate))
        if args.dry_run:
            continue
        event_id = record_profit_to_google_calendar(
            config=bot.config,
            trade_date=trade_date,
            realized_pnl=realized_pnl,
            pnl_rate=rate,
            logger=logger,
        )
        if event_id:
            written += 1

    if args.dry_run:
        print(f"dry-run: {len(rows)}개 손익 기록을 확인했습니다.")
    else:
        print(f"done: {written}/{len(rows)}개 손익 기록을 Calendar에 반영했습니다.")


def _today_kst() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d")


def _format_preview_line(*, trade_date: str, realized_pnl: float, pnl_rate: float | None) -> str:
    rate_text = f" ({pnl_rate:+.2f}%)" if pnl_rate is not None else ""
    return f"{trade_date}: 실현손익 {realized_pnl:,.0f}원{rate_text}"


if __name__ == "__main__":
    main()
