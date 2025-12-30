#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from backend.db import SessionLocal
from backend.models import Asset, PortfolioSnapshot, Trade
from backend.services.users import get_or_create_single_user


@dataclass
class AssetState:
    qty: float = 0.0
    avg_cost: float = 0.0
    realized_profit: float = 0.0
    last_price: float | None = None


def apply_trade(state: AssetState, trade: Trade) -> None:
    if trade.type == "BUY":
        new_qty = state.qty + trade.quantity
        if new_qty > 0:
            state.avg_cost = (
                (state.qty * state.avg_cost + trade.quantity * trade.price) / new_qty
            )
        state.qty = new_qty
    elif trade.type == "SELL":
        sell_qty = min(state.qty, trade.quantity)
        state.realized_profit += (trade.price - state.avg_cost) * sell_qty
        state.qty = max(0.0, state.qty - trade.quantity)
        if state.qty == 0:
            state.avg_cost = trade.price
    state.last_price = trade.price


def daterange(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill portfolio snapshots from trade history (approx using last trade price)."
    )
    parser.add_argument("--days", type=int, default=365, help="Days to backfill (default 365).")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Delete existing snapshots in the backfill range.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Calculate only without writing to DB.",
    )
    args = parser.parse_args()

    end_date = date.today()
    start_date = end_date - timedelta(days=args.days)

    session = SessionLocal()
    try:
        user = get_or_create_single_user(session)
        assets = session.query(Asset).filter(Asset.user_id == user.id).all()
        trades = (
            session.query(Trade)
            .filter(Trade.user_id == user.id)
            .order_by(Trade.timestamp.asc())
            .all()
        )

        trades_by_asset: dict[int, list[Trade]] = {}
        for trade in trades:
            trades_by_asset.setdefault(trade.asset_id, []).append(trade)

        states: dict[int, AssetState] = {}
        trade_index: dict[int, int] = {}
        for asset in assets:
            if asset.id in trades_by_asset:
                states[asset.id] = AssetState()
                trade_index[asset.id] = 0

        if args.replace:
            session.query(PortfolioSnapshot).filter(
                PortfolioSnapshot.user_id == user.id,
                PortfolioSnapshot.snapshot_at >= datetime.combine(start_date, time.min),
                PortfolioSnapshot.snapshot_at <= datetime.combine(end_date, time.max),
            ).delete(synchronize_session=False)

        created = 0
        for day in daterange(start_date, end_date):
            day_start = datetime.combine(day, time.min)

            total_value = 0.0
            total_invested = 0.0
            realized_profit_total = 0.0

            for asset in assets:
                asset_trades = trades_by_asset.get(asset.id)
                if not asset_trades:
                    # No trade history: use current value as flat line.
                    value = (asset.amount or 0.0) * (asset.current_price or 0.0)
                    invested = (asset.amount or 0.0) * (
                        asset.purchase_price or asset.current_price or 0.0
                    )
                    realized = asset.realized_profit or 0.0
                    total_value += value
                    total_invested += invested
                    realized_profit_total += realized
                    continue

                state = states[asset.id]
                idx = trade_index[asset.id]
                while idx < len(asset_trades) and asset_trades[idx].timestamp.date() <= day:
                    apply_trade(state, asset_trades[idx])
                    idx += 1
                trade_index[asset.id] = idx

                if state.qty <= 0 or state.last_price is None:
                    realized_profit_total += state.realized_profit
                    continue

                value = state.qty * state.last_price
                invested = state.qty * state.avg_cost
                total_value += value
                total_invested += invested
                realized_profit_total += state.realized_profit

            unrealized_profit_total = total_value - total_invested

            snapshot = PortfolioSnapshot(
                user_id=user.id,
                snapshot_at=day_start,
                total_value=total_value,
                total_invested=total_invested,
                realized_profit_total=realized_profit_total,
                unrealized_profit_total=unrealized_profit_total,
            )
            session.add(snapshot)
            created += 1

        if args.dry_run:
            session.rollback()
        else:
            session.commit()

        mode = "dry-run" if args.dry_run else "write"
        print(
            f"Snapshots backfill complete ({mode}): {created} rows from {start_date} to {end_date}."
        )
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
