# -*- coding: utf-8 -*-
"""
KIS API - 해외주식 기간별 시세 조회 [v1_해외주식-010]

SPY, QQQ 등 해외 지수의 일봉 OHLCV 데이터를 수집합니다.
"""

import logging
from typing import Optional
import pandas as pd
import kis_auth as ka

logger = logging.getLogger(__name__)

# API 엔드포인트
API_URL = "/uapi/overseas-price/v1/quotations/dailyprice"


def inquire_daily_price(
    auth: str,
    excd: str,
    symb: str,
    gubn: str = "0",  # 0: 일봉, 1: 주봉, 2: 월봉
    modp: str = "1",  # 1: 수정주가반영
    tr_cont: str = "",
    dataframe: Optional[pd.DataFrame] = None,
    depth: int = 0,
    max_depth: int = 10,
    bymd: str = "",
) -> Optional[pd.DataFrame]:
    """
    해외주식 기간별 시세 조회 API

    Args:
        auth (str): 사용자권한정보 (빈 문자열 가능)
        excd (str): 거래소코드 (NAS, NYS, AMS 등)
        symb (str): 종목코드 (예: SPY, QQQ)
        gubn (str): 0=일봉, 1=주봉, 2=월봉
        modp (str): 1=수정주가 반영
        tr_cont (str): 연속 거래 여부
        dataframe (Optional[pd.DataFrame]): 누적 데이터프레임
        depth (int): 현재 재귀 깊이
        max_depth (int): 최대 재귀 깊이

    Returns:
        Optional[pd.DataFrame]: OHLCV 데이터
            - xymd: 일자 (YYYYMMDD)
            - clos: 종가
            - open: 시가
            - high: 고가
            - low: 저가
            - tvol: 거래량
    """
    if not excd:
        logger.error("excd is required (e.g. 'NAS')")
        raise ValueError("excd is required")
    if not symb:
        logger.error("symb is required (e.g. 'SPY')")
        raise ValueError("symb is required")

    if depth >= max_depth:
        logger.warning(
            "Maximum recursion depth (%d) reached. Stopping further requests.",
            max_depth,
        )
        return dataframe if dataframe is not None else pd.DataFrame()

    tr_id = "HHDFS76240000"

    params = {
        "AUTH": auth,
        "EXCD": excd,
        "SYMB": symb,
        "GUBN": gubn,
        "BYMD": bymd,  # 조회 기준일자 (공백: 오늘 기준)
        "MODP": modp,
    }

    res = ka._url_fetch(API_URL, tr_id, tr_cont, params)

    if res.isOK():
        if hasattr(res.getBody(), "output2"):
            output_data = res.getBody().output2
            if not isinstance(output_data, list):
                output_data = [output_data]
            current_data = pd.DataFrame(output_data)
        else:
            current_data = pd.DataFrame()

        if dataframe is not None:
            dataframe = pd.concat([dataframe, current_data], ignore_index=True)
        else:
            dataframe = current_data

        # 페이징 처리: tr_cont가 "M"이거나, 데이터가 100건이면 다음 페이지(이전 데이터)가 더 있을 것으로 판단
        # 해외지수 API는 tr_cont가 "F"로 오더라도 데이터가 더 있을 수 있으므로, 
        # 수집된 데이터의 마지막 날짜(BYMD)를 기준으로 재귀 호출
        tr_cont = res.getHeader().tr_cont
        row_count = len(current_data)
        
        if (tr_cont in ("M", "N")) or (row_count >= 100):
            if depth < max_depth:
                last_date = current_data['xymd'].min()
                # 마지막 날짜의 전날부터 조회하기 위해 숫자로 변환 후 -1 (단순 처리)
                # KIS API 특성상 BYMD를 포함하여 그 이전 데이터를 가져옴
                try:
                    next_bymd = str(int(last_date) - 1)
                    logger.info(f"Fetching more data from {next_bymd} (depth: {depth+1})")
                    ka.smart_sleep()
                    
                    # 새로운 params로 재귀 호출 (BYMD 업데이트)
                    return inquire_daily_price(
                        auth, excd, symb, gubn, modp, "N", dataframe, depth + 1, max_depth, next_bymd
                    )
                except Exception as e:
                    logger.error(f"Failed to calculate next_bymd: {e}")
                    return dataframe
            else:
                logger.warning(f"Max depth {max_depth} reached. Returning accumulated data.")
                return dataframe
        else:
            logger.info("No more data to fetch.")
            return dataframe
    else:
        logger.error(
            "API call failed: %s - %s", res.getErrorCode(), res.getErrorMessage()
        )
        res.printError(API_URL)
        return pd.DataFrame()
