"""
해외주식-016 (해외 현재가 다건) API 래퍼

한 번의 API 호출로 10-20개 해외 종목의 현재가를 조회합니다.
같은 거래소(EXCD)의 종목만 한 번에 조회 가능합니다.
"""

import sys

import pandas as pd

import kis_auth as ka

# 로깅 설정 (전역 설정 대신 모듈 로거 사용)
logger = logging.getLogger(__name__)

##############################################################################################
# [해외주식] 기본시세 > 해외주식 현재가 다건[v1_해외주식-016]
##############################################################################################

# 상수 정의
API_URL = "/uapi/overseas-price/v1/quotations/inquire-multi-price"

def multi_quote(
    auth: str,  # 사용자권한정보 (보통 빈 문자열 "")
    excd: str,  # 거래소코드 (ex. NAS, NYS, AMS, HKS, TSE 등)
    symb_list: str,  # 종목코드 리스트 (쉼표 구분, 최대 약 20개)
    symb_cnt: str  # 종목 개수 (예: "3")
) -> pd.DataFrame:
    """
    해외주식 현재가 다건 조회 API - 한 번에 10-20개 종목 조회 권장
    
    주의: 같은 거래소(EXCD)의 종목만 한 번에 조회 가능
    
    Args:
        auth (str): 사용자권한정보 (보통 빈 문자열 "")
        excd (str): 거래소코드
                   - NAS: 나스닥
                   - NYS: 뉴욕증권거래소
                   - AMS: 아메리칸증권거래소
                   - HKS: 홍콩거래소
                   - TSE: 도쿄증권거래소
                   - 기타: SHS, SZS, SHI, SZI, HSX, HNX 등
        symb_list (str): 종목코드 리스트 (쉼표로 구분)
                        예: "TSLA,AAPL,GOOGL,MSFT"
                        최대 약 20개 권장
        symb_cnt (str): 종목 개수 (예: "3")
    
    Returns:
        pd.DataFrame: 해외 종목별 현재가 데이터
                     각 행이 하나의 종목 데이터
        
    Example:
        >>> df = multi_quote("", "NAS", "TSLA AAPL GOOGL")
        >>> print(df[['symb', 'last']])  # 종목코드, 현재가
    """
    
    # 필수 파라미터 검증
    if not excd:
        logger.error("excd is required. (e.g. 'NAS', 'NYS')")
        raise ValueError("excd is required. (e.g. 'NAS', 'NYS')")
    
    if not symb_list or not symb_list.strip():
        logger.error("symb_list is required. (e.g. 'TSLA AAPL GOOGL')")
        raise ValueError("symb_list is required. (e.g. 'TSLA AAPL GOOGL')")
    
    # 종목 수 체크
    symbols = [s for s in symb_list.split() if s.strip()]
    ticker_count = len(symbols)
    
    if ticker_count > 20:
        logger.warning(
            f"Ticker count ({ticker_count}) exceeds recommended 20. "
            "Response time may be slow."
        )
    
    tr_id = "HHQTC00000500"
    
    params = {
        "AUTH": auth,
        "EXCD": excd,
        "SYMB_LIST": symb_list,  # 쉼표 구분
        "SYMB_CNT": symb_cnt
    }
    
    res = ka._url_fetch(API_URL, tr_id, "", params)
    
    if res.isOK():
        # output이 종목별 시세 데이터 리스트
        if hasattr(res.getBody(), 'output'):
            output_data = res.getBody().output
            if not isinstance(output_data, list):
                output_data = [output_data]
            current_data = pd.DataFrame(output_data)
            logger.info(
                f"Fetched {len(current_data)} tickers from {excd} successfully"
            )
            return current_data
        else:
            logger.warning("No output field in response")
            return pd.DataFrame()
    else:
        logger.error(
            f"API call failed for {excd}: {res.getErrorCode()} - {res.getErrorMessage()}"
        )
        res.printError(API_URL)
        return pd.DataFrame()
