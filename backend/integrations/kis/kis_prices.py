from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    
    **배치 조회 최적화**:
    - 국내: 최대 30개를 1번에 조회
    - 해외: 거래소별로 10-20개씩 1번에 조회
    """
    cleaned = [t.strip() for t in tickers if t and t.strip()]
    if not cleaned:
        return {}

    core._ensure_auth()

    # 1. 티커를 국내/해외로 분류
    domestic_tickers: list[str] = []
    overseas_by_exchange: Dict[str, list[tuple[str, str]]] = {}  # EXCD -> [(원본, SYMB), ...]

    for t in cleaned:
        if core._DOMESTIC_TICKER_RE.match(t):
            domestic_tickers.append(t)
        else:
            excd, symb = core._parse_overseas_ticker(t)
            if excd not in overseas_by_exchange:
                overseas_by_exchange[excd] = []
            overseas_by_exchange[excd].append((t, symb))  # 원본 + 심볼

    prices: Dict[str, float] = {}

    # 2. 국내 주식 배치 조회 (최대 30개)
    if domestic_tickers:
        try:
            prices_domestic = _fetch_domestic_prices_batch(domestic_tickers)
            prices.update(prices_domestic)
            missing_domestic = [t for t in domestic_tickers if t not in prices_domestic]
            for t in missing_domestic:
                try:
                    value = _fetch_domestic_price_krw(t)
                    if value is not None:
                        prices[t] = value
                except Exception as e:
                    logger.warning("KIS 국내 시세 조회 실패 ticker=%s error=%s", t, e)
        except Exception as exc:
            logger.warning("국내 배치 조회 실패, 개별 조회로 전환: %s", exc)
            # Fallback: 개별 조회
            for t in domestic_tickers:
                try:
                    value = _fetch_domestic_price_krw(t)
                    if value is not None:
                        prices[t] = value
                except Exception as e:
                    logger.warning("KIS 국내 시세 조회 실패 ticker=%s error=%s", t, e)

    # 3. 해외 주식 조회 (거래소별, 개별 병렬 조회)
    for excd, ticker_list in overseas_by_exchange.items():
        missing_overseas = [original_ticker for original_ticker, _ in ticker_list]
        if missing_overseas:
            with ThreadPoolExecutor(max_workers=min(8, len(missing_overseas))) as executor:
                future_map = {
                    executor.submit(_fetch_overseas_price_krw, ticker): ticker
                    for ticker in missing_overseas
                }
                for future in as_completed(future_map):
                    ticker = future_map[future]
                    try:
                        value = future.result()
                        if value is not None:
                            prices[ticker] = value
                    except Exception as e:
                        logger.warning("KIS 해외 시세 조회 실패 ticker=%s error=%s", ticker, e)

    return prices


def _fetch_domestic_prices_batch(tickers: list[str]) -> Dict[str, float]:
    """
    국내 주식 배치 조회 (최대 30개)
    
    API: 국내주식-205 (관심종목(멀티종목) 시세조회)
    """
    if not tickers:
        return {}
    
    if len(tickers) > 30:
        logger.warning("국내 티커 수(%d)가 최대 30개를 초과합니다. 처음 30개만 조회합니다.", len(tickers))
        tickers = tickers[:30]
    
    df = core._domestic_watchlist_quote(  # type: ignore[misc]
        env_dv="real",
        fid_cond_mrkt_div_code="J",  # 주식/ETF/ETN
        fid_input_iscd=tickers
    )
    
    if df is None or df.empty:
        return {}
    
    prices: Dict[str, float] = {}
    for _, row in df.iterrows():
        code = row.get("inter_shrn_iscd") or row.get("stck_shrn_iscd")  # 종목코드
        price_raw = row.get("inter2_prpr") or row.get("stck_prpr")  # 현재가
        
        if code and price_raw:
            try:
                prices[str(code)] = float(price_raw)
            except (TypeError, ValueError):
                logger.warning("국내 배치 시세 파싱 실패 code=%s raw=%r", code, price_raw)
    
    return prices


def _fetch_overseas_prices_batch(excd: str, ticker_list: list[tuple[str, str]]) -> Dict[str, float]:
    """
    해외 주식 배치 조회 (거래소별, 10-20개 권장)
    
    API: 해외주식-016 (해외 현재가 다건)
    ticker_list: [(원본 티커, 심볼), ...]
    """
    if not ticker_list:
        return {}
    
    if len(ticker_list) > 20:
        logger.info("해외 티커 수(%d, EXCD=%s)가 권장 20개를 초과합니다.", len(ticker_list), excd)
    
    # 심볼만 추출하여 쉼표로 결합
    symbols = [symb for _, symb in ticker_list]
    symb_str = ",".join(symbols)  # 쉼표 구분
    
    df = core._overseas_multi_quote(  # type: ignore[misc]
        auth="",
        excd=excd,
        symb_list=symb_str,
        symb_cnt=str(len(symbols))
    )
    
    if df is None or df.empty:
        return {}
    
    # 심볼 -> 원본 티커 매핑
    symb_to_original = {symb: original for original, symb in ticker_list}
    
    prices: Dict[str, float] = {}
    usdkrw_rate: float | None = None
    usd_exchanges = {"NAS", "NYS", "AMS"}
    for _, row in df.iterrows():
        symb = row.get("symb")         # 종목코드
        price_raw = row.get("last")    # 현재가 (USD)
        
        # 실제 API 응답 구조에 따라 조정 필요
        # 원화 환산가가 별도 필드에 있을 수 있음 (예: t_xprc)
        xprc_raw = row.get("t_xprc")   # 원환산 당일가격 (있다면)
        
        if symb and symb in symb_to_original:
            original_ticker = symb_to_original[symb]
            
            # 우선 원화 환산가 사용, 없으면 USD 환율로 보정
            if xprc_raw:
                try:
                    prices[original_ticker] = float(xprc_raw)
                except (TypeError, ValueError):
                    logger.warning("해외 배치 시세 파싱 실패 ticker=%s raw=%r", original_ticker, xprc_raw)
            elif price_raw and excd in usd_exchanges:
                if usdkrw_rate is None:
                    usdkrw_rate = fetch_usdkrw_rate()
                if usdkrw_rate is None:
                    logger.warning("USD/KRW 환율 조회 실패로 해외 시세 환산 불가 ticker=%s", original_ticker)
                    continue
                try:
                    prices[original_ticker] = float(price_raw) * usdkrw_rate
                except (TypeError, ValueError):
                    logger.warning("해외 배치 시세 파싱 실패 ticker=%s raw=%r", original_ticker, price_raw)
            else:
                logger.warning("해외 배치 응답에 원화 환산가 없음 ticker=%s", original_ticker)
    
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
