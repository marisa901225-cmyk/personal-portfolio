from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

import pandas as pd
import requests

logger = logging.getLogger(__name__)


class KISMarketDataMixin:
    def volume_rank(self, kind: str, top_n: int, asof: str) -> list[dict[str, Any]]:
        """
        거래량 랭킹 조회 [v1_국내주식-047].
        GET /uapi/domestic-stock/v1/quotations/volume-rank
        """
        del asof
        normalized_kind = str(kind or "").strip().lower()
        if normalized_kind == "value":
            return self._value_rank(top_n=top_n)

        merged_by_code: dict[str, dict[str, Any]] = {}
        for market_div_code in getattr(self, "_rank_market_div_codes", ("J", "NX")):
            params = self._volume_rank_params(
                kind=normalized_kind,
                price_from="0",
                price_to="0",
                market_div_code=market_div_code,
            )
            try:
                data = self._market_get(
                    "/uapi/domestic-stock/v1/quotations/volume-rank",
                    "FHPST01710000",
                    params,
                )
            except requests.exceptions.RequestException as exc:
                logger.warning(
                    "volume_rank request failed kind=%s market=%s top_n=%s error=%s",
                    kind,
                    market_div_code,
                    top_n,
                    exc,
                )
                continue
            for row in self._parse_volume_rank_rows(data.get("output", []), venue_market=market_div_code):
                self._upsert_rank_row(
                    merged_by_code,
                    row,
                    prefer_field="volume",
                )

        rows = sorted(
            merged_by_code.values(),
            key=lambda row: (
                int(row.get("volume", 0)),
                int(row.get("value", 0)),
                int(row.get("market_cap", 0)),
            ),
            reverse=True,
        )
        for idx, row in enumerate(rows, start=1):
            row["rank"] = idx
        return rows[:top_n]

    def hts_top_view_rank(self, top_n: int, asof: str) -> list[dict[str, Any]]:
        """
        HTS 조회상위20종목 조회.
        GET /uapi/domestic-stock/v1/ranking/hts-top-view
        """
        del asof
        params = {
            "FID_INPUT_ISCD": "0000",
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_MKOP_CLS_CODE": "00",
        }
        try:
            data = self._market_get(
                "/uapi/domestic-stock/v1/ranking/hts-top-view",
                "FHPST01810000",
                params,
            )
        except requests.exceptions.RequestException as exc:
            logger.warning("hts_top_view_rank request failed top_n=%s error=%s", top_n, exc)
            return []

        rows = self._parse_hts_top_view_rows(data)
        rows = sorted(
            rows,
            key=lambda row: (
                int(row.get("rank", 0)) <= 0,
                int(row.get("rank", 0)) if int(row.get("rank", 0)) > 0 else 999999,
            ),
        )
        for idx, row in enumerate(rows, start=1):
            if int(row.get("rank", 0)) <= 0:
                row["rank"] = idx
        return rows[:top_n]

    def _value_rank(self, *, top_n: int) -> list[dict[str, Any]]:
        merged_by_code: dict[str, dict[str, Any]] = {}
        for price_from, price_to in getattr(self, "_value_rank_price_buckets", ()):
            for market_div_code in getattr(self, "_rank_market_div_codes", ("J", "NX")):
                params = self._volume_rank_params(
                    kind="value",
                    price_from=price_from,
                    price_to=price_to,
                    market_div_code=market_div_code,
                )
                try:
                    data = self._market_get(
                        "/uapi/domestic-stock/v1/quotations/volume-rank",
                        "FHPST01710000",
                        params,
                    )
                except requests.exceptions.RequestException as exc:
                    logger.warning(
                        "value_rank bucket request failed market=%s price_from=%s price_to=%s error=%s",
                        market_div_code,
                        price_from,
                        price_to,
                        exc,
                    )
                    continue

                for row in self._parse_volume_rank_rows(data.get("output", []), venue_market=market_div_code):
                    self._upsert_rank_row(
                        merged_by_code,
                        row,
                        prefer_field="value",
                    )

        sorted_rows = sorted(
            merged_by_code.values(),
            key=lambda row: (
                int(row.get("value", 0)),
                int(row.get("volume", 0)),
                int(row.get("market_cap", 0)),
            ),
            reverse=True,
        )
        for idx, row in enumerate(sorted_rows, start=1):
            row["rank"] = idx
        return sorted_rows[:top_n]

    def _volume_rank_params(
        self,
        *,
        kind: str,
        price_from: str,
        price_to: str,
        market_div_code: str,
    ) -> dict[str, str]:
        return {
            "FID_COND_MRKT_DIV_CODE": str(market_div_code),
            "FID_COND_SCR_DIV_CODE": "20171",
            "FID_INPUT_ISCD": "0000",
            "FID_DIV_CLS_CODE": "0",
            "FID_BLNG_CLS_CODE": "1" if kind == "etf" else "0",
            "FID_TRGT_CLS_CODE": "",
            "FID_TRGT_EXLS_CLS_CODE": "",
            "FID_INPUT_PRICE_1": str(price_from),
            "FID_INPUT_PRICE_2": str(price_to),
            "FID_VOL_CNT": "0",
            "FID_INPUT_DATE_1": "",
        }

    def _parse_volume_rank_rows(
        self,
        rows: list[dict[str, Any]],
        *,
        venue_market: str,
    ) -> list[dict[str, Any]]:
        parsed_rows: list[dict[str, Any]] = []
        for r in rows or []:
            parsed_rows.append(
                {
                    "code": str(r.get("mksc_shrn_iscd", "")),
                    "name": str(r.get("hts_kor_isnm", "")),
                    "price": self._to_int(r.get("stck_prpr")),
                    "volume": self._to_int(r.get("acml_vol")),
                    "value": self._to_int(r.get("acml_tr_pbmn")),
                    "change_rate": self._to_float(r.get("prdy_ctrt")),
                    "market_cap": self._to_int(r.get("stck_avls")) * 100_000_000,
                    "venue_market": str(venue_market),
                }
            )
        return parsed_rows

    def _upsert_rank_row(
        self,
        merged_by_code: dict[str, dict[str, Any]],
        row: dict[str, Any],
        *,
        prefer_field: str,
    ) -> None:
        code = str(row.get("code") or "").strip()
        if not code:
            return
        existing = merged_by_code.get(code)
        if existing is None:
            merged_by_code[code] = row
            return
        if int(row.get(prefer_field, 0)) > int(existing.get(prefer_field, 0)):
            merged_by_code[code] = row

    def _parse_hts_top_view_rows(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        rows = data.get("output2") or data.get("output") or []
        parsed_rows: list[dict[str, Any]] = []
        for raw in rows or []:
            parsed_rows.append(
                {
                    "code": str(
                        raw.get("mksc_shrn_iscd")
                        or raw.get("stck_shrn_iscd")
                        or raw.get("shrn_iscd")
                        or raw.get("iscd")
                        or ""
                    ),
                    "name": str(
                        raw.get("hts_kor_isnm")
                        or raw.get("kor_isnm")
                        or raw.get("stck_kor_isnm")
                        or raw.get("name")
                        or ""
                    ),
                    "rank": self._to_int(raw.get("data_rank") or raw.get("hts_rank") or raw.get("rank")),
                    "view_count": self._to_int(
                        raw.get("nsel_cnt") or raw.get("seln_cnt") or raw.get("view_cnt")
                    ),
                    "price": self._to_int(raw.get("stck_prpr")),
                    "change_rate": self._to_float(raw.get("prdy_ctrt")),
                }
            )
        return [row for row in parsed_rows if str(row.get("code") or "").strip()]

    def market_cap_rank(self, top_k: int, asof: str) -> list[dict[str, Any]]:
        """
        시가총액 기준 상위 종목 조회.
        volume_rank API를 시가총액 기준 정렬로 활용.
        """
        del asof
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_COND_SCR_DIV_CODE": "20171",
            "FID_INPUT_ISCD": "0000",
            "FID_DIV_CLS_CODE": "0",
            "FID_BLNG_CLS_CODE": "0",
            "FID_TRGT_CLS_CODE": "",
            "FID_TRGT_EXLS_CLS_CODE": "",
            "FID_INPUT_PRICE_1": "0",
            "FID_INPUT_PRICE_2": "0",
            "FID_VOL_CNT": "0",
            "FID_INPUT_DATE_1": "",
        }
        try:
            data = self._market_get(
                "/uapi/domestic-stock/v1/quotations/volume-rank",
                "FHPST01710000",
                params,
            )
        except requests.exceptions.RequestException as exc:
            logger.warning("market_cap_rank request failed top_k=%s error=%s", top_k, exc)
            return []
        rows = data.get("output", [])
        sorted_rows = sorted(
            rows, key=lambda r: int(r.get("stck_avls", 0)), reverse=True
        )
        result = []
        for r in sorted_rows[:top_k]:
            result.append(
                {
                    "code": r.get("mksc_shrn_iscd", ""),
                    "name": r.get("hts_kor_isnm", ""),
                    "market_cap": int(r.get("stck_avls", 0)) * 100_000_000,
                    "price": int(r.get("stck_prpr", 0)),
                    "volume": int(r.get("acml_vol", 0)),
                }
            )
        return result

    def daily_bars(self, code: str, end: str, lookback: int) -> pd.DataFrame:
        """
        국내주식 기간별 시세 (일봉) 조회 [v1_국내주식-016].
        GET /uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice
        """
        normalized_code = str(code or "").strip()
        normalized_end = self._normalize_yyyymmdd(end)
        cache_key = (normalized_code, normalized_end, int(lookback))
        ttl_sec = float(getattr(self, "_daily_bars_cache_ttl_sec", 0.0))
        cached = self._cache_lookup("_daily_bars_cache", cache_key, ttl_sec)
        if cached is not None:
            return cached

        end_dt = datetime.strptime(normalized_end, "%Y%m%d") if len(normalized_end) == 8 else datetime.now()
        start_dt = end_dt - timedelta(days=lookback * 2)
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": normalized_code,
            "FID_INPUT_DATE_1": start_dt.strftime("%Y%m%d"),
            "FID_INPUT_DATE_2": end_dt.strftime("%Y%m%d"),
            "FID_PERIOD_DIV_CODE": "D",
            "FID_ORG_ADJ_PRC": "0",
        }
        data = self._market_get(
            "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
            "FHKST03010100",
            params,
        )
        rows = data.get("output2", [])
        if not rows:
            return self._cache_store(
                "_daily_bars_cache",
                cache_key,
                pd.DataFrame(),
                ttl_sec,
            )

        records = []
        for r in rows:
            dt = r.get("stck_bsop_date", "")
            if not dt:
                continue
            records.append(
                {
                    "date": dt,
                    "open": int(r.get("stck_oprc", 0)),
                    "high": int(r.get("stck_hgpr", 0)),
                    "low": int(r.get("stck_lwpr", 0)),
                    "close": int(r.get("stck_clpr", 0)),
                    "volume": int(r.get("acml_vol", 0)),
                    "value": int(r.get("acml_tr_pbmn", 0)),
                }
            )
        df = pd.DataFrame(records)
        if df.empty:
            return self._cache_store(
                "_daily_bars_cache",
                cache_key,
                df,
                ttl_sec,
            )
        df = df.sort_values("date").tail(lookback).reset_index(drop=True)
        return self._cache_store(
            "_daily_bars_cache",
            cache_key,
            df,
            ttl_sec,
        )

    def daily_index_bars(
        self,
        index_code: str,
        end: str,
        lookback: int,
    ) -> pd.DataFrame:
        """
        국내주식업종기간별시세(일/주/월/년) 조회 [v1_국내주식-021].
        GET /uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice
        """
        normalized_index_code = str(index_code or "").strip().zfill(4)
        normalized_end = self._normalize_yyyymmdd(end)
        cache_key = (normalized_index_code, normalized_end, int(lookback))
        ttl_sec = float(getattr(self, "_daily_index_bars_cache_ttl_sec", 0.0))
        cached = self._cache_lookup("_daily_index_bars_cache", cache_key, ttl_sec)
        if cached is not None:
            return cached

        end_dt = datetime.strptime(normalized_end, "%Y%m%d") if len(normalized_end) == 8 else datetime.now()
        start_dt = end_dt - timedelta(days=lookback * 2)
        params = {
            "FID_COND_MRKT_DIV_CODE": "U",
            "FID_INPUT_ISCD": normalized_index_code,
            "FID_INPUT_DATE_1": start_dt.strftime("%Y%m%d"),
            "FID_INPUT_DATE_2": end_dt.strftime("%Y%m%d"),
            "FID_PERIOD_DIV_CODE": "D",
        }
        data = self._market_get(
            "/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice",
            "FHKUP03500100",
            params,
        )
        rows = data.get("output2", [])
        if not rows:
            return self._cache_store(
                "_daily_index_bars_cache",
                cache_key,
                pd.DataFrame(),
                ttl_sec,
            )

        records = []
        for r in rows:
            dt = r.get("stck_bsop_date", "")
            if not dt:
                continue
            records.append(
                {
                    "date": dt,
                    "open": self._to_float(r.get("bstp_nmix_oprc")),
                    "high": self._to_float(r.get("bstp_nmix_hgpr")),
                    "low": self._to_float(r.get("bstp_nmix_lwpr")),
                    "close": self._to_float(r.get("bstp_nmix_prpr")),
                    "volume": self._to_int(r.get("acml_vol")),
                    "value": self._to_int(r.get("acml_tr_pbmn")),
                }
            )
        df = pd.DataFrame(records)
        if df.empty:
            return self._cache_store(
                "_daily_index_bars_cache",
                cache_key,
                df,
                ttl_sec,
            )
        df = df.sort_values("date").tail(lookback).reset_index(drop=True)
        return self._cache_store(
            "_daily_index_bars_cache",
            cache_key,
            df,
            ttl_sec,
        )

    def _parse_intraday_rows(self, rows: list[dict[str, Any]]) -> pd.DataFrame:
        records: list[dict[str, Any]] = []
        for r in rows or []:
            date = self._normalize_yyyymmdd(r.get("stck_bsop_date", ""))
            hhmmss = str(r.get("stck_cntg_hour", "")).strip().zfill(6)
            if not date or not hhmmss:
                continue
            records.append(
                {
                    "date": date,
                    "time": hhmmss,
                    "timestamp": f"{date}{hhmmss}",
                    "open": self._to_int(r.get("stck_oprc")),
                    "high": self._to_int(r.get("stck_hgpr")),
                    "low": self._to_int(r.get("stck_lwpr")),
                    "close": self._to_int(r.get("stck_prpr")),
                    "volume": self._to_int(r.get("cntg_vol")),
                    "value": self._to_int(r.get("acml_tr_pbmn")),
                    "change_pct": self._to_float(r.get("prdy_ctrt")),
                    "prev_close": self._to_int(r.get("stck_prdy_clpr")),
                }
            )
        return pd.DataFrame(records)

    def time_itemchart_bars(
        self,
        code: str,
        *,
        hour: str | None = None,
        include_past: bool = True,
        market_div_code: str = "J",
    ) -> pd.DataFrame:
        """
        주식당일분봉조회 [v1_국내주식-022].
        GET /uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice
        """
        input_hour = str(hour or datetime.now().strftime("%H%M%S")).zfill(6)
        params = {
            "FID_COND_MRKT_DIV_CODE": market_div_code,
            "FID_INPUT_ISCD": code,
            "FID_INPUT_HOUR_1": input_hour,
            "FID_PW_DATA_INCU_YN": "Y" if include_past else "N",
            "FID_ETC_CLS_CODE": "",
        }
        data = self._market_get(
            "/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice",
            "FHKST03010200",
            params,
        )
        return self._parse_intraday_rows(data.get("output2", []))

    def time_dailychart_bars(
        self,
        code: str,
        *,
        date: str,
        hour: str | None = None,
        include_past: bool = True,
        include_fake_tick: bool = False,
        market_div_code: str = "J",
    ) -> pd.DataFrame:
        """
        주식일별분봉조회 [v1_국내주식-213].
        GET /uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice
        """
        input_hour = str(hour or datetime.now().strftime("%H%M%S")).zfill(6)
        params = {
            "FID_COND_MRKT_DIV_CODE": market_div_code,
            "FID_INPUT_ISCD": code,
            "FID_INPUT_HOUR_1": input_hour,
            "FID_INPUT_DATE_1": self._normalize_yyyymmdd(date),
            "FID_PW_DATA_INCU_YN": "Y" if include_past else "N",
            "FID_FAKE_TICK_INCU_YN": "Y" if include_fake_tick else "",
        }
        data = self._market_get(
            "/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice",
            "FHKST03010230",
            params,
        )
        return self._parse_intraday_rows(data.get("output2", []))

    def intraday_bars(self, code: str, asof: str, lookback: int = 120) -> pd.DataFrame:
        """
        장중 급락 감지를 위한 통합 분봉.
        - 당일분봉(inquire-time-itemchartprice)
        - 일별분봉(inquire-time-dailychartprice)
        """
        asof_day = self._normalize_yyyymmdd(asof)
        input_hour = datetime.now().strftime("%H%M%S")

        frames: list[pd.DataFrame] = []
        try:
            frames.append(
                self.time_itemchart_bars(
                    code,
                    hour=input_hour,
                    include_past=True,
                    market_div_code="J",
                )
            )
        except Exception as exc:
            logger.warning("time_itemchart_bars failed code=%s error=%s", code, exc)

        try:
            frames.append(
                self.time_dailychart_bars(
                    code,
                    date=asof_day,
                    hour=input_hour,
                    include_past=True,
                    include_fake_tick=False,
                    market_div_code="J",
                )
            )
        except Exception as exc:
            logger.warning("time_dailychart_bars failed code=%s error=%s", code, exc)

        non_empty = [f for f in frames if f is not None and not f.empty]
        if not non_empty:
            return pd.DataFrame()

        merged = pd.concat(non_empty, ignore_index=True)
        if "timestamp" in merged.columns:
            merged = merged.sort_values("timestamp", ascending=True)
            merged = merged.drop_duplicates(subset=["timestamp"], keep="last")
        else:
            merged = merged.sort_values(["date", "time"], ascending=True)
            merged = merged.drop_duplicates(subset=["date", "time"], keep="last")
        return merged.tail(max(1, int(lookback))).reset_index(drop=True)

    def quote(self, code: str) -> dict[str, Any]:
        """
        국내주식 현재가 조회 [v1_국내주식-008].
        GET /uapi/domestic-stock/v1/quotations/inquire-price
        """
        normalized_code = str(code or "").strip()
        ttl_sec = float(getattr(self, "_quote_cache_ttl_sec", 0.0))
        cached = self._cache_lookup("_quote_cache", normalized_code, ttl_sec)
        if cached is not None:
            return cached

        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": normalized_code,
        }
        data = self._market_get(
            "/uapi/domestic-stock/v1/quotations/inquire-price",
            "FHKST01010100",
            params,
        )
        out = data.get("output", {})
        payload = {
            "code": normalized_code,
            "price": int(out.get("stck_prpr", 0)),
            "open": int(out.get("stck_oprc", 0)),
            "high": int(out.get("stck_hgpr", 0)),
            "low": int(out.get("stck_lwpr", 0)),
            "volume": int(out.get("acml_vol", 0)),
            "change_rate": float(out.get("prdy_ctrt", 0)),
            "change_pct": float(out.get("prdy_ctrt", 0)),
            "market_cap": int(out.get("hts_avls", 0)) * 100_000_000,
            "market_warning_code": str(out.get("mrkt_warn_cls_code", "")).strip(),
            "management_issue_code": str(out.get("mang_issu_cls_code", "")).strip(),
        }
        return self._cache_store("_quote_cache", normalized_code, payload, ttl_sec)
