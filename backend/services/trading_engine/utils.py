from __future__ import annotations

import math
from datetime import datetime
from typing import Any

import pandas as pd


_CODE_KEYS = [
    "code",
    "pdno",
    "stck_shrn_iscd",
    "symbol",
    "ticker",
    "item_code",
    "isin",
]
_NAME_KEYS = ["name", "hts_kor_isnm", "prdt_name", "symbol_name", "item_name", "nm"]
_RANK_KEYS = ["rank", "rnk", "순위", "data_rank"]
_MCAP_KEYS = ["mcap", "market_cap", "marketcap", "total_mcap", "시가총액"]
_CLOSE_KEYS = ["close", "stck_prpr", "price", "last", "cur_price"]
_CHANGE_KEYS = ["change_pct", "chg_pct", "prdy_ctrt", "rate", "diff_pct"]
_VALUE_KEYS = ["value", "trading_value", "acc_trdval", "volume_value", "거래대금"]
_VOLUME_KEYS = ["volume", "acml_vol", "trade_volume", "거래량"]
_PRODUCT_TYPE_KEYS = ["product_type", "prdt_type", "sec_type", "kind", "category"]
_ETF_FLAG_KEYS = ["is_etf", "etf", "etf_yn", "is_etf_yn"]

_LEVERAGE_ETF_KEYWORDS = [
    "레버",
    "2x",
    "3x",
    "인버스",
    "선물",
    "파생",
    "lever",
    "inverse",
    "ultra",
]


def parse_numeric(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        v = float(value)
    else:
        text = str(value).strip().replace(",", "")
        if not text:
            return None
        try:
            v = float(text)
        except ValueError:
            return None

    if math.isnan(v) or math.isinf(v):
        return None
    return v


def normalize_code(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.isdigit() and len(text) <= 6:
        return text.zfill(6)
    return text


def _pick_first(record: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in record and record[key] not in (None, ""):
            return record[key]
    lower = {str(k).lower(): v for k, v in record.items()}
    for key in keys:
        if key.lower() in lower and lower[key.lower()] not in (None, ""):
            return lower[key.lower()]
    return None


def standardize_rank_df(records: list[dict[str, Any]], rank_key: str = "rank") -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for idx, raw in enumerate(records or [], start=1):
        if not isinstance(raw, dict):
            continue
        code = normalize_code(_pick_first(raw, _CODE_KEYS))
        if not code:
            continue
        base_rank = parse_numeric(_pick_first(raw, [rank_key] + _RANK_KEYS))
        row = {
            "code": code,
            "name": (_pick_first(raw, _NAME_KEYS) or "").strip(),
            rank_key: int(base_rank) if base_rank is not None else idx,
            "mcap": parse_numeric(_pick_first(raw, _MCAP_KEYS)),
            "close": parse_numeric(_pick_first(raw, _CLOSE_KEYS)),
            "change_pct": parse_numeric(_pick_first(raw, _CHANGE_KEYS)),
            "value": parse_numeric(_pick_first(raw, _VALUE_KEYS)),
            "volume": parse_numeric(_pick_first(raw, _VOLUME_KEYS)),
            "product_type": (_pick_first(raw, _PRODUCT_TYPE_KEYS) or "").strip(),
            "is_etf": _to_bool(_pick_first(raw, _ETF_FLAG_KEYS)),
        }
        row["raw"] = raw
        rows.append(row)

    if not rows:
        return pd.DataFrame(
            columns=[
                "code",
                "name",
                rank_key,
                "mcap",
                "close",
                "change_pct",
                "value",
                "volume",
                "product_type",
                "is_etf",
                "raw",
            ]
        )

    df = pd.DataFrame(rows)
    return df.drop_duplicates(subset=["code"], keep="first").reset_index(drop=True)


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip().lower()
    return text in {"y", "yes", "true", "1", "etf"}


def is_etf_row(row: dict[str, Any] | pd.Series) -> bool:
    data = row.to_dict() if hasattr(row, "to_dict") else dict(row)
    if _to_bool(data.get("is_etf")):
        return True
    name = str(data.get("name") or "").lower()
    product_type = str(data.get("product_type") or "").lower()
    
    # Common Korean ETF providers
    etf_providers = ["kodex", "tiger", "kindex", "kbstar", "arirang", "hanaro", "koset", "sol", "ace", "woori", "hismart", "trex"]
    is_provider = any(name.startswith(p) for p in etf_providers)
    
    return "etf" in name or "etf" in product_type or is_provider


def is_excluded_etf(row: dict[str, Any] | pd.Series) -> bool:
    data = row.to_dict() if hasattr(row, "to_dict") else dict(row)
    name = str(data.get("name") or "").lower()
    product_type = str(data.get("product_type") or "").lower()
    text = f"{name} {product_type}"
    return any(keyword in text for keyword in _LEVERAGE_ETF_KEYWORDS)


def compute_sma(close_series: pd.Series, window: int) -> pd.Series:
    return pd.to_numeric(close_series, errors="coerce").rolling(window=window).mean()


def compute_avg_value(df: pd.DataFrame, window: int) -> tuple[float | None, bool]:
    if df is None or df.empty:
        return None, True
    view = df.tail(window).copy()
    if view.empty:
        return None, True

    if "value" in view.columns and pd.to_numeric(view["value"], errors="coerce").notna().any():
        value = pd.to_numeric(view["value"], errors="coerce").mean()
        if pd.notna(value):
            return float(value), False

    if "close" not in view.columns or "volume" not in view.columns:
        return None, True

    close = pd.to_numeric(view["close"], errors="coerce")
    volume = pd.to_numeric(view["volume"], errors="coerce")
    proxy = (close * volume).mean()
    if pd.notna(proxy):
        return float(proxy), True
    return None, True


def kst_iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def normalize_bar_date(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    if "-" in text:
        return text.replace("-", "")[:8]
    if len(text) >= 8:
        return text[:8]
    return text


def parse_hhmm(text: str) -> tuple[int, int]:
    hh, mm = text.split(":", 1)
    return int(hh), int(mm)


def hhmm_of(dt: datetime) -> str:
    return dt.strftime("%H:%M")
