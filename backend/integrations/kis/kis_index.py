"""
KIS 국내업종 지수 조회 모듈

코스피, 코스닥 등의 지수를 조회합니다.
"""
import logging
import re
from typing import Optional, Dict, Any
from backend.integrations.kis import kis_client as core

logger = logging.getLogger(__name__)

_DATE_RE = re.compile(r"^\d{8}$")
_PERIOD_CODES = {"D", "W", "M"}


def _normalize_date(date_str: str) -> str:
    cleaned = date_str.strip().replace("-", "")
    if not _DATE_RE.match(cleaned):
        raise ValueError("date must be in YYYYMMDD format (e.g. 20240223)")
    return cleaned


def _safe_output_dict(body: Any, *names: str) -> Dict[str, Any]:
    for name in names:
        value = getattr(body, name, None)
        if isinstance(value, dict):
            return value
    return {}


def fetch_index_price(index_code: str) -> Optional[float]:
    """
    국내업종 현재지수를 조회합니다.
    
    Args:
        index_code: 지수 코드
            - "0001": 코스피
            - "1001": 코스닥
            - "2001": 코스피200
    
    Returns:
        지수 현재가 (float) 또는 None
    """
    core._require_kis()
    core._ensure_auth()
    
    try:
        endpoint = "/uapi/domestic-stock/v1/quotations/inquire-index-price"
        params = {
            "FID_COND_MRKT_DIV_CODE": "U",  # 업종
            "FID_INPUT_ISCD": index_code
        }

        res = core.ka._url_fetch(endpoint, "FHPUP02100000", "", params)  # type: ignore[union-attr]
        if not res.isOK():
            logger.warning(
                "KIS index API returned error: %s - %s",
                res.getErrorCode(),
                res.getErrorMessage(),
            )
            return None

        output = _safe_output_dict(res.getBody(), "output", "output1")
        index_price_str = output.get("bstp_nmix_prpr", "")

        if not index_price_str:
            logger.warning(f"Index price not found in response for {index_code}")
            return None
        
        return float(index_price_str)
        
    except Exception as e:
        logger.error(f"Failed to fetch index {index_code}: {e}")
        return None


def fetch_index_daily_prices(
    index_code: str,
    date: str,
    period: str = "D",
) -> Optional[Dict[str, Any]]:
    """
    국내업종 일자별 지수를 조회합니다.

    Args:
        index_code: 지수 코드 (예: 0001=코스피, 1001=코스닥, 2001=코스피200)
        date: 기준일 (YYYYMMDD)
        period: "D"(일별), "W"(주별), "M"(월별)

    Returns:
        {"output1": dict, "output2": list} 형태의 dict 또는 None
    """
    core._require_kis()
    core._ensure_auth()

    if period not in _PERIOD_CODES:
        raise ValueError("period must be one of 'D', 'W', 'M'")

    try:
        endpoint = "/uapi/domestic-stock/v1/quotations/inquire-index-daily-price"
        params = {
            "FID_PERIOD_DIV_CODE": period,
            "FID_COND_MRKT_DIV_CODE": "U",
            "FID_INPUT_ISCD": index_code,
            "FID_INPUT_DATE_1": _normalize_date(date),
        }

        res = core.ka._url_fetch(endpoint, "FHPUP02120000", "", params)  # type: ignore[union-attr]
        if not res.isOK():
            logger.warning(
                "KIS index daily API returned error: %s - %s",
                res.getErrorCode(),
                res.getErrorMessage(),
            )
            return None

        body = res.getBody()
        output1 = _safe_output_dict(body, "output1", "output")
        output2 = getattr(body, "output2", None)
        if output2 is None:
            output2 = []
        elif not isinstance(output2, list):
            output2 = [output2]

        return {"output1": output1, "output2": output2}
    except Exception as e:
        logger.error("Failed to fetch index daily prices index=%s error=%s", index_code, e)
        return None


def fetch_kospi_index() -> Optional[float]:
    """코스피 지수 조회"""
    return fetch_index_price("0001")


def fetch_kosdaq_index() -> Optional[float]:
    """코스닥 지수 조회"""
    return fetch_index_price("1001")


__all__ = [
    "fetch_index_price",
    "fetch_index_daily_prices",
    "fetch_kospi_index",
    "fetch_kosdaq_index",
]
