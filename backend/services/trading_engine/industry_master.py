from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha1
import logging
from pathlib import Path
import zipfile

from sqlalchemy import delete, select

from backend.core.db import SessionLocal, engine
from backend.core.models_misc import (
    TradingEngineIndustrySyncState,
    TradingEngineStockIndustry,
)
from backend.core.time_utils import utcnow


_IDX_MEMBER = "idxcode.mst"
_KOSPI_MEMBER = "kospi_code.mst"
_KOSDAQ_MEMBER = "kosdaq_code.mst"
_KOSPI_TAIL_WIDTH = 227
_KOSDAQ_TAIL_WIDTH = 221
_SYNC_DATASET_NAME = "stock_master"

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class StockIndustryInfo:
    code: str
    name: str
    market: str
    large_code: str | None
    large_name: str | None
    medium_code: str | None
    medium_name: str | None
    small_code: str | None
    small_name: str | None

    @property
    def bucket_name(self) -> str:
        for value in (self.small_name, self.medium_name, self.large_name):
            if value:
                return str(value)
        return ""

    @property
    def bucket_code(self) -> str:
        for value in (self.small_code, self.medium_code, self.large_code):
            if value:
                return str(value)
        return ""


def resolve_stock_industry_info(
    code: str,
    *,
    idxcode_path: str,
    kospi_master_path: str,
    kosdaq_master_path: str,
) -> StockIndustryInfo | None:
    normalized = str(code or "").strip()
    if not normalized:
        return None

    mapping = load_stock_industry_map(
        idxcode_path=idxcode_path,
        kospi_master_path=kospi_master_path,
        kosdaq_master_path=kosdaq_master_path,
    )
    return mapping.get(normalized)


def load_stock_industry_map(
    *,
    idxcode_path: str,
    kospi_master_path: str,
    kosdaq_master_path: str,
) -> dict[str, StockIndustryInfo]:
    idx_path = _resolve_master_path(idxcode_path)
    kospi_path = _resolve_master_path(kospi_master_path)
    kosdaq_path = _resolve_master_path(kosdaq_master_path)
    return _load_stock_industry_map_cached(
        str(idx_path),
        _mtime_ns(idx_path),
        str(kospi_path),
        _mtime_ns(kospi_path),
        str(kosdaq_path),
        _mtime_ns(kosdaq_path),
    )


def load_stock_industry_db_map(
    *,
    idxcode_path: str,
    kospi_master_path: str,
    kosdaq_master_path: str,
) -> dict[str, StockIndustryInfo]:
    idx_path = _resolve_master_path(idxcode_path)
    kospi_path = _resolve_master_path(kospi_master_path)
    kosdaq_path = _resolve_master_path(kosdaq_master_path)
    source_signature = _build_source_signature(
        idxcode_path=str(idx_path),
        kospi_master_path=str(kospi_path),
        kosdaq_master_path=str(kosdaq_path),
    )
    try:
        return _load_stock_industry_db_map_cached(
            str(engine.url),
            source_signature,
            str(idx_path),
            str(kospi_path),
            str(kosdaq_path),
        )
    except Exception as exc:
        logger.warning("industry master DB load failed, falling back to zip: %s", exc)
        return load_stock_industry_map(
            idxcode_path=idxcode_path,
            kospi_master_path=kospi_master_path,
            kosdaq_master_path=kosdaq_master_path,
        )


def sync_stock_industry_db(
    *,
    idxcode_path: str,
    kospi_master_path: str,
    kosdaq_master_path: str,
) -> int:
    idx_path = _resolve_master_path(idxcode_path)
    kospi_path = _resolve_master_path(kospi_master_path)
    kosdaq_path = _resolve_master_path(kosdaq_master_path)
    source_signature = _build_source_signature(
        idxcode_path=str(idx_path),
        kospi_master_path=str(kospi_path),
        kosdaq_master_path=str(kosdaq_path),
    )
    _sync_stock_industry_map_to_db(
        source_signature=source_signature,
        idxcode_path=str(idx_path),
        kospi_master_path=str(kospi_path),
        kosdaq_master_path=str(kosdaq_path),
    )
    _load_stock_industry_db_map_cached.cache_clear()
    return len(
        load_stock_industry_db_map(
            idxcode_path=str(idx_path),
            kospi_master_path=str(kospi_path),
            kosdaq_master_path=str(kosdaq_path),
        )
    )


@lru_cache(maxsize=4)
def _load_stock_industry_map_cached(
    idxcode_path: str,
    idxcode_mtime_ns: int,
    kospi_master_path: str,
    kospi_master_mtime_ns: int,
    kosdaq_master_path: str,
    kosdaq_master_mtime_ns: int,
) -> dict[str, StockIndustryInfo]:
    del idxcode_mtime_ns, kospi_master_mtime_ns, kosdaq_master_mtime_ns

    idx_map = _load_idx_name_map(Path(idxcode_path))
    stock_map: dict[str, StockIndustryInfo] = {}
    stock_map.update(
        _parse_stock_master(
            Path(kospi_master_path),
            member_name=_KOSPI_MEMBER,
            tail_width=_KOSPI_TAIL_WIDTH,
            market="KOSPI",
            idx_map=idx_map,
        )
    )
    stock_map.update(
        _parse_stock_master(
            Path(kosdaq_master_path),
            member_name=_KOSDAQ_MEMBER,
            tail_width=_KOSDAQ_TAIL_WIDTH,
            market="KOSDAQ",
            idx_map=idx_map,
        )
    )
    return stock_map


@lru_cache(maxsize=4)
def _load_stock_industry_db_map_cached(
    database_url: str,
    source_signature: str,
    idxcode_path: str,
    kospi_master_path: str,
    kosdaq_master_path: str,
) -> dict[str, StockIndustryInfo]:
    del database_url
    _sync_stock_industry_map_to_db(
        source_signature=source_signature,
        idxcode_path=idxcode_path,
        kospi_master_path=kospi_master_path,
        kosdaq_master_path=kosdaq_master_path,
    )

    with SessionLocal() as db:
        rows = db.execute(select(TradingEngineStockIndustry)).scalars().all()

    return {
        str(row.code): StockIndustryInfo(
            code=str(row.code),
            name=str(row.name),
            market=str(row.market),
            large_code=row.large_code,
            large_name=row.large_name,
            medium_code=row.medium_code,
            medium_name=row.medium_name,
            small_code=row.small_code,
            small_name=row.small_name,
        )
        for row in rows
    }


def _load_idx_name_map(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    lines = _read_zip_lines(path, _IDX_MEMBER)
    out: dict[str, str] = {}
    for line in lines:
        if len(line) < 6:
            continue
        code = line[1:5].strip()
        name = line[5:].rstrip()
        if code and name:
            out[code.zfill(4)] = name
    return out


def _parse_stock_master(
    path: Path,
    *,
    member_name: str,
    tail_width: int,
    market: str,
    idx_map: dict[str, str],
) -> dict[str, StockIndustryInfo]:
    if not path.exists():
        return {}

    lines = _read_zip_lines(path, member_name)
    out: dict[str, StockIndustryInfo] = {}
    for line in lines:
        if len(line) <= tail_width:
            continue

        prefix = line[:-tail_width]
        suffix = line[-tail_width:]
        code = prefix[:9].rstrip()
        if not code:
            continue

        large_code = _clean_code(suffix[3:7])
        medium_code = _clean_code(suffix[7:11])
        small_code = _clean_code(suffix[11:15])
        out[code] = StockIndustryInfo(
            code=code,
            name=prefix[21:].strip(),
            market=market,
            large_code=large_code,
            large_name=idx_map.get(large_code or ""),
            medium_code=medium_code,
            medium_name=idx_map.get(medium_code or ""),
            small_code=small_code,
            small_name=idx_map.get(small_code or ""),
        )
    return out


def _read_zip_lines(path: Path, member_name: str) -> list[str]:
    with zipfile.ZipFile(path) as zf:
        data = zf.read(member_name)
    return data.decode("cp949").splitlines()


def _clean_code(raw: str) -> str | None:
    text = str(raw or "").strip()
    if not text:
        return None
    padded = text.zfill(4)
    if padded == "0000":
        return None
    return padded


def _mtime_ns(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return -1


def _sync_stock_industry_map_to_db(
    *,
    source_signature: str,
    idxcode_path: str,
    kospi_master_path: str,
    kosdaq_master_path: str,
) -> None:
    _ensure_db_tables()

    with SessionLocal() as db:
        state = db.get(TradingEngineIndustrySyncState, _SYNC_DATASET_NAME)
        has_rows = db.execute(select(TradingEngineStockIndustry.code).limit(1)).first() is not None
        if state is not None and state.source_signature == source_signature and has_rows:
            return

        stock_map = load_stock_industry_map(
            idxcode_path=idxcode_path,
            kospi_master_path=kospi_master_path,
            kosdaq_master_path=kosdaq_master_path,
        )
        if not stock_map:
            logger.warning("industry master parse returned no rows; keeping existing DB snapshot")
            return

        db.execute(delete(TradingEngineStockIndustry))
        db.bulk_save_objects(
            [
                TradingEngineStockIndustry(
                    code=info.code,
                    name=info.name,
                    market=info.market,
                    large_code=info.large_code,
                    large_name=info.large_name,
                    medium_code=info.medium_code,
                    medium_name=info.medium_name,
                    small_code=info.small_code,
                    small_name=info.small_name,
                    bucket_name=info.bucket_name or None,
                    source_signature=source_signature,
                )
                for info in stock_map.values()
            ]
        )

        synced_at = utcnow()
        if state is None:
            db.add(
                TradingEngineIndustrySyncState(
                    dataset_name=_SYNC_DATASET_NAME,
                    source_signature=source_signature,
                    row_count=len(stock_map),
                    synced_at=synced_at,
                )
            )
        else:
            state.source_signature = source_signature
            state.row_count = len(stock_map)
            state.synced_at = synced_at
        db.commit()


def _ensure_db_tables() -> None:
    TradingEngineIndustrySyncState.__table__.create(bind=engine, checkfirst=True)
    TradingEngineStockIndustry.__table__.create(bind=engine, checkfirst=True)


def _build_source_signature(
    *,
    idxcode_path: str,
    kospi_master_path: str,
    kosdaq_master_path: str,
) -> str:
    idx_path = _resolve_master_path(idxcode_path)
    kospi_path = _resolve_master_path(kospi_master_path)
    kosdaq_path = _resolve_master_path(kosdaq_master_path)
    raw = "|".join(
        [
            str(idx_path.resolve()),
            str(_mtime_ns(idx_path)),
            str(kospi_path.resolve()),
            str(_mtime_ns(kospi_path)),
            str(kosdaq_path.resolve()),
            str(_mtime_ns(kosdaq_path)),
        ]
    )
    return sha1(raw.encode("utf-8")).hexdigest()


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
