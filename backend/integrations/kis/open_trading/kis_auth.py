# -*- coding: utf-8 -*-
# ====|  (REST) 접근 토큰 / (Websocket) 웹소켓 접속키 발급에 필요한 API 호출 모듈  |====
#
# 기존 kis_auth.py 구현을 모듈로 분리하고, 여기서 재-export 한다.

from . import kis_auth_state as _state
from .kis_auth_rest import (  # noqa: F401
    APIResp,
    APIRespError,
    _getBaseHeader,
    _getResultObject,
    _setTRENV,
    _url_fetch,
    auth,
    changeTREnv,
    getEnv,
    getTREnv,
    isPaperTrading,
    reAuth,
    read_token,
    save_token,
    set_order_hash_key,
    smart_sleep,
)
from .kis_auth_ws import (  # noqa: F401
    KISWebSocket,
    _getBaseHeader_ws,
    add_data_map,
    add_open_map,
    aes_cbc_base64_dec,
    auth_ws,
    data_fetch,
    data_map,
    open_map,
    reAuth_ws,
    system_resp,
)


def __getattr__(name: str):
    return getattr(_state, name)

__all__ = [
    "_DEBUG",
    "_TRENV",
    "_autoReAuth",
    "_base_headers",
    "_base_headers_ws",
    "_cfg",
    "_getBaseHeader",
    "_getBaseHeader_ws",
    "_getResultObject",
    "_isPaper",
    "_last_auth_time",
    "_setTRENV",
    "_smartSleep",
    "_url_fetch",
    "APIResp",
    "APIRespError",
    "KISWebSocket",
    "add_data_map",
    "add_open_map",
    "aes_cbc_base64_dec",
    "auth",
    "auth_ws",
    "changeTREnv",
    "clearConsole",
    "config_root",
    "data_fetch",
    "data_map",
    "getEnv",
    "getTREnv",
    "isPaperTrading",
    "key_bytes",
    "open_map",
    "reAuth",
    "reAuth_ws",
    "read_token",
    "save_token",
    "set_order_hash_key",
    "smart_sleep",
    "system_resp",
    "token_lock",
    "token_tmp",
]
