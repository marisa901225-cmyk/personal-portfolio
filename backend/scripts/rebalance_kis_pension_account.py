from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from datetime import date, datetime, timedelta
from typing import Any

import requests

from backend.services.pension_rebalancing import (
    PensionAsset,
    PensionHolding,
    PensionOrderPlan,
    QuarterlyMarketSignal,
    build_pension_rebalance_plan,
    normalize_regime,
    pct_return,
    quarter_start,
    resolve_quarterly_market_signal,
)
from backend.services.trading_engine.execution_support import (
    krx_tick_size,
    next_buy_retry_price,
    normalize_buy_limit_price,
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


def _env_float(name: str, default: float) -> float:
    raw = str(os.getenv(name, "") or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _aggressive_limit_price(*, side: str, price: int) -> int:
    if side == "BUY":
        return next_buy_retry_price(int(price))
    normalized = normalize_buy_limit_price(int(price))
    tick_size = krx_tick_size(float(normalized))
    return max(tick_size, normalized - tick_size)


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

    def buy_order_capacity(self, code: str, *, price: int = 0, order_type: str = "00") -> dict[str, int]:
        params = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "PDNO": code,
            "ORD_UNPR": str(max(0, int(price))),
            "ORD_DVSN": order_type,
            "CMA_EVLU_AMT_ICLD_YN": "N",
            "OVRS_ICLD_YN": "N",
        }
        response = self.session.get(
            f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-psbl-order",
            headers=self._headers("TTTC8908R"),
            params=params,
            timeout=(3.05, 10.0),
        )
        data = response.json()
        if data.get("rt_cd") != "0":
            raise RuntimeError(f"KIS buy capacity failed code={code}: {data.get('msg_cd')} {data.get('msg1')}")
        output = data.get("output") or {}
        row = output[0] if isinstance(output, list) and output else output
        row = row if isinstance(row, dict) else {}
        return {
            "ord_psbl_cash": _to_int(row.get("ord_psbl_cash")),
            "nrcvb_buy_amt": _to_int(row.get("nrcvb_buy_amt")),
            "nrcvb_buy_qty": _to_int(row.get("nrcvb_buy_qty")),
            "max_buy_amt": _to_int(row.get("max_buy_amt")),
            "max_buy_qty": _to_int(row.get("max_buy_qty")),
        }

    def daily_prices(self, code: str, *, start_date: str, end_date: str) -> list[tuple[str, int]]:
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": code,
            "FID_INPUT_DATE_1": start_date,
            "FID_INPUT_DATE_2": end_date,
            "FID_PERIOD_DIV_CODE": "D",
            "FID_ORG_ADJ_PRC": "0",
        }
        response = self.session.get(
            f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
            headers=self._headers("FHKST03010100"),
            params=params,
            timeout=(3.05, 10.0),
        )
        data = response.json()
        if data.get("rt_cd") != "0":
            raise RuntimeError(f"KIS daily prices failed code={code}: {data.get('msg_cd')} {data.get('msg1')}")
        rows = data.get("output2") or []
        prices: list[tuple[str, int]] = []
        for row in rows:
            trade_date = str(row.get("stck_bsop_date") or "").strip()
            close = _to_int(row.get("stck_clpr"))
            if trade_date and close > 0:
                prices.append((trade_date, close))
        return sorted(prices)

    def place_order(self, *, side: str, code: str, qty: int, price: int) -> dict[str, Any]:
        body = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "PDNO": code,
            "ORD_DVSN": "00",
            "ORD_QTY": str(qty),
            "ORD_UNPR": str(max(0, int(price))),
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
            "price": price,
            "order_id": (data.get("output") or {}).get("ODNO", ""),
            "msg": data.get("msg1", ""),
        }


def _assets_from_env(env: dict[str, str], *, selected_momentum_code: str | None = None) -> list[PensionAsset]:
    sp500 = str(env.get("PENSION_REBALANCE_SP500_CODE") or "360200").strip()
    kospi = str(env.get("PENSION_REBALANCE_KOSPI_CODE") or "237350").strip()
    nasdaq = str(
        env.get("PENSION_REBALANCE_NASDAQ_CODE")
        or env.get("PENSION_REBALANCE_MOMENTUM_CODE")
        or env.get("PENSION_REBALANCE_US_GROWTH_CODE")
        or "426030"
    ).strip()
    bond = str(env.get("PENSION_REBALANCE_US_BOND_CODE") or "").strip()
    momentum_codes = [
        str(selected_momentum_code or "").strip(),
        kospi,
        nasdaq,
    ]
    assets = [
        PensionAsset(sp500, "sp500", "S&P500"),
    ]
    seen = {sp500}
    for code in momentum_codes:
        if code and code not in seen:
            assets.append(PensionAsset(code, "momentum", "Momentum ETF"))
            seen.add(code)
    if bond:
        assets.append(PensionAsset(bond, "bond", "US Bond"))
    return assets


def _quarterly_return(client: PensionKISClient, code: str, *, today: date) -> float:
    start = quarter_start(today).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")
    prices = client.daily_prices(code, start_date=start, end_date=end)
    if len(prices) < 2:
        quote = client.quote(code)
        return float(quote.get("change_pct") or 0.0)
    return pct_return(float(prices[0][1]), float(prices[-1][1]))


def _resolve_quarterly_signal(
    client: PensionKISClient,
    env: dict[str, str],
    requested: str,
) -> QuarterlyMarketSignal:
    sp500_code = str(env.get("PENSION_REBALANCE_SP500_CODE") or "360200").strip()
    kospi_code = str(env.get("PENSION_REBALANCE_KOSPI_CODE") or "237350").strip()
    nasdaq_code = str(
        env.get("PENSION_REBALANCE_NASDAQ_CODE")
        or env.get("PENSION_REBALANCE_MOMENTUM_CODE")
        or env.get("PENSION_REBALANCE_US_GROWTH_CODE")
        or "426030"
    ).strip()
    today = date.today()
    reference_return = _quarterly_return(client, sp500_code, today=today)
    kospi_return = _quarterly_return(client, kospi_code, today=today)
    nasdaq_return = _quarterly_return(client, nasdaq_code, today=today)
    signal = resolve_quarterly_market_signal(
        reference_return_pct=reference_return,
        kospi_return_pct=kospi_return,
        nasdaq_return_pct=nasdaq_return,
        kospi_code=kospi_code,
        nasdaq_code=nasdaq_code,
    )
    if requested != "auto":
        return QuarterlyMarketSignal(
            regime=normalize_regime(requested),
            reference_return_pct=signal.reference_return_pct,
            kospi_return_pct=signal.kospi_return_pct,
            nasdaq_return_pct=signal.nasdaq_return_pct,
            selected_momentum_code=signal.selected_momentum_code,
        )
    configured = str(env.get("PENSION_REBALANCE_REGIME") or "").strip()
    if configured:
        return QuarterlyMarketSignal(
            regime=normalize_regime(configured),
            reference_return_pct=signal.reference_return_pct,
            kospi_return_pct=signal.kospi_return_pct,
            nasdaq_return_pct=signal.nasdaq_return_pct,
            selected_momentum_code=signal.selected_momentum_code,
        )
    return signal


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan or execute KIS pension-account rebalancing.")
    parser.add_argument("--regime", default="auto", help="auto, rising, falling, neutral")
    parser.add_argument("--execute", action="store_true", help="place market orders; default is dry-run")
    parser.add_argument("--no-sells", action="store_true", help="only plan buys with available cash")
    parser.add_argument("--min-order-amount", type=int, default=50_000)
    args = parser.parse_args()

    env = {**_load_env_file(DEFAULT_RUNTIME_ENV), **os.environ}
    client = PensionKISClient(env)
    signal = _resolve_quarterly_signal(client, env, args.regime)
    assets = _assets_from_env(env, selected_momentum_code=signal.selected_momentum_code)
    holdings, cash = client.balance()

    prices = {holding.code: holding.price for holding in holdings if holding.price > 0}
    for asset in assets:
        if asset.code not in prices:
            prices[asset.code] = int(client.quote(asset.code).get("price") or 0)

    orderable_cash = cash
    if args.execute:
        capacity_values = []
        for asset in assets:
            if asset.bucket in {"sp500", "momentum"}:
                limit_price = _aggressive_limit_price(side="BUY", price=prices.get(asset.code, 0))
                capacity = client.buy_order_capacity(asset.code, price=limit_price, order_type="00")
                capacity_values.append(
                    max(
                        capacity.get("ord_psbl_cash", 0),
                        capacity.get("nrcvb_buy_amt", 0),
                        capacity.get("max_buy_amt", 0),
                    )
                )
        positive_capacity_values = [value for value in capacity_values if value > 0]
        if positive_capacity_values:
            orderable_cash = min(cash, max(positive_capacity_values))
        cash_buffer_pct = max(0.0, min(0.5, _env_float("PENSION_REBALANCE_ORDER_CASH_BUFFER_PCT", 0.10)))
        orderable_cash = int(orderable_cash * (1.0 - cash_buffer_pct))

    plan = build_pension_rebalance_plan(
        holdings=holdings,
        cash=orderable_cash,
        assets=assets,
        prices=prices,
        regime=signal.regime,
        min_order_amount=args.min_order_amount,
        allow_sells=not args.no_sells,
    )

    if args.execute:
        remaining_orderable_cash = orderable_cash
        adjusted_orders: list[PensionOrderPlan] = []
        for order in plan.orders:
            if order.side != "BUY":
                adjusted_orders.append(order)
                continue
            limit_price = _aggressive_limit_price(side="BUY", price=order.price)
            capacity = client.buy_order_capacity(order.code, price=limit_price, order_type="00")
            capacity_qty = max(capacity.get("nrcvb_buy_qty", 0), capacity.get("max_buy_qty", 0))
            cash_qty = remaining_orderable_cash // max(1, limit_price)
            qty_candidates = [order.qty, int(cash_qty)]
            if capacity_qty > 0:
                qty_candidates.append(capacity_qty)
            adjusted_qty = min(qty_candidates)
            if adjusted_qty <= 0:
                continue
            adjusted_amount = adjusted_qty * limit_price
            adjusted_orders.append(
                PensionOrderPlan(
                    side=order.side,
                    code=order.code,
                    bucket=order.bucket,
                    qty=adjusted_qty,
                    price=limit_price,
                    amount=adjusted_amount,
                    reason=order.reason,
                )
            )
            remaining_orderable_cash = max(0, remaining_orderable_cash - adjusted_amount)
        plan.orders[:] = adjusted_orders

    print("mode", "EXECUTE" if args.execute else "DRY_RUN")
    print("regime", plan.regime)
    print("quarterly_reference_return_pct", round(signal.reference_return_pct, 2))
    print("quarterly_kospi_return_pct", round(signal.kospi_return_pct, 2))
    print("quarterly_nasdaq_return_pct", round(signal.nasdaq_return_pct, 2))
    print("selected_momentum_code", signal.selected_momentum_code)
    print("total_value", plan.total_value)
    print("cash", plan.cash)
    if args.execute:
        print("balance_cash_d2", cash)
        print("orderable_cash_used", orderable_cash)
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
        order_price = _aggressive_limit_price(side=order.side, price=order.price) if order.side == "SELL" else order.price
        result = client.place_order(side=order.side, code=order.code, qty=order.qty, price=order_price)
        print("order_result", result)
        if not result.get("success"):
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
