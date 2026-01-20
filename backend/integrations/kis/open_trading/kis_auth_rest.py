from __future__ import annotations

import copy
import json
import time
from collections import namedtuple
from datetime import datetime

import logging
import requests

import kis_auth_state as state
from backend.integrations.kis.token_store import read_kis_token, save_kis_token

logger = logging.getLogger(__name__)


def _throttle_rest() -> None:
    while True:
        with state._rest_rate_lock:
            now = time.perf_counter()
            while state._rest_rate_timestamps and now - state._rest_rate_timestamps[0] >= state._REST_RATE_WINDOW:
                state._rest_rate_timestamps.popleft()
            if len(state._rest_rate_timestamps) < state._REST_RATE_LIMIT:
                state._rest_rate_timestamps.append(now)
                return
            sleep_for = state._REST_RATE_WINDOW - (now - state._rest_rate_timestamps[0])
        if sleep_for > 0:
            time.sleep(sleep_for)
        else:
            time.sleep(0)


def save_token(my_token, my_expired):
    try:
        valid_date = datetime.strptime(my_expired, "%Y-%m-%d %H:%M:%S")
        logger.info("[KIS] save_token 호출 - 만료시간 raw: %s, parsed: %s", my_expired, valid_date)
        save_kis_token(my_token, valid_date)
    except Exception as e:
        logger.error("[KIS] save_token 실패: %s (my_expired=%s)", e, my_expired)
        raise


def read_token():
    try:
        token = read_kis_token()
        if token:
            logger.debug("[KIS] read_token 성공 - 토큰 존재")
        else:
            logger.warning("[KIS] read_token - 토큰 없음 또는 만료됨 (재발급 필요)")
        return token
    except Exception as e:
        logger.error("[KIS] read_token 실패: %s", e)
        return None


def _getBaseHeader():
    if state._autoReAuth:
        reAuth()
    return copy.deepcopy(state._base_headers)


def _setTRENV(cfg):
    nt1 = namedtuple(
        "KISEnv",
        ["my_app", "my_sec", "my_acct", "my_prod", "my_htsid", "my_token", "my_url", "my_url_ws"],
    )
    d = {
        "my_app": cfg["my_app"],
        "my_sec": cfg["my_sec"],
        "my_acct": cfg["my_acct"],
        "my_prod": cfg["my_prod"],
        "my_htsid": cfg["my_htsid"],
        "my_token": cfg["my_token"],
        "my_url": cfg["my_url"],
        "my_url_ws": cfg["my_url_ws"],
    }
    state._TRENV = nt1(**d)


def isPaperTrading():
    return state._isPaper


def changeTREnv(token_key, svr="prod", product=None):
    if product is None:
        product = state.get_cfg().get("my_prod", "01")
    cfg = dict()

    if svr == "prod":
        ak1 = "my_app"
        ak2 = "my_sec"
        state._isPaper = False
        state._smartSleep = 0.05
    elif svr == "vps":
        ak1 = "paper_app"
        ak2 = "paper_sec"
        state._isPaper = True
        state._smartSleep = 0.5
    else:
        ak1 = "my_app"
        ak2 = "my_sec"

    cfg["my_app"] = state.get_cfg()[ak1]
    cfg["my_sec"] = state.get_cfg()[ak2]

    if product == "01":
        cfg["my_acct"] = state.get_cfg()["my_acct_stock"]
    elif product == "03":
        cfg["my_acct"] = state.get_cfg()["my_acct_future"]
    elif product == "08":
        cfg["my_acct"] = state.get_cfg()["my_acct_future"]
    elif product == "01" and svr == "prod":
        cfg["my_acct"] = state.get_cfg()["my_acct_stock"]
    elif product == "01" and svr == "vps":
        cfg["my_acct"] = state.get_cfg()["my_paper_stock"]
    elif product == "03" and svr == "vps":
        cfg["my_acct"] = state.get_cfg()["my_paper_future"]

    cfg["my_htsid"] = state.get_cfg()["my_htsid"]
    cfg["my_url"] = state.get_cfg()[svr]
    cfg["my_url_ws"] = state.get_cfg()["ops" if svr == "prod" else "vops"]
    cfg["my_prod"] = product

    if token_key is not None:
        cfg["my_token"] = token_key
    else:
        cfg["my_token"] = state.get_cfg()["my_token"]

    _setTRENV(cfg)


def _getResultObject(json_data):
    _tb_ = namedtuple("body", json_data.keys())
    return _tb_(**json_data)


def auth(svr="prod", product=None, url=None, force=False):
    if product is None:
        product = state.get_cfg().get("my_prod", "01")
    """
    KIS 접근 토큰 발급/로딩.

    Args:
        svr: 서버 타입 ("prod" 또는 "vps")
        product: 상품 타입
        url: 토큰 발급 URL (기본값: None)
        force: True면 캐시된 토큰 무시하고 강제 재발급 (기본값: False)
    
    Returns:
        발급된 토큰 또는 캐시된 토큰. 실패 시 None.
    
    Features:
        - 분산 락으로 스탬피드 방지
        - 서킷브레이커로 연속 실패 시 발급 차단
        - 지수 백오프로 재시도 간격 조절
    """
    import time
    
    # 서킷브레이커 임포트 (lazy)
    try:
        from backend.integrations.kis.kis_circuit_breaker import (
            get_circuit_state,
            acquire_token_refresh_lock,
            release_token_refresh_lock,
            record_auth_failure,
            record_auth_success,
        )
        circuit_enabled = True
    except ImportError:
        circuit_enabled = False
        logger.warning("[KIS Auth] 서킷브레이커 모듈 로드 실패, 기본 동작으로 진행")

    p = {"grant_type": "client_credentials"}
    if svr == "prod":
        ak1 = "my_app"
        ak2 = "my_sec"
    elif svr == "vps":
        ak1 = "paper_app"
        ak2 = "paper_sec"

    p["appkey"] = state.get_cfg()[ak1]
    p["appsecret"] = state.get_cfg()[ak2]

    with state._token_file_lock():
        # 강제 재발급이 아니면 캐시된 토큰 확인
        if not force:
            my_token = read_token()
            if my_token:
                changeTREnv(my_token, svr, product)
                state._base_headers["authorization"] = f"Bearer {my_token}"
                state._base_headers["appkey"] = state._TRENV.my_app
                state._base_headers["appsecret"] = state._TRENV.my_sec
                state._last_auth_time = datetime.now()
                logger.debug("[KIS Auth] 캐시된 토큰 사용 (만료 전)")
                return my_token

        # ========================================
        # 서킷브레이커 체크
        # ========================================
        if circuit_enabled:
            circuit_state = get_circuit_state()
            if not circuit_state.can_attempt:
                logger.error(
                    "[KIS Auth] 🔴 서킷 오픈 상태! 발급 시도 차단됨 (open_until=%s)",
                    circuit_state.circuit_open_until
                )
                return None
            
            # 백오프 대기
            if circuit_state.backoff_seconds > 0:
                logger.info(
                    "[KIS Auth] 백오프 대기 중... (%.1f초, failure_count=%d)",
                    circuit_state.backoff_seconds, circuit_state.failure_count
                )
                time.sleep(circuit_state.backoff_seconds)
        
        # ========================================
        # 분산 락 획득
        # ========================================
        lock_session = None
        if circuit_enabled:
            lock_acquired, lock_session = acquire_token_refresh_lock()
            if not lock_acquired:
                logger.info("[KIS Auth] 다른 프로세스가 토큰 갱신 중, 대기 후 재시도...")
                time.sleep(2)
                # 다시 토큰 확인 (다른 프로세스가 갱신했을 수 있음)
                my_token = read_token()
                if my_token:
                    changeTREnv(my_token, svr, product)
                    state._base_headers["authorization"] = f"Bearer {my_token}"
                    state._base_headers["appkey"] = state._TRENV.my_app
                    state._base_headers["appsecret"] = state._TRENV.my_sec
                    state._last_auth_time = datetime.now()
                    logger.debug("[KIS Auth] 다른 프로세스가 갱신한 토큰 사용")
                    return my_token
                return None

        try:
            # ========================================
            # 새 토큰 발급
            # ========================================
            import os
            import sys
            import traceback

            pid = os.getpid()
            cmd_line = " ".join(sys.argv)
            stack_summary = "".join(traceback.format_stack()[-5:])

            logger.warning(
                "🚨 [KIS Auth] 새 토큰 발급 시도 감지! 🚨\n"
                "pid=%s, cmd=%s\nforce=%s\n"
                "Call Stack:\n%s",
                pid, cmd_line, force, stack_summary
            )

            if not url:
                url = f"{state.get_cfg()[svr]}/oauth2/tokenP"
            res = requests.post(url, data=json.dumps(p), headers=_getBaseHeader())
            rescode = res.status_code
            
            if rescode == 200:
                my_token = _getResultObject(res.json()).access_token
                my_expired = _getResultObject(res.json()).access_token_token_expired
                logger.warning("[KIS Auth] ✅ 토큰 발급 성공! 만료시간: %s", my_expired)
                save_token(my_token, my_expired)
                
                # 서킷브레이커 성공 기록
                if circuit_enabled:
                    record_auth_success()
            else:
                logger.error("[KIS Auth] ❌ 토큰 발급 실패: %s", res.text)
                
                # 서킷브레이커 실패 기록
                if circuit_enabled:
                    circuit_state = record_auth_failure()
                    logger.warning(
                        "[KIS Auth] 실패 기록 (failure_count=%d, circuit_open=%s)",
                        circuit_state.failure_count, circuit_state.circuit_open
                    )
                
                print("Get Auth Token Fail. (Check your AppKey, AppSecret)")
                return None

            changeTREnv(my_token, svr, product)

            state._base_headers["authorization"] = f"Bearer {my_token}"
            state._base_headers["appkey"] = state._TRENV.my_app
            state._base_headers["appsecret"] = state._TRENV.my_sec
            
        finally:
            # ========================================
            # 분산 락 해제
            # ========================================
            if circuit_enabled and lock_session:
                release_token_refresh_lock(lock_session)
                lock_session.close()

    state._last_auth_time = datetime.now()

    if state._DEBUG:
        print(f"[{state._last_auth_time}] => get AUTH Token completed!")

    return my_token


def reAuth(svr="prod", product=None):
    if product is None:
        product = state.get_cfg().get("my_prod", "01")
    n2 = datetime.now()
    if (n2 - state._last_auth_time).seconds >= 86400:
        auth(svr, product)


def getEnv():
    return state.get_cfg()


def smart_sleep():
    if state._DEBUG:
        print(f"[RateLimit] Sleeping {state._smartSleep}s ")

    time.sleep(state._smartSleep)


def getTREnv():
    if state._TRENV is None:
        # Return a mock-like object with empty strings to prevent attribute errors during initialization
        from collections import namedtuple

        nt = namedtuple(
            "KISEnv",
            [
                "my_url",
                "my_url_ws",
                "my_app",
                "my_sec",
                "my_acct",
                "my_prod",
                "my_htsid",
                "my_token",
            ],
        )
        return nt("", "", "", "", "", "", "", "")
    return state._TRENV


def set_order_hash_key(h, p):
    url = f"{getTREnv().my_url}/uapi/hashkey"
    res = requests.post(url, data=json.dumps(p), headers=h)
    rescode = res.status_code
    if rescode == 200:
        h["hashkey"] = _getResultObject(res.json()).HASH
    else:
        print("Error:", rescode)


class APIResp:
    def __init__(self, resp):
        self._rescode = resp.status_code
        self._resp = resp
        self._header = self._setHeader()
        self._body = self._setBody()
        self._err_code = self._body.msg_cd
        self._err_message = self._body.msg1

    def getResCode(self):
        return self._rescode

    def _setHeader(self):
        fld = dict()
        for x in self._resp.headers.keys():
            if x.islower():
                fld[x] = self._resp.headers.get(x)
        _th_ = namedtuple("header", fld.keys())

        return _th_(**fld)

    def _setBody(self):
        _tb_ = namedtuple("body", self._resp.json().keys())

        return _tb_(**self._resp.json())

    def getHeader(self):
        return self._header

    def getBody(self):
        return self._body

    def getResponse(self):
        return self._resp

    def isOK(self):
        try:
            if self.getBody().rt_cd == "0":
                return True
            return False
        except Exception:
            return False

    def getErrorCode(self):
        return self._err_code

    def getErrorMessage(self):
        return self._err_message

    def printAll(self):
        print("<Header>")
        for x in self.getHeader()._fields:
            print(f"\t-{x}: {getattr(self.getHeader(), x)}")
        print("<Body>")
        for x in self.getBody()._fields:
            print(f"\t-{x}: {getattr(self.getBody(), x)}")

    def printError(self, url):
        print(
            "-------------------------------\nError in response: ",
            self.getResCode(),
            " url=",
            url,
        )
        print(
            "rt_cd : ",
            self.getBody().rt_cd,
            "/ msg_cd : ",
            self.getErrorCode(),
            "/ msg1 : ",
            self.getErrorMessage(),
        )
        print("-------------------------------")


class APIRespError(APIResp):
    def __init__(self, status_code, error_text):
        self.status_code = status_code
        self.error_text = error_text
        self._error_code = str(status_code)
        self._error_message = error_text

    def isOK(self):
        return False

    def getErrorCode(self):
        return self._error_code

    def getErrorMessage(self):
        return self._error_message

    def getBody(self):
        class EmptyBody:
            def __getattr__(self, name):
                return None

        return EmptyBody()

    def getHeader(self):
        class EmptyHeader:
            tr_cont = ""

            def __getattr__(self, name):
                return ""

        return EmptyHeader()

    def printAll(self):
        print("=== ERROR RESPONSE ===")
        print(f"Status Code: {self.status_code}")
        print(f"Error Message: {self.error_text}")
        print("======================")

    def printError(self, url=""):
        print(f"Error Code : {self.status_code} | {self.error_text}")
        if url:
            print(f"URL: {url}")


def _url_fetch(
    api_url, ptr_id, tr_cont, params, appendHeaders=None, postFlag=False, hashFlag=True
):
    url = f"{getTREnv().my_url}{api_url}"

    headers = _getBaseHeader()

    tr_id = ptr_id
    if ptr_id[0] in ("T", "J", "C"):
        if isPaperTrading():
            tr_id = "V" + ptr_id[1:]

    headers["tr_id"] = tr_id
    headers["custtype"] = "P"
    headers["tr_cont"] = tr_cont

    if appendHeaders is not None and len(appendHeaders) > 0:
        for x in appendHeaders.keys():
            headers[x] = appendHeaders.get(x)

    if state._DEBUG:
        print("< Sending Info >")
        print(f"URL: {url}, TR: {tr_id}")
        print(f"<header>\n{headers}")
        print(f"<body>\n{params}")

    _throttle_rest()
    if postFlag:
        res = requests.post(url, headers=headers, data=json.dumps(params))
    else:
        res = requests.get(url, headers=headers, params=params)

    if res.status_code == 200:
        ar = APIResp(res)
        if state._DEBUG:
            ar.printAll()
        return ar
    print("Error Code : " + str(res.status_code) + " | " + res.text)
    return APIRespError(res.status_code, res.text)
