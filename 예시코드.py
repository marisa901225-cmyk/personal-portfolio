from dataclasses import dataclass

@dataclass
class RequestHeader:
    content-type: Optional[str] = None    #컨텐츠타입
    authorization: str    #접근토큰
    appkey: str    #앱키
    appsecret: str    #앱시크릿키
    personalseckey: Optional[str] = None    #고객식별키
    tr_id: str    #거래ID
    tr_cont: Optional[str] = None    #연속 거래 여부
    custtype: Optional[str] = None    #고객 타입
    seq_no: Optional[str] = None    #일련번호
    mac_address: Optional[str] = None    #맥주소
    phone_number: Optional[str] = None    #핸드폰번호
    ip_addr: Optional[str] = None    #접속 단말 공인 IP
    gt_uid: Optional[str] = None    #Global UID

@dataclass
class RequestQueryParam:
    FID_COND_MRKT_DIV_CODE: str    #FID 조건 시장 분류 코드
    FID_INPUT_ISCD: str    #FID 입력 종목코드
    FID_INPUT_DATE_1: str    #FID 입력 날짜1
    FID_INPUT_DATE_2: str    #FID 입력 날짜2
    FID_PERIOD_DIV_CODE: str    #FID 기간 분류 코드

from dataclasses import dataclass
from typing import List, Optional

@dataclass
class ResponseHeader:
    content-type: str    #컨텐츠타입
    tr_id: str    #거래ID
    tr_cont: Optional[str] = None    #연속 거래 여부
    gt_uid: Optional[str] = None    #Global UID

@dataclass
class ResponseBody:
    rt_cd: str    #성공 실패 여부
    msg_cd: str    #응답코드
    msg1: str    #응답메세지
    output1: Optional[ResponseBodyoutput1] = None    #응답상세1
    output2: Optional[List[ResponseBodyoutput2] = field(default_factory=list)] = None    #응답상세2

@dataclass
class ResponseBodyoutput1:
    ovrs_nmix_prdy_vrss: Optional[str] = None    # 전일 대비
    prdy_vrss_sign: Optional[str] = None    #전일 대비 부호
    prdy_ctrt: Optional[str] = None    #전일 대비율
    ovrs_nmix_prdy_clpr: Optional[str] = None    #전일 종가
    acml_vol: Optional[str] = None    #누적 거래량
    hts_kor_isnm: Optional[str] = None    #HTS 한글 종목명
    ovrs_nmix_prpr: Optional[str] = None    #현재가
    stck_shrn_iscd: Optional[str] = None    #단축 종목코드
    prdy_vol: Optional[str] = None    #전일 거래량
    ovrs_prod_oprc: Optional[str] = None    #시가
    ovrs_prod_hgpr: Optional[str] = None    #최고가
    ovrs_prod_lwpr: Optional[str] = None    #최저가

@dataclass
class ResponseBodyoutput2:
    stck_bsop_date: Optional[str] = None    #영업 일자
    ovrs_nmix_prpr: Optional[str] = None    #현재가
    ovrs_nmix_oprc: Optional[str] = None    #시가
    ovrs_nmix_hgpr: Optional[str] = None    #최고가
    ovrs_nmix_lwpr: Optional[str] = None    #최저가
    acml_vol: Optional[str] = None    #누적 거래량
    mod_yn: Optional[str] = None    #변경 여부


import requests

url = "https://openapi.koreainvestment.com:9443/uapi/overseas-price/v1/quotations/foreign-index-price"

headers = {
    "Content-Type": "application/json",
    "authorization": "Bearer YOUR_ACCESS_TOKEN",
    "appKey": "YOUR_APPKEY",
    "appSecret": "YOUR_APPSECRET",
    "tr_id": "FHKST03010100",  # TR ID는 실전계좌 기준 (변경 가능)
}

params = {
    "FID_COND_MRKT_DIV_CODE": "X",         # 환율 조회
    "FID_INPUT_ISCD": "FX@KRW",            # 원/달러
    "FID_INPUT_DATE_1": "20250101",        # 시작일
    "FID_INPUT_DATE_2": "20251231",        # 종료일
    "FID_PERIOD_DIV_CODE": "D",            # D:일 / W:주 / M:월 / Y:년
}

response = requests.get(url, headers=headers, params=params)
print(response.json())
