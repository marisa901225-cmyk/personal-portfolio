from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any

import requests

from backend.services.pension_rebalancing import (
    PensionAsset,
    PensionHolding,
    build_pension_rebalance_plan,
    normalize_regime,
)


DEFAULT_RUNTIME_ENV = Path("/app/runtime/myasset.secrets.env")
DEFAULT_TOKEN_CACHE = Path("/app/runtime/kis_pension_token.json")
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


class PensionKISClient:
    def __init__(self, env: dict[str, str]) -> None:
        self.app_key = str(env.get("KIS_MY_APP2") or "").strip()
        self.app_secret = str(env.get("KIS_MY_SEC2") or "").strip()
        self.account = str(env.get("KIS_MY_ACCT_STOCK2") or "").strip()
        self.product = str(env.get("KIS_MY_PROD2") or "").strip()
        self.base_url = str(env.get("KIS_PROD") or DEFAULT_PROD_URL).strip()
        self.session = requests.Session()
        self.token = ""

        missing = [
            name
            for name, value in (
                ("KIS_MY_APP2", self.app_key),
                ("KIS_MY_SEC2", self.app_secret),
                ("KIS_MY_ACCT_STOCK2", self.account),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(f"missing pension KIS env: {','.join(missing)}")

    def _read_cached_token(self) -> str:
        try:
            data = json.loads(DEFAULT_TOKEN_CACHE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return ""

        token = str(data.get("access_token") or "").strip()
        expires_raw = str(data.get("expires_at") or "").strip()
        if not token or not expires_raw:
            return ""
        try:
            expires_at = datetime.strptime(expires_raw, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return ""
        if datetime.now() + timedelta(minutes=30) >= expires_at:
            return ""
        return token

    def _write_cached_token(self, token: str, expires_at: str) -> None:
        if not token or not expires_at:
            return
        try:
            DEFAULT_TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
            DEFAULT_TOKEN_CACHE.write_text(
                json.dumps({"access_token": token, "expires_at": expires_at}),
                encoding="utf-8",
            )
            DEFAULT_TOKEN_CACHE.chmod(0o600)
        except OSError:
            pass

    @property
    def cano(self) -> str:
        return self.account[:8]

    @property
    def acnt_prdt_cd(self) -> str:
        return self.account[8:10] if len(self.account) >= 10 else (self.product or "01")

    def auth(self) -> None:
        cached_token = self._read_cached_token()
        if cached_token:
            self.token = cached_token
            return

        response = self.session.post(
            f"{self.base_url}/oauth2/tokenP",
            headers={"content-type": "application/json"},
            data=json.dumps(
                {
                    "grant_type": "client_credentials",
                    "appkey": self.app_key,
                    "appsecret": self.app_secret,
                }
            ),
            timeout=(3.05, 10.0),
        )
        data = response.json()
        token = str(data.get("access_token") or "").strip()
        if response.status_code >= 400 or not token:
            raise RuntimeError(f"KIS auth failed: {response.status_code} {data.get('msg_cd')} {data.get('msg1')}")
        self.token = token
        self._write_cached_token(token, str(data.get("access_token_token_expired") or "").strip())

    def _headers(self, tr_id: str) -> dict[str, str]:
        if not self.token:
            self.auth()
        return {
            "content-type": "application/json",
            "authorization": f"Bearer {self.token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
            "custtype": "P",
        }

    def balance(self) -> tuple[list[PensionHolding], int]:
        params = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
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
        response = self.session.get(
            f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-balance",
            headers=self._headers("TTTC8434R"),
            params=params,
            timeout=(3.05, 10.0),
        )
        data = response.json()
        if data.get("rt_cd") != "0":
            raise RuntimeError(f"KIS balance failed: {response.status_code} {data.get('msg_cd')} {data.get('msg1')}")

        holdings: list[PensionHolding] = []
        for row in data.get("output1") or []:
            qty = _to_int(row.get("hldg_qty"))
            if qty <= 0:
                continue
            price = _to_int(row.get("prpr"))
            value = _to_int(row.get("evlu_amt")) or qty * price
            holdings.append(
                PensionHolding(
                    code=str(row.get("pdno") or "").strip(),
                    name=str(row.get("prdt_name") or "").strip(),
                    qty=qty,
                    price=price,
                    value=value,
                )
            )

        output2 = data.get("output2") or []
        summary = output2[0] if isinstance(output2, list) and output2 else output2
        summary = summary if isinstance(summary, dict) else {}
        return holdings, _to_int(summary.get("prvs_rcdl_excc_amt"))

    def quote(self, code: str) -> dict[str, Any]:
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": code,
        }
        response = self.session.get(
            f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-price",
            headers=self._headers("FHKST01010100"),
            params=params,
            timeout=(3.05, 10.0),
        )
        data = response.json()
        if data.get("rt_cd") != "0":
            raise RuntimeError(f"KIS quote failed code={code}: {data.get('msg_cd')} {data.get('msg1')}")
        row = data.get("output") or {}
        return {
            "price": _to_int(row.get("stck_prpr")),
            "change_pct": _to_float(row.get("prdy_ctrt")),
        }

    def place_order(self, *, side: str, code: str, qty: int) -> dict[str, Any]:
        body = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "PDNO": code,
            "ORD_DVSN": "01",
            "ORD_QTY": str(qty),
            "ORD_UNPR": "0",
        }
        tr_id = "TTTC0012U" if side == "BUY" else "TTTC0011U"
        response = self.session.post(
            f"{self.base_url}/uapi/domestic-stock/v1/trading/order-cash",
            headers=self._headers(tr_id),
            data=json.dumps(body),
            timeout=(3.05, 10.0),
        )
        data = response.json()
        return {
            "success": data.get("rt_cd") == "0",
            "code": code,
            "side": side,
            "qty": qty,
            "order_id": (data.get("output") or {}).get("ODNO", ""),
            "msg": data.get("msg1", ""),
        }


def _assets_from_env(env: dict[str, str]) -> list[PensionAsset]:
    sp500 = str(env.get("PENSION_REBALANCE_SP500_CODE") or "360200").strip()
    us_growth = str(
        env.get("PENSION_REBALANCE_US_GROWTH_CODE")
        or env.get("PENSION_REBALANCE_NASDAQ_CODE")
        or "426030"
    ).strip()
    bond = str(env.get("PENSION_REBALANCE_US_BOND_CODE") or "").strip()
    assets = [
        PensionAsset(sp500, "sp500", "S&P500"),
        PensionAsset(us_growth, "us_growth", "US Growth ETF"),
    ]
    if bond:
        assets.append(PensionAsset(bond, "bond", "US Bond"))
    return assets


def _resolve_regime(client: PensionKISClient, env: dict[str, str], requested: str, sp500_code: str) -> str:
    if requested != "auto":
        return normalize_regime(requested)
    configured = str(env.get("PENSION_REBALANCE_REGIME") or "").strip()
    if configured:
        return normalize_regime(configured)
    quote = client.quote(sp500_code)
    return "rising" if float(quote.get("change_pct") or 0.0) > 0 else "falling"


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan or execute KIS pension-account rebalancing.")
    parser.add_argument("--regime", default="auto", help="auto, rising, falling, neutral")
    parser.add_argument("--execute", action="store_true", help="place market orders; default is dry-run")
    parser.add_argument("--no-sells", action="store_true", help="only plan buys with available cash")
    parser.add_argument("--min-order-amount", type=int, default=50_000)
    args = parser.parse_args()

    env = {**_load_env_file(DEFAULT_RUNTIME_ENV), **os.environ}
    assets = _assets_from_env(env)
    client = PensionKISClient(env)
    holdings, cash = client.balance()

    prices = {holding.code: holding.price for holding in holdings if holding.price > 0}
    for asset in assets:
        if asset.code not in prices:
            prices[asset.code] = int(client.quote(asset.code).get("price") or 0)

    sp500_code = next(asset.code for asset in assets if asset.bucket == "sp500")
    regime = _resolve_regime(client, env, args.regime, sp500_code)
    plan = build_pension_rebalance_plan(
        holdings=holdings,
        cash=cash,
        assets=assets,
        prices=prices,
        regime=regime,
        min_order_amount=args.min_order_amount,
        allow_sells=not args.no_sells,
    )

    print("mode", "EXECUTE" if args.execute else "DRY_RUN")
    print("regime", plan.regime)
    print("total_value", plan.total_value)
    print("cash", plan.cash)
    print("target_weights", plan.target_weights)
    print("current_values", plan.current_values)
    print("estimated_cash_after_orders", plan.estimated_cash_after_orders)
    print("orders")
    for order in plan.orders:
        print(
            f"- {order.side} {order.code} bucket={order.bucket} qty={order.qty} "
            f"price={order.price} amount={order.amount} reason={order.reason}"
        )

    if not args.execute:
        return 0

    for order in plan.orders:
        result = client.place_order(side=order.side, code=order.code, qty=order.qty)
        print("order_result", result)
        if not result.get("success"):
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
