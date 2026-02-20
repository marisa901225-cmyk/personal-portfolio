
import csv
import logging
from pathlib import Path
from backend.core.models import FxTransaction, User
from backend.scripts.utils.import_utils import parse_date, parse_number

logger = logging.getLogger(__name__)

TYPE_MAP = {
    "매수": "BUY",
    "매도": "SELL",
    "정산": "SETTLEMENT",
    "환전정산입금": "SETTLEMENT",
}

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

def import_fx_csv(session, csv_path: Path, dry_run: bool = False):
    if not csv_path.exists():
        logger.error(f"CSV not found: {csv_path}")
        return

    user = get_or_create_user(session)
    
    # IDEMPOTENCY CHECK NOT IMPLEMENTED YET IN ORIGINAL SCRIPT
    # The original script deleted everything if --replace was used.
    # We should probably improve this later, but for now we follow the improved plan: idempotent upsert.
    # However, for CSV without unique IDs, it's hard. 
    # Let's stick to append-only with duplicate check based on fields.

    inserted = 0
    skipped = 0
    duplicates = 0
    
    # Load existing to prevent duplicates
    # Key: (date, type, fx_amount, krw_amount, rate)
    existing_keys = set()
    existing = session.query(FxTransaction).filter(FxTransaction.user_id == user.id).all()
    for tx in existing:
        key = (tx.trade_date, tx.type, tx.fx_amount, tx.krw_amount, tx.rate)
        existing_keys.add(key)

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
            
            fx_amount = parse_number(row.get("외화금액", ""))
            krw_amount = parse_number(row.get("원화금액", ""))
            rate = parse_number(row.get("환율", ""))
            
            # Duplicate Check
            key = (trade_date, tx_type, fx_amount, krw_amount, rate)
            if key in existing_keys:
                duplicates += 1
                continue

            record = FxTransaction(
                user_id=user.id,
                trade_date=trade_date,
                type=tx_type,
                currency=currency,
                fx_amount=fx_amount,
                krw_amount=krw_amount,
                rate=rate,
                description=(row.get("적요", "") or "").strip() or None,
                note=(row.get("비고", "") or "").strip() or None,
            )
            
            if not dry_run:
                session.add(record)
                existing_keys.add(key) # Add to set to prevent dups within same file
            
            inserted += 1

    if not dry_run:
        session.commit()
    else:
        session.rollback()

    logger.info(f"Import Summary: Inserted={inserted}, Skipped={skipped}, Duplicates={duplicates} (Dry-run={dry_run})")
