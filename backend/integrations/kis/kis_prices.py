from __future__ import annotations

import logging
from typing import Dict, Iterable, Optional

from . import kis_client as core

logger = logging.getLogger(__name__)


def _fetch_domestic_price_krw(code: str) -> float | None:
    """
    국내 주식 현재가(KRW)를 조회한다.

    code: 6자리 숫자 종목코드 (예: '005930')
    """
    if not core._DOMESTIC_TICKER_RE.match(code):
        raise ValueError(f"invalid domestic code format: {code!r}")

    core._require_kis()

    # 실전/모의 구분은 env_dv로 전달, 시장 분류 코드는 샘플 코드와 동일하게 'J' 사용
    df = core._domestic_inquire_price(  # type: ignore[misc]
        env_dv="real",
        fid_cond_mrkt_div_code="J",
        fid_input_iscd=code,
    )
    if df is None or df.empty:
        return None

    raw = df.iloc[0].get("stck_prpr")
    if raw is None or raw == "":
        return None

    try:
        return float(raw)
    except (TypeError, ValueError):
        logger.warning("국내 시세 값 파싱 실패 code=%s raw=%r", code, raw)
        return None


def _fetch_overseas_price_krw(ticker: str) -> float | None:
    """
    해외 주식 현재가를 원화 기준으로 조회한다.

    - KIS 해외 현재가 상세(price-detail)를 사용해 원환산당일가격(t_xprc)을 사용.
    - ticker 포맷은 _parse_overseas_ticker 참고.
    """
    excd, symb = core._parse_overseas_ticker(ticker)

    core._require_kis()

    def _try_price(ex: str, symbol: str) -> float | None:
        df = core._overseas_price_detail(auth="", excd=ex, symb=symbol)  # type: ignore[misc]
        if df is None or df.empty:
            return None

        raw = df.iloc[0].get("t_xprc")
        if raw is None or raw == "":
            return None

        try:
            return float(raw)
        except (TypeError, ValueError):
            logger.warning(
                "해외 시세 값 파싱 실패 ticker=%s excd=%s symb=%s raw=%r",
                ticker,
                ex,
                symbol,
                raw,
            )
            return None

    # 1차: 사용자가 지정한(또는 기본값 NAS) 거래소로 시도
    value = _try_price(excd, symb)
    if value is not None:
        return value

    # 콜론/골뱅이 없는 심볼만 자동으로 다른 미국 거래소( NAS → NYS → AMS )로 재시도
    t = ticker.strip().upper()
    if ":" not in t and "@" not in t:
        for alt_excd in ("NAS", "NYS", "AMS"):
            if alt_excd == excd:
                continue
            value = _try_price(alt_excd, symb)
            if value is not None:
                logger.info(
                    "해외 시세 자동 거래소 보정 ticker=%s symb=%s excd=%s->%s",
                    ticker,
                    symb,
                    excd,
                    alt_excd,
                )
                return value

    return None


def fetch_kis_prices_krw(tickers: Iterable[str]) -> Dict[str, float]:
    """
    주어진 티커 목록에 대해 KIS 기준 현재가(원화)를 조회한다.

    - 국내: 6자리 숫자 코드 (예: '005930')
    - 해외: 'EXCD:SYMB' (예: 'NAS:AAPL'), 또는 'SYMB@EXCD'
    - 그 외 형식은 해외 심볼로 간주해 'NAS:티커' 로 처리
    """
    cleaned = [t.strip() for t in tickers if t and t.strip()]
    if not cleaned:
        return {}

    core._ensure_auth()

    prices: Dict[str, float] = {}

    for t in cleaned:
        try:
            if core._DOMESTIC_TICKER_RE.match(t):
                value = _fetch_domestic_price_krw(t)
            else:
                value = _fetch_overseas_price_krw(t)
        except Exception as exc:  # pragma: no cover - 외부 API 예외
            logger.warning("KIS 시세 조회 실패 ticker=%s error=%s", t, exc)
            continue

        if value is None:
            continue

        prices[t] = value

    return prices


def fetch_usdkrw_rate() -> Optional[float]:
    """
    해외주식 현재가상세 API를 이용해 USD/KRW 당일 환율을 조회한다.

    - 구현 단순화를 위해 미국 나스닥 상장 종목(AAPL)을 기준으로 환율(t_rate)을 사용한다.
    - KIS 기준 환율이므로, 단순 추세 확인용으로 사용한다.
    """
    core._ensure_auth()

    try:
        df = core._overseas_price_detail(auth="", excd="NAS", symb="AAPL")  # type: ignore[misc]
    except Exception as exc:  # pragma: no cover - 외부 API 예외
        logger.warning("USD/KRW 환율 조회 실패 (price_detail 호출 오류): %s", exc)
        return None

    if df is None or df.empty:
        logger.warning("USD/KRW 환율 조회 실패: empty dataframe")
        return None

    raw = df.iloc[0].get("t_rate")
    if raw is None or raw == "":
        logger.warning("USD/KRW 환율 t_rate 값 없음")
        return None

    try:
        return float(raw)
    except (TypeError, ValueError):
        logger.warning("USD/KRW 환율 값 파싱 실패 raw=%r", raw)
        return None
