from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

logger = logging.getLogger(__name__)

_KST = ZoneInfo("Asia/Seoul")
_COLUMNS = ("date", "open", "high", "low", "close", "volume", "value")
DEFAULT_DAILY_BARS_DISK_CACHE_PATH = Path(
    os.getenv(
        "KIS_DAILY_BARS_DISK_CACHE_PATH",
        "backend/storage/trading_engine/daily_bars_cache.sqlite",
    )
)


class DailyBarsDiskCache:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._initialized = False

    def load(
        self,
        *,
        code: str,
        end_date: str,
        lookback: int,
        adjusted_flag: str,
    ) -> pd.DataFrame | None:
        self._ensure_schema()
        try:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT rows_json
                    FROM daily_bars_cache
                    WHERE code = ?
                      AND end_date = ?
                      AND lookback = ?
                      AND adjusted_flag = ?
                      AND trade_date = ?
                    """,
                    (code, end_date, int(lookback), adjusted_flag, end_date),
                ).fetchone()
        except sqlite3.Error:
            logger.warning("daily bars disk cache load failed path=%s code=%s", self.path, code, exc_info=True)
            return None

        if not row:
            return None
        try:
            records = json.loads(str(row[0] or "[]"))
        except json.JSONDecodeError:
            return None
        if not isinstance(records, list):
            return None
        return _records_to_frame(records)

    def store(
        self,
        *,
        code: str,
        end_date: str,
        lookback: int,
        adjusted_flag: str,
        frame: pd.DataFrame,
    ) -> None:
        self._ensure_schema()
        self.purge_stale(keep_trade_date=end_date)
        records = _frame_to_records(frame)
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO daily_bars_cache (
                        code, end_date, lookback, adjusted_flag, trade_date, fetched_at, rows_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(code, end_date, lookback, adjusted_flag)
                    DO UPDATE SET
                        trade_date = excluded.trade_date,
                        fetched_at = excluded.fetched_at,
                        rows_json = excluded.rows_json
                    """,
                    (
                        code,
                        end_date,
                        int(lookback),
                        adjusted_flag,
                        end_date,
                        datetime.now(_KST).isoformat(timespec="seconds"),
                        json.dumps(records, ensure_ascii=False, separators=(",", ":")),
                    ),
                )
                conn.commit()
        except sqlite3.Error:
            logger.warning("daily bars disk cache store failed path=%s code=%s", self.path, code, exc_info=True)

    def purge_stale(self, *, keep_trade_date: str | None = None) -> int:
        self._ensure_schema()
        today = datetime.now(_KST).strftime("%Y%m%d")
        keep = str(keep_trade_date or today).strip()[:8]
        if len(keep) != 8:
            keep = today
        try:
            with self._connect() as conn:
                cursor = conn.execute(
                    "DELETE FROM daily_bars_cache WHERE trade_date != ?",
                    (keep,),
                )
                conn.commit()
                return int(cursor.rowcount if cursor.rowcount is not None else 0)
        except sqlite3.Error:
            logger.warning("daily bars disk cache purge failed path=%s", self.path, exc_info=True)
            return 0

    def load_holiday_rows(self, *, bass_dt: str, fetched_on: str) -> list[dict[str, Any]] | None:
        self._ensure_schema()
        normalized_bass_dt = str(bass_dt or "").strip()[:8]
        normalized_fetched_on = str(fetched_on or "").strip()[:8]
        if len(normalized_bass_dt) != 8 or len(normalized_fetched_on) != 8:
            return None
        try:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT rows_json
                    FROM holiday_rows_cache
                    WHERE bass_dt = ?
                      AND fetched_on = ?
                    """,
                    (normalized_bass_dt, normalized_fetched_on),
                ).fetchone()
        except sqlite3.Error:
            logger.warning("holiday rows disk cache load failed path=%s bass_dt=%s", self.path, bass_dt, exc_info=True)
            return None

        if not row:
            return None
        try:
            rows = json.loads(str(row[0] or "[]"))
        except json.JSONDecodeError:
            return None
        if not isinstance(rows, list):
            return None
        return [dict(item) for item in rows if isinstance(item, dict)]

    def store_holiday_rows(self, *, bass_dt: str, fetched_on: str, rows: list[dict[str, Any]]) -> None:
        self._ensure_schema()
        normalized_bass_dt = str(bass_dt or "").strip()[:8]
        normalized_fetched_on = str(fetched_on or "").strip()[:8]
        if len(normalized_bass_dt) != 8 or len(normalized_fetched_on) != 8:
            return
        normalized_rows = [dict(item) for item in rows if isinstance(item, dict)]
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO holiday_rows_cache (
                        bass_dt, fetched_on, stored_at, rows_json
                    )
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(bass_dt, fetched_on)
                    DO UPDATE SET
                        stored_at = excluded.stored_at,
                        rows_json = excluded.rows_json
                    """,
                    (
                        normalized_bass_dt,
                        normalized_fetched_on,
                        datetime.now(_KST).isoformat(timespec="seconds"),
                        json.dumps(normalized_rows, ensure_ascii=False, separators=(",", ":")),
                    ),
                )
                conn.commit()
        except sqlite3.Error:
            logger.warning("holiday rows disk cache store failed path=%s bass_dt=%s", self.path, bass_dt, exc_info=True)

    def clear(self) -> int:
        self._ensure_schema()
        try:
            with self._connect() as conn:
                cursor = conn.execute("DELETE FROM daily_bars_cache")
                conn.commit()
                return int(cursor.rowcount if cursor.rowcount is not None else 0)
        except sqlite3.Error:
            logger.warning("daily bars disk cache clear failed path=%s", self.path, exc_info=True)
            return 0

    def _ensure_schema(self) -> None:
        if self._initialized:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._connect() as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.execute("PRAGMA busy_timeout=30000")
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS daily_bars_cache (
                        code TEXT NOT NULL,
                        end_date TEXT NOT NULL,
                        lookback INTEGER NOT NULL,
                        adjusted_flag TEXT NOT NULL,
                        trade_date TEXT NOT NULL,
                        fetched_at TEXT NOT NULL,
                        rows_json TEXT NOT NULL,
                        PRIMARY KEY (code, end_date, lookback, adjusted_flag)
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_daily_bars_cache_trade_date
                    ON daily_bars_cache(trade_date)
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS holiday_rows_cache (
                        bass_dt TEXT NOT NULL,
                        fetched_on TEXT NOT NULL,
                        stored_at TEXT NOT NULL,
                        rows_json TEXT NOT NULL,
                        PRIMARY KEY (bass_dt, fetched_on)
                    )
                    """
                )
                conn.commit()
            self._initialized = True
        except sqlite3.Error:
            logger.warning("daily bars disk cache schema init failed path=%s", self.path, exc_info=True)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.path), timeout=30)


def clear_daily_bars_disk_cache(path: str | Path) -> int:
    return DailyBarsDiskCache(path).clear()


def _frame_to_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return []
    records: list[dict[str, Any]] = []
    for row in frame.loc[:, [col for col in _COLUMNS if col in frame.columns]].to_dict(orient="records"):
        normalized: dict[str, Any] = {}
        for key in _COLUMNS:
            value = row.get(key)
            if key == "date":
                normalized[key] = str(value or "").strip()
            elif value is None:
                normalized[key] = 0
            else:
                normalized[key] = int(float(value))
        records.append(normalized)
    return records


def _records_to_frame(records: list[Any]) -> pd.DataFrame:
    normalized_records: list[dict[str, Any]] = []
    for item in records:
        if not isinstance(item, dict):
            continue
        normalized: dict[str, Any] = {"date": str(item.get("date") or "").strip()}
        if not normalized["date"]:
            continue
        for key in _COLUMNS:
            if key == "date":
                continue
            value = item.get(key)
            try:
                normalized[key] = int(float(value or 0))
            except (TypeError, ValueError):
                normalized[key] = 0
        normalized_records.append(normalized)
    if not normalized_records:
        return pd.DataFrame(columns=list(_COLUMNS))
    return pd.DataFrame(normalized_records, columns=list(_COLUMNS))
