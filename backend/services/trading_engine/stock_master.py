from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import zipfile

from .config import TradeEngineConfig
from .utils import is_etf_row, parse_numeric

_KOSPI_MEMBER = "kospi_code.mst"
_KOSDAQ_MEMBER = "kosdaq_code.mst"
_KOSPI_TAIL_WIDTH = 228
_KOSDAQ_TAIL_WIDTH = 222
_SWING_UNIVERSE_INDEX_FLOOR_BUFFER_RATIO = 0.90

_KOSPI_FIELD_SPECS = [
    2, 1, 4, 4, 4,
    1, 1, 1, 1, 1,
    1, 1, 1, 1, 1,
    1, 1, 1, 1, 1,
    1, 1, 1, 1, 1,
    1, 1, 1, 1, 1,
    1, 9, 5, 5, 1,
    1, 1, 2, 1, 1,
    1, 2, 2, 2, 3,
    1, 3, 12, 12, 8,
    15, 21, 2, 7, 1,
    1, 1, 1, 1, 9,
    9, 9, 5, 9, 8,
    9, 3, 1, 1, 1,
]
_KOSPI_COLUMNS = [
    "group_code",
    "mcap_size_code",
    "industry_large_code",
    "industry_medium_code",
    "industry_small_code",
    "is_manufacturing",
    "is_low_liquidity",
    "is_governance_index",
    "kospi200_sector_code",
    "is_kospi100",
    "is_kospi50",
    "is_krx",
    "is_etp",
    "is_elw",
    "is_krx100",
    "is_krx_auto",
    "is_krx_semiconductor",
    "is_krx_bio",
    "is_krx_bank",
    "is_spac",
    "is_krx_energy_chem",
    "is_krx_steel",
    "is_short_term_overheat",
    "is_krx_media_telecom",
    "is_krx_construction",
    "unused_1",
    "is_krx_securities",
    "is_krx_ship",
    "is_krx_insurance",
    "is_krx_transport",
    "is_sri",
    "base_price",
    "lot_size",
    "after_hours_lot_size",
    "is_halted",
    "is_liquidation",
    "is_management_issue",
    "market_warning_code",
    "is_warning_preannounce",
    "is_unfaithful_disclosure",
    "is_backdoor_listing",
    "lock_code",
    "par_value_change_code",
    "capital_increase_code",
    "margin_ratio",
    "is_margin_allowed",
    "credit_days",
    "previous_volume",
    "par_value",
    "listed_at",
    "listed_shares_thousand",
    "capital",
    "fiscal_month",
    "ipo_price",
    "preferred_share_code",
    "is_short_sale_overheat",
    "is_abnormal_surge",
    "is_krx300",
    "is_kospi",
    "sales",
    "operating_profit",
    "ordinary_profit",
    "net_income",
    "roe",
    "base_year_month",
    "master_market_cap_eok",
    "group_company_code",
    "is_credit_limit_exceeded",
    "is_collateral_loan_allowed",
    "is_stock_loan_allowed",
]

_KOSDAQ_FIELD_SPECS = [
    2, 1,
    4, 4, 4, 1, 1,
    1, 1, 1, 1, 1,
    1, 1, 1, 1, 1,
    1, 1, 1, 1, 1,
    1, 1, 1, 1, 9,
    5, 5, 1, 1, 1,
    2, 1, 1, 1, 2,
    2, 2, 3, 1, 3,
    12, 12, 8, 15, 21,
    2, 7, 1, 1, 1,
    1, 9, 9, 9, 5,
    9, 8, 9, 3, 1,
    1, 1,
]
_KOSDAQ_COLUMNS = [
    "group_code",
    "mcap_size_code",
    "industry_large_code",
    "industry_medium_code",
    "industry_small_code",
    "is_venture",
    "is_low_liquidity",
    "is_krx",
    "is_etp",
    "is_krx100",
    "is_krx_auto",
    "is_krx_semiconductor",
    "is_krx_bio",
    "is_krx_bank",
    "is_spac",
    "is_krx_energy_chem",
    "is_krx_steel",
    "short_term_overheat_code",
    "is_krx_media_telecom",
    "is_krx_construction",
    "is_investment_caution_issue",
    "is_krx_securities",
    "is_krx_ship",
    "is_krx_insurance",
    "is_krx_transport",
    "is_kosdaq150",
    "base_price",
    "lot_size",
    "after_hours_lot_size",
    "is_halted",
    "is_liquidation",
    "is_management_issue",
    "market_warning_code",
    "is_warning_preannounce",
    "is_unfaithful_disclosure",
    "is_backdoor_listing",
    "lock_code",
    "par_value_change_code",
    "capital_increase_code",
    "margin_ratio",
    "is_margin_allowed",
    "credit_days",
    "previous_volume",
    "par_value",
    "listed_at",
    "listed_shares_thousand",
    "capital",
    "fiscal_month",
    "ipo_price",
    "preferred_share_code",
    "is_short_sale_overheat",
    "is_abnormal_surge",
    "is_krx300",
    "sales",
    "operating_profit",
    "ordinary_profit",
    "net_income",
    "roe",
    "base_year_month",
    "master_market_cap_eok",
    "group_company_code",
    "is_credit_limit_exceeded",
    "is_collateral_loan_allowed",
    "is_stock_loan_allowed",
]


@dataclass(frozen=True, slots=True)
class StockMasterInfo:
    code: str
    name: str
    market: str
    master_market_cap: float | None
    listed_shares: float | None
    base_price: float | None
    is_etf: bool
    is_kospi200: bool
    is_kosdaq150: bool

    @property
    def is_index_large_cap(self) -> bool:
        return bool(self.is_kospi200 or self.is_kosdaq150)


def load_stock_master_map(
    *,
    kospi_master_path: str,
    kosdaq_master_path: str,
) -> dict[str, StockMasterInfo]:
    kospi_path = _resolve_master_path(kospi_master_path)
    kosdaq_path = _resolve_master_path(kosdaq_master_path)
    return _load_stock_master_map_cached(
        str(kospi_path),
        _mtime_ns(kospi_path),
        str(kosdaq_path),
        _mtime_ns(kosdaq_path),
    )


def load_swing_universe_candidates(config: TradeEngineConfig) -> list[dict[str, object]]:
    master_map = load_stock_master_map(
        kospi_master_path=config.industry_kospi_master_path,
        kosdaq_master_path=config.industry_kosdaq_master_path,
    )
    if not master_map:
        return []

    floors = _derive_index_floors(master_map.values())
    rows: list[dict[str, object]] = []
    for info in master_map.values():
        if not _is_swing_universe_candidate(info, floors, config):
            continue
        rows.append(
            {
                "code": info.code,
                "name": info.name,
                "mcap": info.master_market_cap,
                "master_market_cap": info.master_market_cap,
                "master_market": info.market,
                "listed_shares": info.listed_shares,
                "base_price": info.base_price,
                "is_etf": info.is_etf,
                "master_is_index_member": info.is_index_large_cap,
            }
        )

    rows.sort(
        key=lambda row: (
            0 if bool(row.get("master_is_index_member")) else 1,
            -(float(row.get("master_market_cap") or 0.0)),
            str(row.get("code") or ""),
        )
    )
    return rows[: max(1, int(config.model_top_k))]


@lru_cache(maxsize=4)
def _load_stock_master_map_cached(
    kospi_master_path: str,
    kospi_master_mtime_ns: int,
    kosdaq_master_path: str,
    kosdaq_master_mtime_ns: int,
) -> dict[str, StockMasterInfo]:
    del kospi_master_mtime_ns, kosdaq_master_mtime_ns

    stock_map: dict[str, StockMasterInfo] = {}
    stock_map.update(
        _parse_master_file(
            Path(kospi_master_path),
            member_name=_KOSPI_MEMBER,
            market="KOSPI",
            tail_width=_KOSPI_TAIL_WIDTH,
            field_specs=_KOSPI_FIELD_SPECS,
            column_names=_KOSPI_COLUMNS,
        )
    )
    stock_map.update(
        _parse_master_file(
            Path(kosdaq_master_path),
            member_name=_KOSDAQ_MEMBER,
            market="KOSDAQ",
            tail_width=_KOSDAQ_TAIL_WIDTH,
            field_specs=_KOSDAQ_FIELD_SPECS,
            column_names=_KOSDAQ_COLUMNS,
        )
    )
    return stock_map


def _parse_master_file(
    path: Path,
    *,
    member_name: str,
    market: str,
    tail_width: int,
    field_specs: list[int],
    column_names: list[str],
) -> dict[str, StockMasterInfo]:
    if not path.exists():
        return {}

    rows = _read_zip_lines(path, member_name)
    out: dict[str, StockMasterInfo] = {}
    for line in rows:
        prefix = line[0 : len(line) - tail_width]
        code = prefix[0:9].rstrip()
        if not code:
            continue

        name = prefix[21:].strip()
        raw_fields = _parse_fixed_width_fields(line[-tail_width:], field_specs, column_names)
        master_market_cap = _market_cap_from_fields(raw_fields)
        listed_shares = _listed_shares_from_fields(raw_fields)
        base_price = parse_numeric(raw_fields.get("base_price"))
        is_etf = _field_is_truthy(raw_fields.get("is_etp")) or is_etf_row(
            {"name": name, "is_etf": raw_fields.get("is_etp")}
        )
        out[code] = StockMasterInfo(
            code=code,
            name=name,
            market=market,
            master_market_cap=master_market_cap,
            listed_shares=listed_shares,
            base_price=base_price,
            is_etf=is_etf,
            is_kospi200=_field_has_value(raw_fields.get("kospi200_sector_code")),
            is_kosdaq150=_field_is_truthy(raw_fields.get("is_kosdaq150")),
        )
    return out


def _parse_fixed_width_fields(
    text: str,
    field_specs: list[int],
    column_names: list[str],
) -> dict[str, str]:
    pos = 0
    out: dict[str, str] = {}
    for width, column_name in zip(field_specs, column_names):
        out[column_name] = text[pos : pos + width]
        pos += width
    return out


def _market_cap_from_fields(fields: dict[str, str]) -> float | None:
    market_cap_eok = parse_numeric(fields.get("master_market_cap_eok"))
    if market_cap_eok is not None and market_cap_eok > 0:
        return float(market_cap_eok) * 100_000_000.0

    listed_shares = _listed_shares_from_fields(fields)
    base_price = parse_numeric(fields.get("base_price"))
    if listed_shares is None or base_price is None or listed_shares <= 0 or base_price <= 0:
        return None
    return float(listed_shares) * float(base_price)


def _listed_shares_from_fields(fields: dict[str, str]) -> float | None:
    listed_shares_thousand = parse_numeric(fields.get("listed_shares_thousand"))
    if listed_shares_thousand is None or listed_shares_thousand <= 0:
        return None
    return float(listed_shares_thousand) * 1000.0


def _derive_index_floors(entries: list[StockMasterInfo] | object) -> dict[str, float]:
    floors: dict[str, float] = {}
    entries_list = list(entries)
    kospi_members = [
        float(entry.master_market_cap)
        for entry in entries_list
        if entry.market == "KOSPI" and entry.is_kospi200 and entry.master_market_cap
    ]
    kosdaq_members = [
        float(entry.master_market_cap)
        for entry in entries_list
        if entry.market == "KOSDAQ" and entry.is_kosdaq150 and entry.master_market_cap
    ]
    if kospi_members:
        floors["KOSPI"] = min(kospi_members)
    if kosdaq_members:
        floors["KOSDAQ"] = min(kosdaq_members)
    return floors


def _is_swing_universe_candidate(
    info: StockMasterInfo,
    floors: dict[str, float],
    config: TradeEngineConfig,
) -> bool:
    if info.is_etf:
        return False

    market_cap = float(info.master_market_cap or 0.0)
    if market_cap <= 0:
        return False

    if info.is_index_large_cap:
        return True

    market_floor = float(floors.get(info.market, 0.0) or 0.0)
    threshold = float(config.model_mcap_min)
    if market_floor > 0:
        threshold = min(threshold, market_floor * _SWING_UNIVERSE_INDEX_FLOOR_BUFFER_RATIO)
    return market_cap >= threshold


def _field_is_truthy(value: object) -> bool:
    text = str(value or "").strip().upper()
    return text not in {"", "0", "00", "N"}


def _field_has_value(value: object) -> bool:
    return str(value or "").strip() not in {"", "0"}


def _read_zip_lines(path: Path, member_name: str) -> list[str]:
    with zipfile.ZipFile(path) as zf:
        data = zf.read(member_name)
    return data.decode("cp949").splitlines(True)


def _mtime_ns(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return -1


def _resolve_master_path(raw_path: str) -> Path:
    path = Path(str(raw_path or "").strip())
    if path.is_absolute():
        return path

    if path.exists():
        return path

    repo_root = Path(__file__).resolve().parents[3]
    repo_relative = repo_root / path
    if repo_relative.exists():
        return repo_relative

    return repo_relative
