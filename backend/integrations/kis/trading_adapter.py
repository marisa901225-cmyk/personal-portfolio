"""
KIS 한국투자증권 Trading Adapter
================================
TradingAPI 프로토콜을 KIS OpenAPI로 구현하는 어댑터.

환경변수:
    TRADING_ENGINE_API_FACTORY=backend.integrations.kis.trading_adapter:create_trading_api

API 참고:
    - 주식주문(현금) [v1_국내주식-001]: POST /uapi/domestic-stock/v1/trading/order-cash
    - 주식잔고조회   [v1_국내주식-006]: GET  /uapi/domestic-stock/v1/trading/inquire-balance
"""
from __future__ import annotations

from datetime import datetime
import json
import logging
import time
from typing import Any

import pandas as pd
import requests

logger = logging.getLogger(__name__)

_KIS_HTTP_CONNECT_TIMEOUT_SEC = 3.05
_KIS_HTTP_READ_TIMEOUT_SEC = 10.0
_KIS_HTTP_GET_MAX_ATTEMPTS = 3
_KIS_HTTP_RETRY_BACKOFF_SEC = 0.35
_KIS_HTTP_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


class KISTradingAPI:
    """KIS OpenAPI 기반 TradingAPI 프로토콜 구현체."""

    def __init__(self) -> None:
        from . import kis_client as core

        core._ensure_kis_modules_loaded()
        core._ensure_auth()

        self._core = core
        self._ka = core.ka  # kis_auth module reference
        import kis_auth_rest  # type: ignore

        self._session = requests.Session()
        self._rest_throttle = kis_auth_rest._throttle_rest
        logger.info("[KIS TradingAPI] 어댑터 초기화 완료")

    # ──────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────

    def _headers(self, tr_id: str, tr_cont: str = "") -> dict[str, str]:
        """REST 요청용 공통 헤더를 생성한다."""
        h = self._ka._getBaseHeader()
        h["tr_id"] = tr_id
        h["custtype"] = "P"
        if tr_cont:
            h["tr_cont"] = tr_cont
        return h

    def _base_url(self) -> str:
        return self._ka.getTREnv().my_url

    def _account(self) -> tuple[str, str]:
        """계좌번호 (CANO 8자리, ACNT_PRDT_CD 2자리) 반환."""
        acct = self._ka.getTREnv().my_acct
        return acct[:8], acct[8:10] if len(acct) >= 10 else "01"

    def _throttle_rest(self) -> None:
        throttle = getattr(self, "_rest_throttle", None)
        if callable(throttle):
            throttle()
            return
        # Fallback for partially initialized test doubles.
        time.sleep(0.05)

    @staticmethod
    def _normalize_yyyymmdd(value: str) -> str:
        raw = str(value or "").strip()
        if "-" in raw:
            raw = raw.replace("-", "")
        return raw[:8]

    @staticmethod
    def _to_int(value: Any) -> int:
        text = str(value or "").replace(",", "").strip()
        if not text:
            return 0
        try:
            return int(float(text))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _to_float(value: Any) -> float:
        text = str(value or "").replace(",", "").strip()
        if not text:
            return 0.0
        try:
            return float(text)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _is_retryable_get_exception(exc: requests.exceptions.RequestException) -> bool:
        if isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
            return True

        if isinstance(exc, requests.exceptions.HTTPError):
            response = getattr(exc, "response", None)
            status_code = getattr(response, "status_code", None)
            return status_code in _KIS_HTTP_RETRYABLE_STATUS

        return False

    @staticmethod
    def _get_retry_delay_seconds(attempt: int) -> float:
        return _KIS_HTTP_RETRY_BACKOFF_SEC * (2 ** max(0, attempt - 1))

    @staticmethod
    def _order_division_code(order_type: str) -> str:
        order_kind = str(order_type or "").strip().lower()
        ord_dvsn_map = {
            "limit": "00",       # 지정가
            "market": "01",      # 시장가
            "mkt": "01",         # 시장가 (alias)
            "conditional": "02", # 조건부지정가
            "best": "03",        # 최유리지정가
            "priority": "04",    # 최우선지정가
        }
        return ord_dvsn_map.get(order_kind, "00")

    def _get(self, path: str, tr_id: str, params: dict, tr_cont: str = "") -> dict:
        """GET 요청 래퍼."""
        url = f"{self._base_url()}{path}"
        for attempt in range(1, _KIS_HTTP_GET_MAX_ATTEMPTS + 1):
            self._core._ensure_auth()
            headers = self._headers(tr_id, tr_cont)
            self._throttle_rest()
            try:
                res = self._session.get(
                    url,
                    headers=headers,
                    params=params,
                    timeout=(_KIS_HTTP_CONNECT_TIMEOUT_SEC, _KIS_HTTP_READ_TIMEOUT_SEC),
                )
                res.raise_for_status()
                data = res.json()
                if data.get("rt_cd") != "0":
                    logger.error(
                        "[KIS API] GET 실패: tr_id=%s msg=%s", tr_id, data.get("msg1")
                    )
                return data
            except requests.exceptions.RequestException as exc:
                is_last_attempt = attempt >= _KIS_HTTP_GET_MAX_ATTEMPTS
                retryable = self._is_retryable_get_exception(exc)
                if not retryable or is_last_attempt:
                    logger.warning(
                        "[KIS API] GET 요청 실패: tr_id=%s path=%s attempt=%s/%s retryable=%s error=%s",
                        tr_id,
                        path,
                        attempt,
                        _KIS_HTTP_GET_MAX_ATTEMPTS,
                        retryable,
                        exc,
                    )
                    raise

                delay = self._get_retry_delay_seconds(attempt)
                logger.warning(
                    "[KIS API] GET 재시도 예정: tr_id=%s path=%s attempt=%s/%s backoff=%.2fs error=%s",
                    tr_id,
                    path,
                    attempt,
                    _KIS_HTTP_GET_MAX_ATTEMPTS,
                    delay,
                    exc,
                )
                time.sleep(delay)

        raise RuntimeError(f"unreachable KIS GET retry flow: tr_id={tr_id} path={path}")

    def _post(self, path: str, tr_id: str, body: dict) -> dict:
        """POST 요청 래퍼."""
        self._core._ensure_auth()
        url = f"{self._base_url()}{path}"
        headers = self._headers(tr_id)
        # hashkey 설정
        self._ka.set_order_hash_key(headers, body)
        self._throttle_rest()
        try:
            res = self._session.post(
                url,
                headers=headers,
                data=json.dumps(body),
                timeout=(_KIS_HTTP_CONNECT_TIMEOUT_SEC, _KIS_HTTP_READ_TIMEOUT_SEC),
            )
        except requests.exceptions.RequestException as exc:
            logger.warning(
                "[KIS API] POST 전송 실패: tr_id=%s path=%s error=%s",
                tr_id,
                path,
                exc,
            )
            raise
        res.raise_for_status()
        data = res.json()
        if data.get("rt_cd") != "0":
            logger.error(
                "[KIS API] POST 실패: tr_id=%s msg=%s", tr_id, data.get("msg1")
            )
        return data

    # ──────────────────────────────────────────────
    # TradingAPI protocol methods
    # ──────────────────────────────────────────────

    def volume_rank(
        self, kind: str, top_n: int, asof: str
    ) -> list[dict[str, Any]]:
        """
        거래량 랭킹 조회 [v1_국내주식-047].
        GET /uapi/domestic-stock/v1/quotations/volume-rank
        """
        del asof
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",  # 주식
            "FID_COND_SCR_DIV_CODE": "20171",
            "FID_INPUT_ISCD": "0000",  # 전체
            "FID_DIV_CLS_CODE": "0",  # 전체
            "FID_BLNG_CLS_CODE": "1" if kind == "etf" else "0",
            "FID_TRGT_CLS_CODE": "",
            "FID_TRGT_EXLS_CLS_CODE": "",
            "FID_INPUT_PRICE_1": "0",
            "FID_INPUT_PRICE_2": "0",
            "FID_VOL_CNT": "0",
            "FID_INPUT_DATE_1": "",
        }
        try:
            data = self._get(
                "/uapi/domestic-stock/v1/quotations/volume-rank",
                "FHPST01710000",
                params,
            )
        except requests.exceptions.RequestException as exc:
            logger.warning(
                "volume_rank request failed kind=%s top_n=%s error=%s",
                kind,
                top_n,
                exc,
            )
            return []
        rows = data.get("output", [])
        result = []
        for r in rows[:top_n]:
            result.append(
                {
                    "code": r.get("mksc_shrn_iscd", ""),  # 종목코드
                    "name": r.get("hts_kor_isnm", ""),  # 종목명
                    "price": int(r.get("stck_prpr", 0)),  # 현재가
                    "volume": int(r.get("acml_vol", 0)),  # 누적거래량
                    "change_rate": float(r.get("prdy_ctrt", 0)),  # 전일대비율
                    "market_cap": int(r.get("stck_avls", 0)) * 100_000_000,
                }
            )
        return result

    def market_cap_rank(
        self, top_k: int, asof: str
    ) -> list[dict[str, Any]]:
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
            data = self._get(
                "/uapi/domestic-stock/v1/quotations/volume-rank",
                "FHPST01710000",
                params,
            )
        except requests.exceptions.RequestException as exc:
            logger.warning("market_cap_rank request failed top_k=%s error=%s", top_k, exc)
            return []
        rows = data.get("output", [])
        # 시가총액 기준 정렬
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

    def daily_bars(
        self, code: str, end: str, lookback: int
    ) -> pd.DataFrame:
        """
        국내주식 기간별 시세 (일봉) 조회 [v1_국내주식-016].
        GET /uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice
        """
        from datetime import datetime, timedelta

        end_dt = datetime.strptime(end, "%Y%m%d") if len(end) == 8 else datetime.now()
        start_dt = end_dt - timedelta(days=lookback * 2)  # 영업일 고려
        start_str = start_dt.strftime("%Y%m%d")
        end_str = end_dt.strftime("%Y%m%d")

        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": code,
            "FID_INPUT_DATE_1": start_str,
            "FID_INPUT_DATE_2": end_str,
            "FID_PERIOD_DIV_CODE": "D",         # 일봉
            "FID_ORG_ADJ_PRC": "0",             # 수정주가 미반영(0) / 반영(1)
        }
        data = self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
            "FHKST03010100",
            params,
        )
        rows = data.get("output2", [])
        if not rows:
            return pd.DataFrame()

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
            return df
        df = df.sort_values("date").tail(lookback).reset_index(drop=True)
        return df

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
        data = self._get(
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
        data = self._get(
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
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": code,
        }
        data = self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-price",
            "FHKST01010100",
            params,
        )
        out = data.get("output", {})
        return {
            "code": code,
            "price": int(out.get("stck_prpr", 0)),
            "open": int(out.get("stck_oprc", 0)),
            "high": int(out.get("stck_hgpr", 0)),
            "low": int(out.get("stck_lwpr", 0)),
            "volume": int(out.get("acml_vol", 0)),
            "change_rate": float(out.get("prdy_ctrt", 0)),
            "change_pct": float(out.get("prdy_ctrt", 0)),
            "market_cap": int(out.get("hts_avls", 0)),
        }

    def positions(self) -> list[dict[str, Any]]:
        """
        주식 잔고 조회 [v1_국내주식-006].
        GET /uapi/domestic-stock/v1/trading/inquire-balance
        """
        cano, acnt_prdt_cd = self._account()
        params = {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt_prdt_cd,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "01",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "00",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }
        data = self._get(
            "/uapi/domestic-stock/v1/trading/inquire-balance",
            "TTTC8434R",
            params,
        )
        output1 = data.get("output1", [])
        result = []
        for r in output1:
            qty = int(r.get("hldg_qty", 0))
            if qty <= 0:
                continue
            result.append(
                {
                    "code": r.get("pdno", ""),
                    "name": r.get("prdt_name", ""),
                    "qty": qty,
                    "avg_price": float(r.get("pchs_avg_pric", 0)),
                    "current_price": int(r.get("prpr", 0)),
                    "pnl": int(r.get("evlu_pfls_amt", 0)),
                    "pnl_rate": float(r.get("evlu_pfls_rt", 0)),
                    "orderable_qty": int(r.get("ord_psbl_qty", 0)),
                }
            )
        return result

    def cash_available(self) -> int:
        """
        주문 가능 현금(예수금) 조회.
        잔고 조회 API의 output2에서 D+2 예수금(prvs_rcdl_excc_amt)을 사용한다.
        """
        cano, acnt_prdt_cd = self._account()
        params = {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt_prdt_cd,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "01",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "00",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }
        data = self._get(
            "/uapi/domestic-stock/v1/trading/inquire-balance",
            "TTTC8434R",
            params,
        )
        output2 = data.get("output2", [])
        if output2:
            row = output2[0] if isinstance(output2, list) else output2
            # D+2 예수금(가수도정산금액)이 가장 안전한 주문 가능 금액
            return int(row.get("prvs_rcdl_excc_amt", 0))
        return 0

    def buy_order_capacity(
        self,
        code: str,
        order_type: str,
        price: int | None,
    ) -> dict[str, Any]:
        """
        종목별 매수가능조회.

        잔고조회 예수금이 아니라 KIS의 주문 심사 기준에 맞춘
        주문가능현금/미수없는매수금액/매수수량을 반환한다.
        """
        cano, acnt_prdt_cd = self._account()
        query_price = self._to_int(price)
        ord_dvsn = self._order_division_code(order_type)
        params = {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt_prdt_cd,
            "PDNO": code,
            "ORD_UNPR": str(query_price),
            "ORD_DVSN": ord_dvsn,
            "CMA_EVLU_AMT_ICLD_YN": "N",
            "OVRS_ICLD_YN": "N",
        }
        data = self._get(
            "/uapi/domestic-stock/v1/trading/inquire-psbl-order",
            "TTTC8908R",
            params,
        )
        output = data.get("output", {})
        row = output[0] if isinstance(output, list) and output else output
        if not isinstance(row, dict):
            row = {}

        result = {
            "ord_psbl_cash": self._to_int(row.get("ord_psbl_cash")),
            "nrcvb_buy_amt": self._to_int(row.get("nrcvb_buy_amt")),
            "nrcvb_buy_qty": self._to_int(row.get("nrcvb_buy_qty")),
            "max_buy_amt": self._to_int(row.get("max_buy_amt")),
            "max_buy_qty": self._to_int(row.get("max_buy_qty")),
            "psbl_qty_calc_unpr": self._to_int(row.get("psbl_qty_calc_unpr")),
        }
        logger.info(
            "[KIS 매수가능조회] code=%s type=%s price=%s cash=%s nrcvb_amt=%s nrcvb_qty=%s calc_price=%s",
            code,
            order_type,
            query_price,
            result["ord_psbl_cash"],
            result["nrcvb_buy_amt"],
            result["nrcvb_buy_qty"],
            result["psbl_qty_calc_unpr"],
        )
        return result

    def sell_order_capacity(self, code: str) -> dict[str, Any]:
        """
        종목별 매도가능수량조회.

        보유수량과 별개로 현재 주문 가능한 실제 매도 수량을 반환한다.
        """
        cano, acnt_prdt_cd = self._account()
        params = {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt_prdt_cd,
            "PDNO": code,
        }
        data = self._get(
            "/uapi/domestic-stock/v1/trading/inquire-psbl-sell",
            "TTTC8408R",
            params,
        )
        output = data.get("output", {})
        row = output[0] if isinstance(output, list) and output else output
        if not isinstance(row, dict):
            row = {}

        result = {
            "ord_psbl_qty": self._to_int(row.get("ord_psbl_qty")),
            "hldg_qty": self._to_int(row.get("hldg_qty")),
        }
        logger.info(
            "[KIS 매도가능조회] code=%s sellable_qty=%s holding_qty=%s",
            code,
            result["ord_psbl_qty"],
            result["hldg_qty"],
        )
        return result

    def place_order(
        self,
        side: str,
        code: str,
        qty: int,
        order_type: str,
        price: int | None,
    ) -> dict[str, Any]:
        """
        주식 주문(현금) [v1_국내주식-001].
        POST /uapi/domestic-stock/v1/trading/order-cash

        Args:
            side: "buy" 또는 "sell"
            code: 종목코드 6자리
            qty: 주문수량
            order_type: "limit"(지정가) 또는 "market"(시장가)
            price: 주문단가 (시장가일 경우 None 또는 0)
        """
        cano, acnt_prdt_cd = self._account()

        # TR ID 결정: 실전 매도=TTTC0011U, 매수=TTTC0012U
        if side.lower() in ("sell", "매도"):
            tr_id = "TTTC0011U"
        else:
            tr_id = "TTTC0012U"

        ord_dvsn = self._order_division_code(order_type)

        body = {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt_prdt_cd,
            "PDNO": code,
            "ORD_DVSN": ord_dvsn,
            "ORD_QTY": str(qty),
            "ORD_UNPR": str(price or 0),
        }

        logger.info(
            "[KIS 주문] side=%s code=%s qty=%d type=%s price=%s",
            side, code, qty, order_type, price,
        )
        data = self._post(
            "/uapi/domestic-stock/v1/trading/order-cash",
            tr_id,
            body,
        )
        output = data.get("output", {})
        success = data.get("rt_cd") == "0"
        result = {
            "success": success,
            "order_id": output.get("ODNO", ""),
            "order_time": output.get("ORD_TMD", ""),
            "exchange": output.get("KRX_FWDG_ORD_ORGNO", ""),
            "msg": data.get("msg1", ""),
        }
        if success:
            logger.info("[KIS 주문 성공] %s", result)
        else:
            logger.error("[KIS 주문 실패] %s", result)
        return result

    def open_orders(self) -> list[dict[str, Any]]:
        """
        미체결 주문 조회 [v1_국내주식-004].
        GET /uapi/domestic-stock/v1/trading/inquire-psbl-rvsecncl
        """
        cano, acnt_prdt_cd = self._account()
        params = {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt_prdt_cd,
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
            "INQR_DVSN_1": "0",   # 조회 구분 (0: 전체)
            "INQR_DVSN_2": "0",   # 조회 구분2 (0: 전체)
        }
        data = self._get(
            "/uapi/domestic-stock/v1/trading/inquire-psbl-rvsecncl",
            "TTTC8036R",
            params,
        )
        output = data.get("output", [])
        result = []
        for r in output:
            result.append(
                {
                    "order_id": r.get("odno", ""),
                    "code": r.get("pdno", ""),
                    "name": r.get("prdt_name", ""),
                    "side": "buy" if r.get("sll_buy_dvsn_cd") == "02" else "sell",
                    "qty": int(r.get("ord_qty", 0)),
                    "price": int(r.get("ord_unpr", 0)),
                    "filled_qty": int(r.get("tot_ccld_qty", 0)),
                    "remaining_qty": int(r.get("psbl_qty", 0)),
                    "order_time": r.get("ord_tmd", ""),
                }
            )
        return result

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        """
        주식 주문 취소 [v1_국내주식-003].
        POST /uapi/domestic-stock/v1/trading/order-rvsecncl
        """
        cano, acnt_prdt_cd = self._account()
        body = {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt_prdt_cd,
            "KRX_FWDG_ORD_ORGNO": "",
            "ORGN_ODNO": order_id,
            "ORD_DVSN": "00",
            "RVSE_CNCL_DVSN_CD": "02",  # 02: 취소
            "ORD_QTY": "0",             # 잔량 전부 취소
            "ORD_UNPR": "0",
            "QTY_ALL_ORD_YN": "Y",      # 잔량 전부
        }
        logger.info("[KIS 주문취소] order_id=%s", order_id)
        data = self._post(
            "/uapi/domestic-stock/v1/trading/order-rvsecncl",
            "TTTC0013U",
            body,
        )
        success = data.get("rt_cd") == "0"
        result = {
            "success": success,
            "order_id": order_id,
            "msg": data.get("msg1", ""),
        }
        if success:
            logger.info("[KIS 주문취소 성공] %s", result)
        else:
            logger.error("[KIS 주문취소 실패] %s", result)
        return result

    def inquire_realized_pnl(self) -> dict[str, Any]:
        """
        주식잔고조회_실현손익 [v1_국내주식-041].
        GET /uapi/domestic-stock/v1/trading/inquire-balance-rlz-pl

        오늘 체결 기준 실현손익 및 종목별 매도 평균단가를 반환한다.
        (모의투자 미지원 - 실전 전용)
        """
        cano, acnt_prdt_cd = self._account()
        params = {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt_prdt_cd,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "00",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "01",       # 01: 전일매매 미포함 (오늘만)
            "COST_ICLD_YN": "Y",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }
        data = self._get(
            "/uapi/domestic-stock/v1/trading/inquire-balance-rlz-pl",
            "TTTC8494R",
            params,
        )
        if data.get("rt_cd") != "0":
            logger.warning(
                "[KIS 실현손익 조회 실패] msg=%s", data.get("msg1")
            )
        return data

    def get_today_sell_avg_price(self, code: str) -> float | None:
        """
        오늘 매도한 특정 종목의 KIS 체결기준 실제 평균단가를 조회한다.
        inquire_realized_pnl() output1에서 종목코드로 필터링.

        Returns:
            실제 체결 평균단가 (float), 없으면 None
        """
        try:
            data = self.inquire_realized_pnl()
            for row in data.get("output1", []):
                if row.get("pdno", "").strip() != code.strip():
                    continue
                sll_qty = int(row.get("thdt_sll_qty", 0) or 0)
                if sll_qty <= 0:
                    continue
                avg = float(row.get("pchs_avg_pric", 0) or 0)
                if avg > 0:
                    logger.info(
                        "[KIS 실현손익] %s 오늘 매도 체결 평단가: %.0f (qty=%d)",
                        code, avg, sll_qty,
                    )
                    return avg
        except Exception as exc:
            logger.warning("[KIS 실현손익 조회 예외] code=%s err=%s", code, exc)
        return None


# ──────────────────────────────────────────────
# Factory function (TRADING_ENGINE_API_FACTORY 용)
# ──────────────────────────────────────────────

def create_trading_api() -> KISTradingAPI:
    """
    Trading engine이 호출하는 팩토리 함수.

    사용법:
        TRADING_ENGINE_API_FACTORY=backend.integrations.kis.trading_adapter:create_trading_api
    """
    logger.info("[KIS TradingAPI] 팩토리 함수 호출 → KISTradingAPI 생성")
    return KISTradingAPI()
