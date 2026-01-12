from __future__ import annotations

import copy
import json
import time
from collections import namedtuple
from datetime import datetime

import requests

import kis_auth_state as state
from backend.integrations.kis.token_store import read_kis_token, save_kis_token


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
    valid_date = datetime.strptime(my_expired, "%Y-%m-%d %H:%M:%S")
    save_kis_token(my_token, valid_date)


def read_token():
    try:
        return read_kis_token()
    except Exception:
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


def changeTREnv(token_key, svr="prod", product=state._cfg["my_prod"]):
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

    cfg["my_app"] = state._cfg[ak1]
    cfg["my_sec"] = state._cfg[ak2]

    if product == "01":
        cfg["my_acct"] = state._cfg["my_acct_stock"]
    elif product == "03":
        cfg["my_acct"] = state._cfg["my_acct_future"]
    elif product == "08":
        cfg["my_acct"] = state._cfg["my_acct_future"]
    elif product == "01" and svr == "prod":
        cfg["my_acct"] = state._cfg["my_acct_stock"]
    elif product == "01" and svr == "vps":
        cfg["my_acct"] = state._cfg["my_paper_stock"]
    elif product == "03" and svr == "vps":
        cfg["my_acct"] = state._cfg["my_paper_future"]

    cfg["my_htsid"] = state._cfg["my_htsid"]
    cfg["my_url"] = state._cfg[svr]
    cfg["my_url_ws"] = state._cfg["ops" if svr == "prod" else "vops"]
    cfg["my_prod"] = product

    if token_key is not None:
        cfg["my_token"] = token_key
    else:
        cfg["my_token"] = state._cfg["my_token"]

    _setTRENV(cfg)


def _getResultObject(json_data):
    _tb_ = namedtuple("body", json_data.keys())
    return _tb_(**json_data)


def auth(svr="prod", product=state._cfg["my_prod"], url=None):
    p = {"grant_type": "client_credentials"}
    if svr == "prod":
        ak1 = "my_app"
        ak2 = "my_sec"
    elif svr == "vps":
        ak1 = "paper_app"
        ak2 = "paper_sec"

    p["appkey"] = state._cfg[ak1]
    p["appsecret"] = state._cfg[ak2]

    with state._token_file_lock():
        my_token = read_token()
        if my_token:
            changeTREnv(my_token, svr, product)
            state._base_headers["authorization"] = f"Bearer {my_token}"
            state._base_headers["appkey"] = state._TRENV.my_app
            state._base_headers["appsecret"] = state._TRENV.my_sec
            state._last_auth_time = datetime.now()
            return my_token

        if not url:
            url = f"{state._cfg[svr]}/oauth2/tokenP"
        res = requests.post(url, data=json.dumps(p), headers=_getBaseHeader())
        rescode = res.status_code
        if rescode == 200:
            my_token = _getResultObject(res.json()).access_token
            my_expired = _getResultObject(res.json()).access_token_token_expired
            save_token(my_token, my_expired)
        else:
            print("Get Auth Token Fail. (Check your AppKey, AppSecret)")
            return

        changeTREnv(my_token, svr, product)

        state._base_headers["authorization"] = f"Bearer {my_token}"
        state._base_headers["appkey"] = state._TRENV.my_app
        state._base_headers["appsecret"] = state._TRENV.my_sec

    state._last_auth_time = datetime.now()

    if state._DEBUG:
        print(f"[{state._last_auth_time}] => get AUTH Token completed!")

    return my_token


def reAuth(svr="prod", product=state._cfg["my_prod"]):
    n2 = datetime.now()
    if (n2 - state._last_auth_time).seconds >= 86400:
        auth(svr, product)


def getEnv():
    return state._cfg


def smart_sleep():
    if state._DEBUG:
        print(f"[RateLimit] Sleeping {state._smartSleep}s ")

    time.sleep(state._smartSleep)


def getTREnv():
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
