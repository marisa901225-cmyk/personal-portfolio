from __future__ import annotations

import asyncio
import copy
import json
import logging
from base64 import b64decode
from collections import namedtuple
from collections.abc import Callable
from datetime import datetime
from io import StringIO

import pandas as pd
import requests
import websockets
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

from . import kis_auth_state as state
from .kis_auth_rest import _getBaseHeader, _getResultObject, changeTREnv, getTREnv, smart_sleep

open_map: dict = {}
data_map: dict = {}


def _getBaseHeader_ws():
    if state._autoReAuth:
        reAuth_ws()
    return copy.deepcopy(state._base_headers_ws)


def auth_ws(svr="prod", product=state._cfg["my_prod"]):
    p = {"grant_type": "client_credentials"}
    if svr == "prod":
        ak1 = "my_app"
        ak2 = "my_sec"
    elif svr == "vps":
        ak1 = "paper_app"
        ak2 = "paper_sec"
    else:
        ak1 = "my_app"
        ak2 = "my_sec"

    p["appkey"] = state._cfg[ak1]
    p["secretkey"] = state._cfg[ak2]

    url = f"{state._cfg[svr]}/oauth2/Approval"
    res = requests.post(url, data=json.dumps(p), headers=_getBaseHeader())
    rescode = res.status_code
    if rescode == 200:
        approval_key = _getResultObject(res.json()).approval_key
    else:
        print("Get Approval token fail!\nYou have to restart your app!!!")
        return

    changeTREnv(None, svr, product)

    state._base_headers_ws["approval_key"] = approval_key

    state._last_auth_time = datetime.now()

    if state._DEBUG:
        print(f"[{state._last_auth_time}] => get AUTH Key completed!")


def reAuth_ws(svr="prod", product=state._cfg["my_prod"]):
    n2 = datetime.now()
    if (n2 - state._last_auth_time).seconds >= 86400:
        auth_ws(svr, product)


def data_fetch(tr_id, tr_type, params, appendHeaders=None) -> dict:
    headers = _getBaseHeader_ws()

    headers["tr_type"] = tr_type
    headers["custtype"] = "P"

    if appendHeaders is not None and len(appendHeaders) > 0:
        for x in appendHeaders.keys():
            headers[x] = appendHeaders.get(x)

    if state._DEBUG:
        print("< Sending Info >")
        print(f"TR: {tr_id}")
        print(f"<header>\n{headers}")

    inp = {"tr_id": tr_id}
    inp.update(params)

    return {"header": headers, "body": {"input": inp}}


def system_resp(data):
    isPingPong = False
    isUnSub = False
    isOk = False
    tr_msg = None
    tr_key = None
    encrypt, iv, ekey = None, None, None

    rdic = json.loads(data)

    tr_id = rdic["header"]["tr_id"]
    if tr_id != "PINGPONG":
        tr_key = rdic["header"]["tr_key"]
        encrypt = rdic["header"]["encrypt"]
    if rdic.get("body", None) is not None:
        isOk = True if rdic["body"]["rt_cd"] == "0" else False
        tr_msg = rdic["body"]["msg1"]
        if "output" in rdic["body"]:
            iv = rdic["body"]["output"]["iv"]
            ekey = rdic["body"]["output"]["key"]
        isUnSub = True if tr_msg[:5] == "UNSUB" else False
    else:
        isPingPong = True if tr_id == "PINGPONG" else False

    nt2 = namedtuple(
        "SysMsg",
        [
            "isOk",
            "tr_id",
            "tr_key",
            "isUnSub",
            "isPingPong",
            "tr_msg",
            "iv",
            "ekey",
            "encrypt",
        ],
    )
    d = {
        "isOk": isOk,
        "tr_id": tr_id,
        "tr_key": tr_key,
        "tr_msg": tr_msg,
        "isUnSub": isUnSub,
        "isPingPong": isPingPong,
        "iv": iv,
        "ekey": ekey,
        "encrypt": encrypt,
    }

    return nt2(**d)


def aes_cbc_base64_dec(key, iv, cipher_text):
    if key is None or iv is None:
        raise AttributeError("key and iv cannot be None")

    cipher = AES.new(key.encode("utf-8"), AES.MODE_CBC, iv.encode("utf-8"))
    return bytes.decode(unpad(cipher.decrypt(b64decode(cipher_text)), AES.block_size))


def add_open_map(
    name: str,
    request: Callable[[str, str, ...], (dict, list[str])],
    data: str | list[str],
    kwargs: dict = None,
):
    if open_map.get(name, None) is None:
        open_map[name] = {
            "func": request,
            "items": [],
            "kwargs": kwargs,
        }

    if type(data) is list:
        open_map[name]["items"] += data
    elif type(data) is str:
        open_map[name]["items"].append(data)


def add_data_map(
    tr_id: str,
    columns: list = None,
    encrypt: str = None,
    key: str = None,
    iv: str = None,
):
    if data_map.get(tr_id, None) is None:
        data_map[tr_id] = {"columns": [], "encrypt": False, "key": None, "iv": None}

    if columns is not None:
        data_map[tr_id]["columns"] = columns

    if encrypt is not None:
        data_map[tr_id]["encrypt"] = encrypt

    if key is not None:
        data_map[tr_id]["key"] = key

    if iv is not None:
        data_map[tr_id]["iv"] = iv


class KISWebSocket:
    api_url: str = ""
    on_result: Callable[
        [websockets.ClientConnection, str, pd.DataFrame, dict], None
    ] = None
    result_all_data: bool = False

    retry_count: int = 0
    amx_retries: int = 0

    def __init__(self, api_url: str, max_retries: int = 3):
        self.api_url = api_url
        self.max_retries = max_retries

    async def __subscriber(self, ws: websockets.ClientConnection):
        async for raw in ws:
            logging.info("received message >> %s", raw)
            show_result = False

            df = pd.DataFrame()

            if raw[0] in ["0", "1"]:
                d1 = raw.split("|")
                if len(d1) < 4:
                    raise ValueError("data not found...")

                tr_id = d1[1]

                dm = data_map[tr_id]
                d = d1[3]
                if dm.get("encrypt", None) == "Y":
                    d = aes_cbc_base64_dec(dm["key"], dm["iv"], d)

                df = pd.read_csv(
                    StringIO(d), header=None, sep="^", names=dm["columns"], dtype=object
                )

                show_result = True

            else:
                rsp = system_resp(raw)

                tr_id = rsp.tr_id
                add_data_map(
                    tr_id=rsp.tr_id, encrypt=rsp.encrypt, key=rsp.ekey, iv=rsp.iv
                )

                if rsp.isPingPong:
                    print(f"### RECV [PINGPONG] [{raw}]")
                    await ws.pong(raw)
                    print(f"### SEND [PINGPONG] [{raw}]")

                if self.result_all_data:
                    show_result = True

            if show_result is True and self.on_result is not None:
                self.on_result(ws, tr_id, df, data_map[tr_id])

    async def __runner(self):
        if len(open_map.keys()) > 40:
            raise ValueError("Subscription's max is 40")

        url = f"{getTREnv().my_url_ws}{self.api_url}"

        while self.retry_count < self.max_retries:
            try:
                async with websockets.connect(url) as ws:
                    for name, obj in open_map.items():
                        await self.send_multiple(
                            ws, obj["func"], "1", obj["items"], obj["kwargs"]
                        )

                    await asyncio.gather(
                        self.__subscriber(ws),
                    )
            except Exception as e:
                print("Connection exception >> ", e)
                self.retry_count += 1
                await asyncio.sleep(1)

    @classmethod
    async def send(
        cls,
        ws: websockets.ClientConnection,
        request: Callable[[str, str, ...], (dict, list[str])],
        tr_type: str,
        data: str,
        kwargs: dict = None,
    ):
        k = {} if kwargs is None else kwargs
        msg, columns = request(tr_type, data, **k)

        add_data_map(tr_id=msg["body"]["input"]["tr_id"], columns=columns)

        logging.info("send message >> %s", json.dumps(msg))

        await ws.send(json.dumps(msg))
        smart_sleep()

    async def send_multiple(
        self,
        ws: websockets.ClientConnection,
        request: Callable[[str, str, ...], (dict, list[str])],
        tr_type: str,
        data: list | str,
        kwargs: dict = None,
    ):
        if type(data) is str:
            await self.send(ws, request, tr_type, data, kwargs)
        elif type(data) is list:
            for d in data:
                await self.send(ws, request, tr_type, d, kwargs)
        else:
            raise ValueError("data must be str or list")

    @classmethod
    def subscribe(
        cls,
        request: Callable[[str, str, ...], (dict, list[str])],
        data: list | str,
        kwargs: dict = None,
    ):
        add_open_map(request.__name__, request, data, kwargs)

    def unsubscribe(
        self,
        ws: websockets.ClientConnection,
        request: Callable[[str, str, ...], (dict, list[str])],
        data: list | str,
    ):
        self.send_multiple(ws, request, "2", data)

    def start(
        self,
        on_result: Callable[
            [websockets.ClientConnection, str, pd.DataFrame, dict], None
        ],
        result_all_data: bool = False,
    ):
        self.on_result = on_result
        self.result_all_data = result_all_data
        try:
            asyncio.run(self.__runner())
        except KeyboardInterrupt:
            print("Closing by KeyboardInterrupt")
