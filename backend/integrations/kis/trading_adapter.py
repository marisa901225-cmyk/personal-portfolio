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

import json
import logging
import os
import time
from typing import Any

import pandas as pd
import requests
from backend.integrations.kis.rest_rate_limiter import throttle_rest_min_gap
from backend.integrations.kis.secondary_market_context import build_secondary_market_context

from .trading_account_mixin import KISAccountTradingMixin
from .trading_market_data_mixin import KISMarketDataMixin

logger = logging.getLogger(__name__)

_KIS_HTTP_CONNECT_TIMEOUT_SEC = 3.05
_KIS_HTTP_READ_TIMEOUT_SEC = 10.0
_KIS_HTTP_GET_MAX_ATTEMPTS = 3
_KIS_HTTP_RETRY_BACKOFF_SEC = 0.35
_KIS_HTTP_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


def _env_float(name: str, default: float) -> float:
    raw = str(os.getenv(name, "") or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


_KIS_HTTP_PATH_MIN_GAP_SEC = {
    "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice": _env_float(
        "KIS_DAILY_CHART_MIN_GAP_SEC",
        0.12,
    ),
    "/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice": _env_float(
        "KIS_DAILY_INDEX_CHART_MIN_GAP_SEC",
        0.12,
    ),
    "/uapi/domestic-stock/v1/quotations/inquire-price": _env_float(
        "KIS_QUOTE_MIN_GAP_SEC",
        0.10,
    ),
}
_KIS_DAILY_BARS_CACHE_TTL_SEC = max(0.0, _env_float("KIS_DAILY_BARS_CACHE_TTL_SEC", 300.0))
_KIS_DAILY_INDEX_BARS_CACHE_TTL_SEC = max(0.0, _env_float("KIS_DAILY_INDEX_BARS_CACHE_TTL_SEC", 300.0))
_KIS_QUOTE_CACHE_TTL_SEC = max(0.0, _env_float("KIS_QUOTE_CACHE_TTL_SEC", 20.0))
_KIS_RANK_MARKET_DIV_CODES: tuple[str, ...] = ("J", "NX")
_KIS_VALUE_RANK_PRICE_BUCKETS: tuple[tuple[str, str], ...] = (
    ("0", "1000"),
    ("1000", "2000"),
    ("2000", "5000"),
    ("5000", "10000"),
    ("10000", "20000"),
    ("20000", "50000"),
    ("50000", "100000"),
    ("100000", "200000"),
    ("200000", "500000"),
    ("500000", "9999999"),
)


class KISTradingBase:
    """KIS OpenAPI 공통 세션/헬퍼 구현체."""

    _rank_market_div_codes = _KIS_RANK_MARKET_DIV_CODES
    _value_rank_price_buckets = _KIS_VALUE_RANK_PRICE_BUCKETS
    _daily_bars_cache_ttl_sec = _KIS_DAILY_BARS_CACHE_TTL_SEC
    _daily_index_bars_cache_ttl_sec = _KIS_DAILY_INDEX_BARS_CACHE_TTL_SEC
    _quote_cache_ttl_sec = _KIS_QUOTE_CACHE_TTL_SEC

    def __init__(self) -> None:
        from . import kis_client as core

        core._ensure_kis_modules_loaded()
        core._ensure_auth()

        self._core = core
        self._ka = core.ka
        import kis_auth_rest  # type: ignore

        self._session = requests.Session()
        self._rest_throttle = kis_auth_rest._throttle_rest
        self._daily_bars_cache: dict[tuple[str, str, int], tuple[float, pd.DataFrame]] = {}
        self._daily_index_bars_cache: dict[tuple[str, str, int], tuple[float, pd.DataFrame]] = {}
        self._quote_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._secondary_market_ctx = build_secondary_market_context(
            min_gap_by_path=_KIS_HTTP_PATH_MIN_GAP_SEC,
        )
        if self._secondary_market_ctx is not None:
            logger.info("[KIS TradingAPI] 보조 조회 전용 appkey 활성화")
        logger.info("[KIS TradingAPI] 어댑터 초기화 완료")

    def _headers(self, tr_id: str, tr_cont: str = "") -> dict[str, str]:
        h = self._ka._getBaseHeader()
        h["tr_id"] = tr_id
        h["custtype"] = "P"
        if tr_cont:
            h["tr_cont"] = tr_cont
        return h

    def _base_url(self) -> str:
        return self._ka.getTREnv().my_url

    def _account(self) -> tuple[str, str]:
        acct = self._ka.getTREnv().my_acct
        return acct[:8], acct[8:10] if len(acct) >= 10 else "01"

    def _throttle_rest(self) -> None:
        throttle = getattr(self, "_rest_throttle", None)
        if callable(throttle):
            throttle()
            return
        time.sleep(0.05)

    def _throttle_path_min_gap(self, path: str) -> None:
        min_gap_sec = _KIS_HTTP_PATH_MIN_GAP_SEC.get(str(path or "").strip())
        if not min_gap_sec:
            return
        throttle_rest_min_gap(
            scope=f"kis_get:{path}",
            min_gap_sec=min_gap_sec,
        )

    def _market_get(self, path: str, tr_id: str, params: dict, tr_cont: str = "") -> dict:
        secondary_market_ctx = getattr(self, "_secondary_market_ctx", None)
        if secondary_market_ctx is None:
            return self._get(path, tr_id, params, tr_cont)

        try:
            return secondary_market_ctx.get(path, tr_id, params, tr_cont)
        except Exception as exc:
            logger.warning(
                "[KIS TradingAPI] 보조 조회 전용 appkey 실패 -> 기본 appkey fallback path=%s tr_id=%s error=%s",
                path,
                tr_id,
                exc,
            )
            return self._get(path, tr_id, params, tr_cont)

    @staticmethod
    def _copy_cached_value(value: Any) -> Any:
        if isinstance(value, pd.DataFrame):
            return value.copy(deep=True)
        if isinstance(value, dict):
            return dict(value)
        return value

    def _cache_lookup(self, cache_name: str, key: Any, ttl_sec: float) -> Any | None:
        if ttl_sec <= 0:
            return None
        cache = getattr(self, cache_name, None)
        if not isinstance(cache, dict):
            cache = {}
            setattr(self, cache_name, cache)
        entry = cache.get(key)
        if not entry:
            return None
        stored_at, payload = entry
        if (time.monotonic() - float(stored_at)) > ttl_sec:
            cache.pop(key, None)
            return None
        return self._copy_cached_value(payload)

    def _cache_store(self, cache_name: str, key: Any, value: Any, ttl_sec: float) -> Any:
        copied = self._copy_cached_value(value)
        if ttl_sec > 0:
            cache = getattr(self, cache_name, None)
            if not isinstance(cache, dict):
                cache = {}
                setattr(self, cache_name, cache)
            cache[key] = (time.monotonic(), copied)
        return self._copy_cached_value(copied)

    def _is_expired_token_response(self, response: requests.Response, data: dict | None = None) -> bool:
        checker = getattr(getattr(self, "_ka", None), "is_expired_token_response", None)
        if callable(checker):
            return bool(checker(response, data=data))
        return False

    def _force_reauth_current_env(self) -> None:
        refresher = getattr(getattr(self, "_ka", None), "force_reauth_current_env", None)
        if callable(refresher):
            refresher()

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
            "limit": "00",
            "market": "01",
            "mkt": "01",
            "conditional": "02",
            "best": "03",
            "priority": "04",
        }
        return ord_dvsn_map.get(order_kind, "00")

    def _get(self, path: str, tr_id: str, params: dict, tr_cont: str = "") -> dict:
        url = f"{self._base_url()}{path}"
        force_refreshed = False
        for attempt in range(1, _KIS_HTTP_GET_MAX_ATTEMPTS + 1):
            self._core._ensure_auth()
            headers = self._headers(tr_id, tr_cont)
            self._throttle_rest()
            self._throttle_path_min_gap(path)
            try:
                res = self._session.get(
                    url,
                    headers=headers,
                    params=params,
                    timeout=(_KIS_HTTP_CONNECT_TIMEOUT_SEC, _KIS_HTTP_READ_TIMEOUT_SEC),
                )
                data = res.json() if "json" in dir(res) else None
                if self._is_expired_token_response(res, data=data):
                    if force_refreshed:
                        res.raise_for_status()
                    logger.warning(
                        "[KIS API] GET 응답에서 만료 토큰 감지; 강제 재인증 후 재시도 tr_id=%s path=%s",
                        tr_id,
                        path,
                    )
                    self._force_reauth_current_env()
                    force_refreshed = True
                    continue

                res.raise_for_status()
                if not isinstance(data, dict):
                    data = res.json()
                if data.get("rt_cd") != "0":
                    logger.error("[KIS API] GET 실패: tr_id=%s msg=%s", tr_id, data.get("msg1"))
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
        url = f"{self._base_url()}{path}"
        force_refreshed = False

        while True:
            self._core._ensure_auth()
            headers = self._headers(tr_id)
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

            data = res.json() if "json" in dir(res) else None
            if self._is_expired_token_response(res, data=data):
                if force_refreshed:
                    res.raise_for_status()
                logger.warning(
                    "[KIS API] POST 응답에서 만료 토큰 감지; 강제 재인증 후 재시도 tr_id=%s path=%s",
                    tr_id,
                    path,
                )
                self._force_reauth_current_env()
                force_refreshed = True
                continue

            res.raise_for_status()
            if not isinstance(data, dict):
                data = res.json()
            if data.get("rt_cd") != "0":
                logger.error("[KIS API] POST 실패: tr_id=%s msg=%s", tr_id, data.get("msg1"))
            return data


class KISTradingAPI(KISMarketDataMixin, KISAccountTradingMixin, KISTradingBase):
    """KIS OpenAPI 기반 TradingAPI 프로토콜 구현체."""


def create_trading_api() -> KISTradingAPI:
    """
    Trading engine이 호출하는 팩토리 함수.

    사용법:
        TRADING_ENGINE_API_FACTORY=backend.integrations.kis.trading_adapter:create_trading_api
    """
    logger.info("[KIS TradingAPI] 팩토리 함수 호출 → KISTradingAPI 생성")
    return KISTradingAPI()
