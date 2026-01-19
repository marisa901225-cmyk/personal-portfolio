
import re
import zipfile
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, time
from pathlib import Path

from backend.core.models import Asset, Trade
from backend.services.users import get_or_create_single_user
from backend.scripts.utils.import_utils import normalize_name, parse_date, parse_number, parse_time

logger = logging.getLogger(__name__)

DEFAULT_SHEET = "All_Normalized"
TRADE_KIND_MAP = {
    "매수": "BUY",
    "매도": "SELL",
}
CURRENCY_NAMES = {
    "USD", "US$", "US DOLLAR", "USDOLLAR", "달러", "미국달러",
    "KRW", "원화",
    "JPY", "엔",
    "CNY", "위안",
    "HKD",
    "EUR", "유로",
    "GBP",
}
NORMALIZED_CURRENCY_NAMES = {re.sub(r"\s+", "", name).upper() for name in CURRENCY_NAMES}
FX_KEYWORDS = ("환전", "외화매수", "외화매도", "자동환전")


def get_cell(row: list[str], idx: int | None) -> str:
    if idx is None or idx < 0 or idx >= len(row):
        return ""
    return row[idx]


def load_shared_strings(xlsx_path: Path) -> list[str]:
    with zipfile.ZipFile(xlsx_path) as zf:
        shared = zf.read("xl/sharedStrings.xml")
    root = ET.fromstring(shared)
    ns = {"ss": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    strings: list[str] = []
    for si in root.findall("ss:si", ns):
        texts = []
        for t in si.findall(".//ss:t", ns):
            texts.append(t.text or "")
        strings.append("".join(texts))
    return strings


def sheet_name_to_path(xlsx_path: Path) -> dict[str, str]:
    with zipfile.ZipFile(xlsx_path) as zf:
        wb = ET.fromstring(zf.read("xl/workbook.xml"))
        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rels_map = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in rels.findall(
            "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"
        )
    }
    ns = {"ss": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    mapping: dict[str, str] = {}
    for sheet in wb.findall("ss:sheets/ss:sheet", ns):
        name = sheet.attrib.get("name")
        rid = sheet.attrib.get(
            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        )
        target = rels_map.get(rid or "")
        if name and target:
            mapping[name] = f"xl/{target}"
    return mapping


def col_to_index(col: str) -> int:
    idx = 0
    for ch in col:
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx - 1


def iter_rows(xlsx_path: Path, sheet_path: str, shared_strings: list[str]):
    ns = {"ss": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(xlsx_path) as zf:
        data = zf.read(sheet_path)
    root = ET.fromstring(data)
    for row in root.findall("ss:sheetData/ss:row", ns):
        row_vals: dict[int, str] = {}
        for cell in row.findall("ss:c", ns):
            ref = cell.attrib.get("r")
            cell_type = cell.attrib.get("t")
            value_node = cell.find("ss:v", ns)
            if ref is None or value_node is None:
                continue
            col = re.match(r"[A-Z]+", ref)
            if not col:
                continue
            col_idx = col_to_index(col.group(0))
            raw = value_node.text or ""
            if cell_type == "s":
                try:
                    val = shared_strings[int(raw)]
                except Exception:
                    val = raw
            else:
                val = raw
            row_vals[col_idx] = val
        if row_vals:
            max_col = max(row_vals.keys())
            yield [row_vals.get(i, "") for i in range(max_col + 1)]


def infer_currency(trade_desc: str, currency_code: str, exchange: str) -> str:
    code = (currency_code or "").strip().upper()
    if code in {"KRW", "USD"}:
        return code
    desc = (trade_desc or "").upper()
    exch = (exchange or "").upper()
    if "USD" in desc or "해외" in desc or exch in {"NASDAQ", "NYSE", "AMEX", "NAS", "NYS", "AMS"}:
        return "USD"
    return "KRW"


def infer_category(trade_desc: str, currency: str) -> str:
    desc = (trade_desc or "")
    if currency == "USD" or "해외" in desc:
        return "해외주식"
    return "국내주식"


def build_asset_map(assets: list[Asset]) -> tuple[dict[str, Asset], int]:
    mapping: dict[str, Asset] = {}
    duplicates = 0
    for asset in assets:
        key = normalize_name(asset.name)
        existing = mapping.get(key)
        if not existing:
            mapping[key] = asset
            continue
        duplicates += 1
        # Priority: Not deleted > Deleted (to resurrect) OR Newer ID
        if existing.deleted_at is not None and asset.deleted_at is None:
            mapping[key] = asset
            continue
        if (existing.deleted_at is None) == (asset.deleted_at is None) and asset.id > existing.id:
            mapping[key] = asset
    return mapping, duplicates


def is_fx_conversion(name: str, desc: str) -> bool:
    normalized = normalize_name(name)
    if normalized in NORMALIZED_CURRENCY_NAMES:
        return True
    desc_text = desc.replace(" ", "")
    return any(keyword in desc_text for keyword in FX_KEYWORDS)


def trade_key(asset_id: int, trade_type: str, qty: float, price: float, ts: datetime) -> tuple:
    return (asset_id, trade_type, round(qty, 6), round(price, 6), ts)


def import_trades_xlsx(session, xlsx_path: Path, sheet_name: str = DEFAULT_SHEET, dry_run: bool = False):
    if not xlsx_path.exists():
        logger.error(f"XLSX not found: {xlsx_path}")
        return

    shared_strings = load_shared_strings(xlsx_path)
    sheet_map = sheet_name_to_path(xlsx_path)
    if sheet_name not in sheet_map:
        logger.error(f"Sheet '{sheet_name}' not found. Available: {', '.join(sheet_map.keys())}")
        return

    rows = iter_rows(xlsx_path, sheet_map[sheet_name], shared_strings)
    header = [str(h).strip() for h in next(rows, [])]
    col = {name: idx for idx, name in enumerate(header)}

    required = ["거래일자", "분류", "종목명", "거래수량", "거래단가"]
    missing = [name for name in required if name not in col]
    if missing:
        logger.error(f"Missing required columns: {', '.join(missing)}")
        return

    user = get_or_create_single_user(session)
    assets = session.query(Asset).filter(Asset.user_id == user.id).all()
    asset_map, duplicate_assets = build_asset_map(assets)

    existing_trades = session.query(Trade).filter(Trade.user_id == user.id).all()
    existing_keys = {
        trade_key(t.asset_id, t.type, t.quantity, t.price, t.timestamp)
        for t in existing_trades
        if t.timestamp is not None
    }

    stats = {
        "rows": 0, "eligible": 0, "missing_name": 0, "invalid_values": 0,
        "missing_date": 0, "duplicates": 0, "inserted": 0, "assets_created": 0,
    }

    created_asset_ids: set[int] = set()
    created_last_ts: dict[int, datetime] = {}

    for row in rows:
        stats["rows"] += 1
        kind_raw = get_cell(row, col.get("분류"))
        kind = str(kind_raw).strip()
        trade_type = TRADE_KIND_MAP.get(kind)
        if not trade_type:
            continue
        stats["eligible"] += 1

        name_raw = get_cell(row, col.get("종목명"))
        name = str(name_raw).strip()
        if not name:
            stats["missing_name"] += 1
            continue

        qty = parse_number(get_cell(row, col.get("거래수량")))
        price = parse_number(get_cell(row, col.get("거래단가")))
        if qty is None or qty == 0:
            stats["invalid_values"] += 1
            continue

        amount = parse_number(get_cell(row, col.get("거래금액"))) if "거래금액" in col else None
        if (price is None or price == 0) and amount is not None:
            price = abs(amount) / abs(qty)

        if price is None or price <= 0:
            stats["invalid_values"] += 1
            continue

        trade_date = parse_date(get_cell(row, col.get("거래일자")))
        if trade_date is None:
            stats["missing_date"] += 1
            continue
        trade_time = parse_time(get_cell(row, col.get("거래시각"))) if "거래시각" in col else None
        timestamp = datetime.combine(trade_date, trade_time or time.min)

        desc = str(get_cell(row, col.get("거래구분"))).strip() if "거래구분" in col else ""
        if is_fx_conversion(name, desc):
            continue
        exchange = str(get_cell(row, col.get("거래소"))).strip() if "거래소" in col else ""
        currency_code = str(get_cell(row, col.get("통화코드"))).strip() if "통화코드" in col else ""

        key = normalize_name(name)
        asset = asset_map.get(key)
        if not asset:
            currency = infer_currency(desc, currency_code, exchange)
            category = infer_category(desc, currency)
            asset = Asset(
                user_id=user.id,
                name=name,
                ticker=None,
                category=category,
                currency=currency,
                amount=0.0,
                current_price=0.0,
                realized_profit=0.0,
            )
            session.add(asset)
            session.flush()
            asset_map[key] = asset
            created_asset_ids.add(asset.id)
            stats["assets_created"] += 1

        unique_key = trade_key(asset.id, trade_type, abs(qty), price, timestamp)
        if unique_key in existing_keys:
            stats["duplicates"] += 1
            continue

        trade = Trade(
            user_id=user.id,
            asset_id=asset.id,
            type=trade_type,
            quantity=abs(qty),
            price=price,
            timestamp=timestamp,
            note=desc or None,
        )
        if not dry_run:
            session.add(trade)
            existing_keys.add(unique_key)
        
        stats["inserted"] += 1

        if asset.id in created_asset_ids:
            prev = created_last_ts.get(asset.id)
            if prev is None or timestamp > prev:
                created_last_ts[asset.id] = timestamp

    # Cleanup temporary created assets if dry-run
    if dry_run:
        session.rollback()
        logger.info("[Dry-Run] Changes rolled back.")
    else:
        session.commit()
    
    logger.info(f"Import Summary: {stats} (Mode: {'Dry-Run' if dry_run else 'Write'})")
