"""
국내주식-205 (관심종목(멀티종목) 시세조회) API 래퍼

한 번의 API 호출로 최대 30개 국내 종목의 현재가를 조회합니다.
"""

import sys

import pandas as pd

import kis_auth as ka

# 로깅 설정 (전역 설정 대신 모듈 로거 사용)
logger = logging.getLogger(__name__)

##############################################################################################
# [국내주식] 시세분석 > 관심종목(멀티종목) 시세조회[v1_국내주식-205]
##############################################################################################

# 상수 정의
API_URL = "/uapi/domestic-stock/v1/quotations/intstock-multprice"

def watchlist_quote(
    env_dv: str,  # [필수] 실전모의구분 (ex. real:실전, demo:모의)
    fid_cond_mrkt_div_code: str | list[str],  # [필수] 조건 시장 분류 코드 (ex. J:주식, ETF, ETN, W:ELW)
    fid_input_iscd: str | list[str]  # [필수] 입력 종목코드 (ex. "005930,000660,035720" - 최대 30종목)
) -> pd.DataFrame:
    """
    관심종목(멀티종목) 시세조회 API - 한 번에 최대 30개 종목 조회 가능
    
    Args:
        env_dv (str): [필수] 실전모의구분 (ex. real:실전, demo:모의)
        fid_cond_mrkt_div_code (str): [필수] 조건 시장 분류 코드 (ex. J:주식/ETF/ETN, W:ELW)
        fid_input_iscd (str): [필수] 입력 종목코드 (쉼표 구분, 최대 30종목)
                              예: "005930,000660,035720"
    
    Returns:
        pd.DataFrame: 관심종목 시세 데이터
                     각 행이 하나의 종목 데이터
        
    Example:
        >>> df = watchlist_quote("real", "J", "005930,000660,035720")
        >>> print(df[['stck_shrn_iscd', 'stck_prpr']])  # 종목코드, 현재가
    """
    
    # 필수 파라미터 검증
    if not env_dv:
        raise ValueError("env_dv is required (e.g. 'real' or 'demo')")
    
    if not fid_cond_mrkt_div_code:
        raise ValueError("fid_cond_mrkt_div_code is required (e.g. 'J' for stocks)")
    
    if not fid_input_iscd:
        raise ValueError("fid_input_iscd is required (e.g. '005930,000660')")
    
    if env_dv != "real":
        raise ValueError("env_dv can only be 'real' (interest stock API is not supported in demo)")

    if isinstance(fid_input_iscd, str):
        tickers = [t.strip() for t in fid_input_iscd.split(",") if t.strip()]
    else:
        tickers = [t.strip() for t in fid_input_iscd if t and t.strip()]

    if isinstance(fid_cond_mrkt_div_code, str):
        market_codes = [fid_cond_mrkt_div_code] * len(tickers)
    else:
        market_codes = [m.strip() for m in fid_cond_mrkt_div_code if m and m.strip()]

    if len(market_codes) != len(tickers):
        raise ValueError("fid_cond_mrkt_div_code must match ticker count")

    # 종목 수 체크
    ticker_count = len(tickers)
    if ticker_count > 30:
        logger.warning(f"Ticker count ({ticker_count}) exceeds maximum 30. API may fail.")
        tickers = tickers[:30]
        market_codes = market_codes[:30]
    
    tr_id = "FHKST11300006"

    params = {}
    for idx, (mkt, code) in enumerate(zip(market_codes, tickers), start=1):
        params[f"FID_COND_MRKT_DIV_CODE_{idx}"] = mkt
        params[f"FID_INPUT_ISCD_{idx}"] = code
    
    res = ka._url_fetch(API_URL, tr_id, "", params)
    
    if res.isOK():
        body = res.getBody()
        output_data = getattr(body, "output", None) or getattr(body, "output2", None)
        if output_data:
            if not isinstance(output_data, list):
                output_data = [output_data]
            current_data = pd.DataFrame(output_data)
            logger.info(f"Fetched {len(current_data)} tickers successfully")
            return current_data
        logger.warning("No output field in response")
        return pd.DataFrame()
    else:
        res.printError(url=API_URL)
        return pd.DataFrame()
