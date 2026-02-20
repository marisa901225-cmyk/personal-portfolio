import logging
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from backend.core.config import settings

logger = logging.getLogger(__name__)

_KIS_ENABLED_ENV = "KIS_ENABLED"


def _env_truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def _env_falsy(value: str) -> bool:
    return value.strip().lower() in {"0", "false", "f", "no", "n", "off"}


def _kis_enabled_mode() -> str:
    """
    KIS 연동 활성화 모드.

    - "auto"(기본): backend 내 KIS 모듈이 있으면 활성화, 없으면 비활성화
    - truthy(1/true/yes/on): 강제 활성화 (없으면 요청 시 RuntimeError)
    - falsy(0/false/no/off): 강제 비활성화
    """
    v = settings.kis_enabled.strip().lower()
    if v in {"auto", ""}:
        return "auto"
    if _env_truthy(v):
        return "enabled"
    if _env_falsy(v):
        return "disabled"
    # 알 수 없는 값은 안전하게 auto 취급
    return "auto"


def _setup_kis_path() -> None:
    """
    backend 내부에 이관한 KIS 모듈 경로를 sys.path에 추가한다.

    - backend/integrations/kis/open_trading
        - kis_auth.py
        - domestic_stock/...
        - overseas_stock/...
    """
    kis_llm_dir = Path(__file__).resolve().parent / "open_trading"
    if not kis_llm_dir.exists():
        raise RuntimeError(f"KIS open_trading directory not found: {kis_llm_dir}")

    if str(kis_llm_dir) not in sys.path:
        sys.path.append(str(kis_llm_dir))


_KIS_MODULES_LOADED = False
_KIS_AVAILABLE = False

# lazy-loaded modules
ka = None  # type: ignore[assignment]
_domestic_inquire_price = None  # type: ignore[assignment]
_domestic_search_stock_info = None  # type: ignore[assignment]
_domestic_watchlist_quote = None  # type: ignore[assignment]
_overseas_price_detail = None  # type: ignore[assignment]
_overseas_search_info = None  # type: ignore[assignment]
_overseas_multi_quote = None  # type: ignore[assignment]


def _ensure_kis_modules_loaded() -> None:
    """
    KIS 모듈들은 환경마다 존재하지 않을 수 있으므로 import를 지연한다.

    - 백엔드 코드를 다른 서버로 옮겨서 테스트할 때, KIS 모듈 폴더가 없어도
      앱 import 자체가 터지지 않게 하기 위함.
    """
    global _KIS_AVAILABLE
    global _KIS_MODULES_LOADED
    global ka
    global _domestic_inquire_price
    global _domestic_search_stock_info
    global _domestic_watchlist_quote
    global _overseas_price_detail
    global _overseas_search_info
    global _overseas_multi_quote

    if _KIS_MODULES_LOADED:
        return

    mode = _kis_enabled_mode()
    kis_llm_dir = Path(__file__).resolve().parent / "open_trading"
    has_open_trading = kis_llm_dir.exists()

    if mode == "disabled" or (mode == "auto" and not has_open_trading):
        _KIS_AVAILABLE = False
        _KIS_MODULES_LOADED = True
        logger.info(
            "KIS integration disabled (mode=%s, open_trading exists=%s). "
            "Set %s=1 to force-enable.",
            mode,
            has_open_trading,
            _KIS_ENABLED_ENV,
        )
        return

    try:
        from .open_trading import kis_auth_state as state
        if not state._is_config_ready():
            _KIS_AVAILABLE = False
            _KIS_MODULES_LOADED = True
            logger.info("KIS configuration is not ready. Skipping module load.")
            return

        _setup_kis_path()
        import kis_auth as _ka  # type: ignore
        from domestic_stock.inquire_price.inquire_price import (  # type: ignore
            inquire_price as __domestic_inquire_price,
        )
        from domestic_stock.search_stock_info.search_stock_info import (  # type: ignore
            search_stock_info as __domestic_search_stock_info,
        )
        from domestic_stock.watchlist_quote.watchlist_quote import (  # type: ignore
            watchlist_quote as __domestic_watchlist_quote,
        )
        from overseas_stock.price_detail.price_detail import (  # type: ignore
            price_detail as __overseas_price_detail,
        )
        from overseas_stock.search_info.search_info import (  # type: ignore
            search_info as __overseas_search_info,
        )
        from overseas_stock.multi_quote.multi_quote import (  # type: ignore
            multi_quote as __overseas_multi_quote,
        )
    except Exception as e:
        import traceback
        import sys
        print(f"FAILED TO IMPORT KIS MODULES: {e}", file=sys.stderr)
        traceback.print_exc()
        import logging
        _KIS_AVAILABLE = False
        _KIS_MODULES_LOADED = True
        logging.getLogger(__name__).warning(
            "KIS integration unavailable (failed to import KIS modules): %s. "
            "If you don't need KIS during tests, set KIS_ENABLED=0.",
            e,
        )
        return

    ka = _ka
    _domestic_inquire_price = __domestic_inquire_price
    _domestic_search_stock_info = __domestic_search_stock_info
    _domestic_watchlist_quote = __domestic_watchlist_quote
    _overseas_price_detail = __overseas_price_detail
    _overseas_search_info = __overseas_search_info
    _overseas_multi_quote = __overseas_multi_quote

    _KIS_AVAILABLE = True
    _KIS_MODULES_LOADED = True


async def get_futures_period_price(
    symbol: str,
    start_date: str,
    end_date: str,
    period_div: str = "D",
    market_div: str = "F",
) -> Optional[Dict]:
    """
    국내 선물/옵션 기간별 시세 조회 (FHKIF03020100)

    Args:
        symbol: 종목코드 (지수선물 6자리, 지수옵션 9자리)
        start_date: 조회 시작일자 (YYYYMMDD)
        end_date: 조회 종료일자 (YYYYMMDD)
        period_div: 기간구분 (D:일, W:주, M:월, Y:년)
        market_div: 시장분류 (F:지수선물, O:지수옵션, JF:주식선물, JO:주식옵션, ...)
    """
    _ensure_auth()
    period = period_div.strip().upper()
    if period not in {"D", "W", "M", "Y"}:
        raise ValueError("period_div must be one of 'D', 'W', 'M', 'Y'")

    tr_id = "FHKIF03020100"
    params = {
        "FID_COND_MRKT_DIV_CODE": market_div,
        "FID_COND_SCR_DIV_CODE": "00000",
        "FID_INPUT_ISCD": symbol,
        "FID_INPUT_DATE_1": start_date,
        "FID_INPUT_DATE_2": end_date,
        "FID_PERIOD_DIV_CODE": period,
        "FID_ORG_ADJ_PRC": "0"
    }
    
    try:
        headers = ka._getBaseHeader()
        headers["tr_id"] = tr_id
        headers["custtype"] = "P"
        
        url = ka.getTREnv().my_url + "/uapi/domestic-futureoption/v1/quotations/inquire-daily-fuopchartprice"
        
        import httpx
        async with httpx.AsyncClient() as client:
            res = await client.get(url, headers=headers, params=params)
            res.raise_for_status()
            return res.json()
    except Exception as e:
        logger.error("선물 기간별 시세 조회 실패: %s", e)
        return None


def _require_kis() -> None:
    _ensure_kis_modules_loaded()
    if not _KIS_AVAILABLE:
        mode = _kis_enabled_mode()
        raise RuntimeError(
            "KIS integration is disabled or unavailable. "
            f"(mode={mode}, env={_KIS_ENABLED_ENV})"
        )


_DOMESTIC_TICKER_RE = re.compile(r"^[0-9A-Z]{6}$")


def _stocks_info_dir() -> Path:
    """
    backend/integrations/kis/stocks_info 디렉터리 경로를 반환한다.
    """
    return Path(__file__).resolve().parent / "stocks_info"


def _ensure_auth() -> None:
    """
    한국투자증권 OpenAPI 토큰 발급/로딩.

    - kis_auth.py 내부에서 토큰 캐싱을 처리하므로,
      매 요청마다 auth()를 호출해도 과도한 재발급은 발생하지 않는다.
    - 실전 계좌 기준으로 동작하도록 기본값(auth(svr=\"prod\"))을 사용한다.
    """
    _require_kis()
    try:
        ka.auth()  # type: ignore[union-attr]  # 실전투자 기준, _cfg.my_prod 기반 계좌 선택
    except Exception as exc:  # pragma: no cover - 네트워크/환경 의존
        logger.exception("KIS 인증 실패: %s", exc)
        raise RuntimeError(
            "KIS authentication failed; KIS config not found in settings (환경변수 KIS_MY_APP...) or file (~/KIS/config/kis_user.yaml)"
        ) from exc


def _parse_overseas_ticker(ticker: str) -> tuple[str, str]:
    """
    해외 티커 문자열을 (EXCD, SYMB) 형태로 파싱한다.

    지원 형식:
      - 'NAS:AAPL' (권장)
      - 'AAPL@NAS'
      - 'AAPL'  -> 기본값으로 미국 나스닥('NAS')로 간주
    """
    t = ticker.strip().upper()
    if ":" in t:
        ex, sym = t.split(":", 1)
        return ex.strip(), sym.strip()
    if "@" in t:
        sym, ex = t.split("@", 1)
        return ex.strip(), sym.strip()
    # 심볼만 들어온 경우: 기본값으로 미국 나스닥으로 처리
    return "NAS", t


def fetch_kis_prices_krw(tickers: Iterable[str]) -> Dict[str, float]:
    from .kis_prices import fetch_kis_prices_krw as _fetch

    return _fetch(tickers)


def fetch_usdkrw_rate() -> Optional[float]:
    from .kis_prices import fetch_usdkrw_rate as _fetch

    return _fetch()


def search_tickers_by_name(query: str, limit: int = 5) -> list[Dict[str, str | None]]:
    from .kis_tickers import search_tickers_by_name as _search

    return _search(query, limit=limit)


def search_tickers(query: str) -> list[Dict[str, str | None]]:
    from .kis_tickers import search_tickers as _search

    return _search(query)


async def get_futures_daily_chart(
    symbol: str, 
    start_date: str, 
    end_date: str, 
    period_div: str = "D"
) -> Optional[Dict]:
    """
    국내 선물/옵션 일자별 차트 조회 (FHKIF03030100)
    
    Args:
        symbol: 종목코드 (예: '101S03' - 코스피200 선물)
        start_date: 시작일자 (YYYYMMDD)
        end_date: 종료일자 (YYYYMMDD)
        period_div: 기간구분 (D:일, W:주, M:월, Y:년)
    """
    _ensure_auth()
    period = period_div.strip().upper()
    if period not in {"D", "W", "M", "Y"}:
        raise ValueError("period_div must be one of 'D', 'W', 'M', 'Y'")
    
    # KIS 내부 TR 환경 설정
    tr_id = "FHKIF03020100"
    params = {
        "FID_COND_MRKT_DIV_CODE": "F", # 지수선물 'F' (LO가 알려준 정확한 코드!)
        "FID_COND_SCR_DIV_CODE": "00000",
        "FID_INPUT_ISCD": symbol,
        "FID_INPUT_DATE_1": start_date,
        "FID_INPUT_DATE_2": end_date,
        "FID_PERIOD_DIV_CODE": period,
        "FID_ORG_ADJ_PRC": "0" # 수정주가 반영 여부
    }
    
    try:
        # kis_auth_rest._url_fetch를 직접 활용하여 호출
        headers = ka._getBaseHeader()
        headers["tr_id"] = tr_id
        headers["custtype"] = "P" # 개인
        
        url = ka.getTREnv().my_url + "/uapi/domestic-futureoption/v1/quotations/inquire-daily-fuopchartprice"
        
        # 비동기 요청을 위해 httpx 활용 (기존 kis_prices 등 패턴 참고)
        import httpx
        async with httpx.AsyncClient() as client:
            res = await client.get(url, headers=headers, params=params)
            res.raise_for_status()
            data = res.json()
            
            if data.get("rt_cd") != "0":
                logger.error("KIS 선물 API 오류: %s", data.get("msg1"))
                return None
                
            return data
    except Exception as e:
        logger.error("선물 차트 데이터 수집 실패: %s", e)
        return None


async def get_futures_option_price(
    symbol: str, 
    market_div: str = "F"
) -> Optional[Dict]:
    """
    선물옵션 현재가 시세 조회 (FHMIF10000000)
    """
    _ensure_auth()
    tr_id = "FHMIF10000000"
    params = {
        "FID_COND_MRKT_DIV_CODE": market_div,
        "FID_INPUT_ISCD": symbol
    }
    
    try:
        headers = ka._getBaseHeader()
        headers["tr_id"] = tr_id
        headers["custtype"] = "P"
        
        url = ka.getTREnv().my_url + "/uapi/domestic-futureoption/v1/quotations/inquire-price"
        
        import httpx
        async with httpx.AsyncClient() as client:
            res = await client.get(url, headers=headers, params=params)
            res.raise_for_status()
            return res.json()
    except Exception as e:
        logger.error("선물옵션 시세 조회 실패: %s", e)
        return None


async def get_options_display_board(
    maturity_month: str, 
    market_cls: str = "", 
    call_put_cls: str = "CO"
) -> Optional[Dict]:
    """
    국내 옵션 전광판 조회 (FHPIF05030100)
    """
    _ensure_auth()
    tr_id = "FHPIF05030100"
    params = {
        "FID_COND_MRKT_DIV_CODE": "O",
        "FID_COND_SCR_DIV_CODE": "20503",
        "FID_MRKT_CLS_CODE": call_put_cls,
        "FID_MTRT_CNT": maturity_month,
        "FID_COND_MRKT_CLS_CODE": market_cls,
        "FID_MRKT_CLS_CODE1": "PO" if call_put_cls == "CO" else "CO"
    }
    
    try:
        headers = ka._getBaseHeader()
        headers["tr_id"] = tr_id
        headers["custtype"] = "P"
        
        url = ka.getTREnv().my_url + "/uapi/domestic-futureoption/v1/quotations/display-board-callput"
        
        import httpx
        async with httpx.AsyncClient() as client:
            res = await client.get(url, headers=headers, params=params)
            res.raise_for_status()
            return res.json()
    except Exception as e:
        logger.error("옵션 전광판 조회 실패: %s", e)
        return None

__all__ = [
    "fetch_kis_prices_krw",
    "fetch_usdkrw_rate",
    "search_tickers_by_name",
    "search_tickers",
    "get_futures_daily_chart",
    "get_futures_option_price",
    "get_options_display_board",
    "get_futures_period_price",
]
