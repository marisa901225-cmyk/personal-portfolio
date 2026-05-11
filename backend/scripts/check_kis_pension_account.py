from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests


DEFAULT_RUNTIME_ENV = Path("/app/runtime/myasset.secrets.env")
DEFAULT_PROD_URL = "https://openapi.koreainvestment.com:9443"


def _load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def _to_int(value: Any) -> int:
    try:
        return int(float(str(value or "0").replace(",", "").strip() or "0"))
    except (TypeError, ValueError):
        return 0


def _to_float(value: Any) -> float:
    try:
        return float(str(value or "0").replace(",", "").strip() or "0")
    except (TypeError, ValueError):
        return 0.0


def main() -> int:
    runtime_env = _load_env_file(DEFAULT_RUNTIME_ENV)
    env = {**runtime_env, **os.environ}

    app_key = str(env.get("KIS_MY_APP2") or "").strip()
    app_secret = str(env.get("KIS_MY_SEC2") or "").strip()
    account = str(env.get("KIS_MY_ACCT_STOCK2") or "").strip()
    product = str(env.get("KIS_MY_PROD2") or "").strip()
    base_url = str(env.get("KIS_PROD") or DEFAULT_PROD_URL).strip()

    missing = [
        name
        for name, value in (
            ("KIS_MY_APP2", app_key),
            ("KIS_MY_SEC2", app_secret),
            ("KIS_MY_ACCT_STOCK2", account),
        )
        if not value
    ]
    if missing:
        print("missing", ",".join(missing))
        return 2

    cano = account[:8]
    acnt_prdt_cd = account[8:10] if len(account) >= 10 else (product or "01")

    session = requests.Session()
    auth_response = session.post(
        f"{base_url}/oauth2/tokenP",
        headers={"content-type": "application/json"},
        data=json.dumps(
            {
                "grant_type": "client_credentials",
                "appkey": app_key,
                "appsecret": app_secret,
            }
        ),
        timeout=(3.05, 10.0),
    )
    try:
        auth_data = auth_response.json()
    except ValueError:
        auth_data = {}

    token = str(auth_data.get("access_token") or "").strip()
    if auth_response.status_code >= 400 or not token:
        print(
            "auth_failed",
            auth_response.status_code,
            auth_data.get("msg_cd"),
            auth_data.get("msg1"),
        )
        return 1

    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": "TTTC8434R",
        "custtype": "P",
    }
    params = {
        "CANO": cano,
        "ACNT_PRDT_CD": acnt_prdt_cd,
        "AFHR_FLPR_YN": "N",
        "OFL_YN": "",
        "INQR_DVSN": "01",
        "UNPR_DVSN": "01",
        "FUND_STTL_ICLD_YN": "N",
        "FNCG_AMT_AUTO_RDPT_YN": "N",
        "PRCS_DVSN": "00",
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": "",
    }
    balance_response = session.get(
        f"{base_url}/uapi/domestic-stock/v1/trading/inquire-balance",
        headers=headers,
        params=params,
        timeout=(3.05, 10.0),
    )
    data = balance_response.json()
    print(
        "balance_status",
        balance_response.status_code,
        data.get("rt_cd"),
        data.get("msg_cd"),
        data.get("msg1"),
    )
    if data.get("rt_cd") != "0":
        return 1

    positions = []
    for row in data.get("output1") or []:
        qty = _to_int(row.get("hldg_qty"))
        if qty <= 0:
            continue
        positions.append(
            {
                "code": row.get("pdno", ""),
                "name": row.get("prdt_name", ""),
                "qty": qty,
                "eval_amt": _to_int(row.get("evlu_amt")),
                "pnl": _to_int(row.get("evlu_pfls_amt")),
                "pnl_rate": _to_float(row.get("evlu_pfls_rt")),
            }
        )

    output2 = data.get("output2") or []
    summary = output2[0] if isinstance(output2, list) and output2 else output2
    summary = summary if isinstance(summary, dict) else {}

    print("positions_count", len(positions))
    print("cash_d2", summary.get("prvs_rcdl_excc_amt"))
    print("total_eval", summary.get("tot_evlu_amt") or summary.get("scts_evlu_amt"))
    print("positions", positions[:10])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
