#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from backend.core.db import SessionLocal
from backend.core.models import FxTransaction, User


TYPE_MAP = {
    "매수": "BUY",
    "매도": "SELL",
    "정산": "SETTLEMENT",
    "환전정산입금": "SETTLEMENT",
}


def parse_date(value: str) -> datetime.date | None:
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%Y%m%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def parse_number(value: str) -> float | None:
    value = (value or "").strip()
    if not value:
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", value)
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def infer_type(kind: str, desc: str) -> str | None:
    kind = (kind or "").strip()
    desc = (desc or "").strip()
    if kind in TYPE_MAP:
        return TYPE_MAP[kind]
    if "매수" in desc:
        return "BUY"
    if "매도" in desc:
        return "SELL"
    if "정산" in desc:
        return "SETTLEMENT"
    return None


def type_to_currency(kind: str) -> str:
    return "USD" if kind == "BUY" else "KRW"


def get_or_create_user(session) -> User:
    user = session.query(User).first()
    if user:
        return user
    user = User(name="default")
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def main() -> int:
    parser = argparse.ArgumentParser(description="Import FX history CSV into backend DB.")
    parser.add_argument(
        "--csv",
        default=str(ROOT_DIR / "Book(Sheet1) (2)_clean.csv"),
        help="Path to CSV file (default: Book(Sheet1) (2)_clean.csv)",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Delete existing fx_transactions before import.",
    )
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"CSV not found: {csv_path}", file=sys.stderr)
        return 1

    session = SessionLocal()
    try:
        user = get_or_create_user(session)
        if args.replace:
            session.query(FxTransaction).filter(FxTransaction.user_id == user.id).delete()
            session.commit()

        inserted = 0
        skipped = 0
        with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                trade_date = parse_date(row.get("거래일자", ""))
                tx_type = infer_type(row.get("구분", ""), row.get("적요", ""))
                if not trade_date or not tx_type:
                    skipped += 1
                    continue
                currency = (row.get("통화", "") or "").strip().upper()
                if currency not in ("KRW", "USD"):
                    currency = type_to_currency(tx_type)

                record = FxTransaction(
                    user_id=user.id,
                    trade_date=trade_date,
                    type=tx_type,
                    currency=currency,
                    fx_amount=parse_number(row.get("외화금액", "")),
                    krw_amount=parse_number(row.get("원화금액", "")),
                    rate=parse_number(row.get("환율", "")),
                    description=(row.get("적요", "") or "").strip() or None,
                    note=(row.get("비고", "") or "").strip() or None,
                )
                session.add(record)
                inserted += 1

        session.commit()
        print(f"Inserted {inserted} rows (skipped {skipped}).")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
