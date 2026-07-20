from __future__ import annotations

import argparse
from contextlib import nullcontext
from dataclasses import asdict, replace
import json
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from backend.integrations.kis.trading_adapter import KISDirectCredentials, create_trading_api
from backend.services.pension_exit_review import pension_exit_chart_codes, review_pension_sell_orders
from backend.services.pension_momentum import (
    PensionIndexCandidate,
    PensionMomentumCandidate,
    analyze_pension_momentum_candidate,
    pension_index_family,
    requires_momentum_trend_exit,
    review_pension_momentum_candidates,
    select_liquid_pension_index_candidates,
)
from backend.services.pension_order_safety import (
    DEFAULT_MAX_SINGLE_ASSET_WEIGHT_PCT,
    PensionExecutionJournal,
    aggregate_and_validate_sell_orders,
    apply_buy_capacity,
    assert_no_open_orders,
    normalized_price_history,
    orderable_cash_for_buys,
    pension_execution_lock,
    pension_signal_key,
    resolve_pension_product,
    validate_buyable_pension_assets,
)
from backend.services.pension_rebalancing import (
    DEFAULT_MOMENTUM_OUTPERFORMANCE_THRESHOLD_PCT,
    calculate_equity_trend_metrics,
    PensionAsset,
    PensionHolding,
    PensionOrderPlan,
    PensionRebalancePlan,
    QuarterlyMarketSignal,
    build_pension_rebalance_plan,
    cap_pension_sell_orders,
    max_target_weight_drift_pct,
    normalize_regime,
    pct_return,
    quarter_start,
    resolve_quarterly_market_signal,
)
from backend.services.trading_engine.config import TradeEngineConfig
from backend.services.trading_engine.execution_support import (
    krx_tick_size,
    next_buy_retry_price,
    normalize_buy_limit_price,
)
from backend.services.trading_engine.stock_master import load_stock_master_map
from backend.services.trading_engine.utils import compute_avg_value


DEFAULT_RUNTIME_ENV = Path("/app/runtime/myasset.secrets.env")
DEFAULT_PROD_URL = "https://openapi.koreainvestment.com:9443"
DEFAULT_US_SHORT_BOND_CODE = "0048J0"
DEFAULT_EXIT_REVIEW_OUTPUT_DIR = Path("/app/backend/storage/pension_rebalance/monthly_review")
DEFAULT_EXECUTION_STATE_PATH = Path("/app/backend/storage/pension_rebalance/execution_state.json")
DEFAULT_EXECUTION_LOCK_PATH = Path("/app/backend/storage/pension_rebalance/execution.lock")


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


def _env_float(name: str, default: float, env: dict[str, str] | None = None) -> float:
    source = os.environ if env is None else env
    raw = str(source.get(name, "") or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int, env: dict[str, str] | None = None) -> int:
    source = os.environ if env is None else env
    raw = str(source.get(name, "") or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
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
        app_key = str(env.get("KIS_MY_APP2") or "").strip()
        app_secret = str(env.get("KIS_MY_SEC2") or "").strip()
        account = str(env.get("KIS_MY_ACCT_STOCK2") or "").strip()
        configured_product = str(env.get("KIS_MY_PROD2") or "").strip()
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
            raise RuntimeError(f"missing pension KIS env: {','.join(missing)}")
        product = resolve_pension_product(account=account, product=configured_product)
        self.api = create_trading_api(
            KISDirectCredentials(
                app_key=app_key,
                app_secret=app_secret,
                account=account,
                product=product,
                base_url=base_url,
                token_slot=2,
            )
        )

    def balance(self) -> tuple[list[PensionHolding], int]:
        holdings: list[PensionHolding] = []
        for row in self.api.positions():
            qty = _to_int(row.get("qty"))
            if qty <= 0:
                continue
            price = _to_int(row.get("current_price"))
            value = qty * price
            holdings.append(
                PensionHolding(
                    code=str(row.get("code") or "").strip(),
                    name=str(row.get("name") or "").strip(),
                    qty=qty,
                    price=price,
                    value=value,
                    avg_price=_to_float(row.get("avg_price")),
                    pnl=_to_int(row.get("pnl")),
                    pnl_rate=_to_float(row.get("pnl_rate")),
                )
            )
        return holdings, self.api.cash_available()

    def quote(self, code: str) -> dict[str, Any]:
        return self.api.quote(code)

    def buy_order_capacity(self, code: str, *, price: int = 0, order_type: str = "00") -> dict[str, int]:
        return self.api.buy_order_capacity(code=code, price=price, order_type=order_type)

    def sell_order_capacity(self, code: str) -> dict[str, int]:
        return self.api.sell_order_capacity(code)

    def daily_prices(self, code: str, *, start_date: str, end_date: str) -> list[tuple[str, int]]:
        return normalized_price_history(
            self.api.chart_prices(
                code,
                start_date=start_date,
                end_date=end_date,
                period_div_code="D",
            )
        )

    def monthly_prices(self, code: str, *, start_date: str, end_date: str) -> list[tuple[str, int]]:
        return normalized_price_history(
            self.api.chart_prices(
                code,
                start_date=start_date,
                end_date=end_date,
                period_div_code="M",
            )
        )

    def weekly_prices(self, code: str, *, start_date: str, end_date: str) -> list[tuple[str, int]]:
        return normalized_price_history(
            self.api.chart_prices(
                code,
                start_date=start_date,
                end_date=end_date,
                period_div_code="W",
            )
        )

    def daily_history(self, code: str, *, end_date: str, lookback: int) -> tuple[list[tuple[str, int]], float]:
        bars = self.api.daily_bars(code=code, end=end_date, lookback=lookback)
        avg_value_20d, _ = compute_avg_value(bars, window=20)
        prices = [
            (str(row.get("date") or ""), _to_int(row.get("close")))
            for row in bars.to_dict(orient="records")
            if _to_int(row.get("close")) > 0
        ]
        return normalized_price_history(prices), float(avg_value_20d or 0.0)

    def place_order(self, *, side: str, code: str, qty: int, price: int) -> dict[str, Any]:
        result = self.api.place_order(side=side, code=code, qty=qty, order_type="limit", price=price)
        return {
            "success": bool(result.get("success")),
            "code": code,
            "side": side,
            "qty": qty,
            "price": price,
            "order_id": result.get("order_id", ""),
            "msg": result.get("msg", ""),
        }

    def open_orders(self) -> list[dict[str, Any]]:
        return self.api.open_orders()

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        return self.api.cancel_order(order_id)

    def daily_order_fills(self, *, code: str = "", order_id: str = "", side: str = "00") -> list[dict[str, Any]]:
        today = datetime.now().strftime("%Y%m%d")
        return self.api.daily_order_fills(start_date=today, end_date=today, code=code, order_id=order_id, side=side)


def _assets_from_env(
    env: dict[str, str],
    *,
    selected_momentum_code: str | None = None,
    momentum_trend_exit_codes: tuple[str, ...] = (),
    holdings: list[PensionHolding] | None = None,
) -> list[PensionAsset]:
    sp500 = str(env.get("PENSION_REBALANCE_SP500_CODE") or "360200").strip()
    kospi = str(env.get("PENSION_REBALANCE_KOSPI_CODE") or "237350").strip()
    nasdaq = str(
        env.get("PENSION_REBALANCE_NASDAQ_CODE")
        or env.get("PENSION_REBALANCE_MOMENTUM_CODE")
        or env.get("PENSION_REBALANCE_US_GROWTH_CODE")
        or "426030"
    ).strip()
    bond = str(env.get("PENSION_REBALANCE_US_BOND_CODE") or DEFAULT_US_SHORT_BOND_CODE).strip()
    parking = str(
        env.get("PENSION_REBALANCE_PARKING_CODE")
        or env.get("TRADING_RISK_OFF_PARKING_CODE")
        or TradeEngineConfig().risk_off_parking_code
        or ""
    ).strip()
    selected_momentum_code = None if selected_momentum_code is None else str(selected_momentum_code).strip()
    if selected_momentum_code is None:
        momentum_codes = [(kospi, True), (nasdaq, True)]
    elif selected_momentum_code:
        momentum_codes = [(selected_momentum_code, True), (kospi, False), (nasdaq, False)]
    else:
        momentum_codes = [(kospi, False), (nasdaq, False)]
    trend_exit_codes = {str(code).strip() for code in momentum_trend_exit_codes if str(code).strip()}
    assets = [
        PensionAsset(sp500, "sp500", "S&P500"),
    ]
    seen = {sp500}
    for code, buyable in momentum_codes:
        if code and code not in seen:
            assets.append(
                PensionAsset(
                    code,
                    "momentum",
                    "Momentum ETF",
                    buyable=buyable,
                    trend_exit=code in trend_exit_codes,
                )
            )
            seen.add(code)
    for holding in holdings or []:
        code = str(holding.code or "").strip()
        name = str(holding.name or "").strip()
        if not code or code in seen or not pension_index_family(name):
            continue
        assets.append(
            PensionAsset(
                code,
                "momentum",
                name or "Momentum ETF",
                buyable=False,
                trend_exit=code in trend_exit_codes,
            )
        )
        seen.add(code)
    for code in sorted(trend_exit_codes - seen):
        assets.append(PensionAsset(code, "momentum", "Momentum ETF", buyable=False, trend_exit=True))
        seen.add(code)
    if bond and bond in seen:
        raise ValueError(f"duplicate pension asset code across buckets: {bond}")
    if bond:
        assets.append(PensionAsset(bond, "bond", "US Short Bond"))
        seen.add(bond)
    if parking and parking in seen and parking != bond:
        raise ValueError(f"duplicate pension asset code across buckets: {parking}")
    if parking and parking not in seen:
        assets.append(PensionAsset(parking, "parking", "Parking ETF"))
    return assets


def _quarterly_return(client: PensionKISClient, code: str, *, today: date) -> float:
    start = quarter_start(today).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")
    prices = normalized_price_history(
        client.daily_prices(code, start_date=start, end_date=end)
    )
    if len(prices) >= 2:
        return pct_return(float(prices[0][1]), float(prices[-1][1]))
    if len(prices) == 1:
        quote = client.quote(code)
        current_price = int(quote.get("price") or prices[-1][1])
        return pct_return(float(prices[0][1]), float(current_price))
    return 0.0


def _trend_start(today: date) -> str:
    return (today - timedelta(days=540)).strftime("%Y%m%d")


def _analyze_pension_momentum_universe(
    client: PensionKISClient,
    env: dict[str, str],
    *,
    kospi_code: str,
    nasdaq_code: str,
    end_date: str,
) -> list[PensionMomentumCandidate]:
    config = TradeEngineConfig()
    universe_by_code: dict[str, tuple[str, str]] = {}
    try:
        master_map = load_stock_master_map(
            kospi_master_path=config.industry_kospi_master_path,
            kosdaq_master_path=config.industry_kosdaq_master_path,
        )
    except Exception as exc:
        print("pension_momentum_master_error", {"error": type(exc).__name__})
        master_map = {}

    for info in master_map.values():
        code = str(info.code or "").strip()
        if not info.is_etf or not code or code.upper().startswith("Q"):
            continue
        family = pension_index_family(info.name)
        if not family:
            continue
        if family == "korea_kospi" and code != kospi_code:
            continue
        universe_by_code[code] = (str(info.name or "").strip(), family)

    seed_specs = (
        (kospi_code, "237350", "KODEX 코스피100", "korea_kospi"),
        (nasdaq_code, "426030", "TIME 미국나스닥100액티브", "us_nasdaq100"),
    )
    for code, default_code, default_name, expected_family in seed_specs:
        if code in universe_by_code:
            continue
        info = master_map.get(code)
        if info is not None:
            actual_name = str(info.name or "").strip()
            actual_family = pension_index_family(actual_name)
            if info.is_etf and actual_family == expected_family:
                universe_by_code[code] = (actual_name, actual_family)
            else:
                print(
                    "pension_momentum_seed_rejected",
                    {"code": code, "name": actual_name, "family": actual_family},
                )
        elif code == default_code:
            universe_by_code[code] = (default_name, expected_family)
        else:
            print("pension_momentum_seed_rejected", {"code": code, "reason": "UNKNOWN_CUSTOM_CODE"})

    histories: dict[str, list[tuple[str, int]]] = {}
    liquid_candidates: list[PensionIndexCandidate] = []
    for code, (name, family) in sorted(universe_by_code.items()):
        try:
            daily_prices, avg_value_20d = client.daily_history(code, end_date=end_date, lookback=180)
        except Exception as exc:
            print(
                "pension_momentum_history_error",
                {"code": code, "family": family, "error": type(exc).__name__},
            )
            continue
        histories[code] = daily_prices
        liquid_candidates.append(PensionIndexCandidate(code, name, family, avg_value_20d))

    raw_min_avg_value = str(env.get("PENSION_REBALANCE_MOMENTUM_MIN_AVG_VALUE_20D") or "").strip()
    try:
        configured_min_avg_value = float(raw_min_avg_value) if raw_min_avg_value else 1_000_000_000.0
    except ValueError:
        configured_min_avg_value = 1_000_000_000.0
    min_avg_value_20d = max(0.0, configured_min_avg_value)
    selected = select_liquid_pension_index_candidates(
        liquid_candidates,
        min_avg_value_20d=min_avg_value_20d,
        preferred_codes={kospi_code, nasdaq_code},
    )
    family_leaders = select_liquid_pension_index_candidates(
        liquid_candidates,
        min_avg_value_20d=0.0,
        preferred_codes={kospi_code, nasdaq_code},
    )
    print(
        "pension_momentum_universe",
        {
            "scanned": len(liquid_candidates),
            "min_avg_value_20d": int(min_avg_value_20d),
            "selected": [
                {
                    "code": candidate.code,
                    "name": candidate.name,
                    "family": candidate.family,
                    "avg_value_20d": int(candidate.avg_value_20d),
                }
                for candidate in selected
            ],
            "below_liquidity": [
                {
                    "code": candidate.code,
                    "name": candidate.name,
                    "family": candidate.family,
                    "avg_value_20d": int(candidate.avg_value_20d),
                }
                for candidate in family_leaders
                if candidate.avg_value_20d < min_avg_value_20d
            ],
        },
    )
    analyzed: list[PensionMomentumCandidate] = []
    weekly_start = (datetime.strptime(end_date, "%Y%m%d").date() - timedelta(days=540)).strftime("%Y%m%d")
    for candidate in selected:
        try:
            weekly_prices = client.weekly_prices(candidate.code, start_date=weekly_start, end_date=end_date)
        except Exception as exc:
            print(
                "pension_momentum_weekly_error",
                {"code": candidate.code, "family": candidate.family, "error": type(exc).__name__},
            )
            continue
        analyzed.append(
            analyze_pension_momentum_candidate(
                code=candidate.code,
                name=candidate.name,
                daily_prices=histories[candidate.code],
                weekly_prices=weekly_prices,
                family=candidate.family,
                avg_value_20d=candidate.avg_value_20d,
            )
        )
    return analyzed


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
    trend_start = _trend_start(today)
    trend_end = today.strftime("%Y%m%d")
    trend_metrics = calculate_equity_trend_metrics(
        daily_prices=client.daily_prices(sp500_code, start_date=trend_start, end_date=trend_end),
        monthly_prices=client.monthly_prices(sp500_code, start_date=trend_start, end_date=trend_end),
    )
    signal = resolve_quarterly_market_signal(
        reference_return_pct=reference_return,
        kospi_return_pct=kospi_return,
        nasdaq_return_pct=nasdaq_return,
        kospi_code=kospi_code,
        nasdaq_code=nasdaq_code,
        momentum_outperformance_threshold_pct=max(
            0.0,
            _env_float(
                "PENSION_REBALANCE_MOMENTUM_OUTPERFORMANCE_PCT",
                DEFAULT_MOMENTUM_OUTPERFORMANCE_THRESHOLD_PCT,
                env,
            ),
        ),
        trend_metrics=trend_metrics,
    )
    configured = str(env.get("PENSION_REBALANCE_REGIME") or "").strip()
    if requested != "auto":
        signal = replace(signal, regime=normalize_regime(requested))
    elif configured:
        signal = replace(signal, regime=normalize_regime(configured))

    momentum_candidates = _analyze_pension_momentum_universe(
        client,
        env,
        kospi_code=kospi_code,
        nasdaq_code=nasdaq_code,
        end_date=trend_end,
    )
    print(
        "pension_momentum_analysis",
        json.dumps(
            [
                {
                    "code": candidate.code,
                    "name": candidate.name,
                    "family": candidate.family,
                    "avg_value_20d": int(candidate.avg_value_20d),
                    "score": candidate.score,
                    "eligible": candidate.eligible,
                    "weekly_ma10": round(candidate.weekly_ma10, 2),
                    "weekly_ma20": round(candidate.weekly_ma20, 2),
                    "return_13w_pct": round(candidate.return_13w_pct, 2),
                    "return_26w_pct": round(candidate.return_26w_pct, 2),
                    "drawdown_26w_pct": round(candidate.drawdown_26w_pct, 2),
                    "reasons": candidate.reasons,
                }
                for candidate in momentum_candidates
            ],
            ensure_ascii=False,
        ),
    )
    trend_exit_codes = tuple(
        sorted(candidate.code for candidate in momentum_candidates if requires_momentum_trend_exit(candidate))
    )

    review_enabled = str(env.get("PENSION_REBALANCE_MOMENTUM_AI_REVIEW_ENABLED") or "1").strip().lower()
    if review_enabled not in {"1", "true", "t", "yes", "y", "on"}:
        return replace(
            signal,
            selected_momentum_code="",
            momentum_trend_exit_codes=trend_exit_codes,
        )

    review = review_pension_momentum_candidates(
        momentum_candidates,
        model=str(env.get("PENSION_REBALANCE_MOMENTUM_AI_MODEL") or "gpt-5.5").strip(),
        reasoning_effort=str(env.get("PENSION_REBALANCE_MOMENTUM_AI_REASONING_EFFORT") or "low").strip(),
    )
    print(
        "pension_momentum_review",
        {
            "selected_code": review.selected_code,
            "approved_codes": review.approved_codes,
            "summary": review.summary,
            "route": review.route,
        },
    )
    eligible_codes = {candidate.code for candidate in momentum_candidates if candidate.eligible}
    selected_code = review.selected_code
    if review.route not in {"paid", "local"} or selected_code not in eligible_codes:
        selected_code = ""
    return replace(
        signal,
        selected_momentum_code=selected_code,
        momentum_trend_exit_codes=trend_exit_codes,
    )


def _parking_code_from_env(env: dict[str, str]) -> str:
    parking_code = str(
        env.get("PENSION_REBALANCE_PARKING_CODE")
        or env.get("TRADING_RISK_OFF_PARKING_CODE")
        or TradeEngineConfig().risk_off_parking_code
        or ""
    ).strip()
    bond_code = str(env.get("PENSION_REBALANCE_US_BOND_CODE") or DEFAULT_US_SHORT_BOND_CODE).strip()
    return "" if parking_code and parking_code == bond_code else parking_code


def _allow_overweight_sells(signal: QuarterlyMarketSignal) -> bool:
    return signal.regime != "rising" or bool(signal.selected_momentum_code)


def _validate_buyable_assets(
    *,
    client: PensionKISClient,
    env: dict[str, str],
    assets: list[PensionAsset],
) -> list[PensionAsset]:
    config = TradeEngineConfig()
    master_map = load_stock_master_map(
        kospi_master_path=config.industry_kospi_master_path,
        kosdaq_master_path=config.industry_kosdaq_master_path,
    )
    end_date = date.today().strftime("%Y%m%d")
    avg_value_20d_by_code: dict[str, float] = {}
    for asset in assets:
        if not asset.buyable:
            continue
        _, avg_value_20d = client.daily_history(asset.code, end_date=end_date, lookback=30)
        avg_value_20d_by_code[asset.code] = avg_value_20d
    min_avg_value_20d = max(
        0.0,
        _env_float(
            "PENSION_REBALANCE_BUYABLE_MIN_AVG_VALUE_20D",
            _env_float("PENSION_REBALANCE_MOMENTUM_MIN_AVG_VALUE_20D", 1_000_000_000.0, env),
            env,
        ),
    )
    return validate_buyable_pension_assets(
        assets=assets,
        master_by_code=master_map,
        avg_value_20d_by_code=avg_value_20d_by_code,
        min_avg_value_20d=min_avg_value_20d,
    )


def _load_exit_review_monthly_prices(
    *,
    client: PensionKISClient,
    assets: list[PensionAsset],
) -> dict[str, list[tuple[str, int]]]:
    end_date = date.today()
    start_date = end_date - timedelta(days=365 * 5)
    histories: dict[str, list[tuple[str, int]]] = {}
    for code in pension_exit_chart_codes(assets=assets):
        try:
            histories[code] = client.monthly_prices(
                code,
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
            )
        except Exception as exc:
            print("pension_exit_monthly_chart_error", {"code": code, "error": type(exc).__name__})
    return histories


def _apply_buy_capacity(
    *,
    client: PensionKISClient,
    orders: list[PensionOrderPlan],
    orderable_cash: int,
    holdings: list[PensionHolding] | None = None,
    total_value: int | None = None,
    max_single_asset_weight_pct: float = DEFAULT_MAX_SINGLE_ASSET_WEIGHT_PCT,
) -> list[PensionOrderPlan]:
    priced_orders: list[PensionOrderPlan] = []
    for order in orders:
        if order.side != "BUY":
            priced_orders.append(order)
            continue
        limit_price = _aggressive_limit_price(side="BUY", price=order.price)
        priced_orders.append(
            replace(order, price=limit_price, amount=order.qty * limit_price)
        )
    return apply_buy_capacity(
        client=client,
        orders=priced_orders,
        orderable_cash=orderable_cash,
        holdings=holdings,
        total_value=total_value,
        max_single_asset_weight_pct=max_single_asset_weight_pct,
    )


def _split_order_qty(qty: int, split_count: int) -> list[int]:
    normalized_qty = max(0, int(qty))
    if normalized_qty <= 0:
        return []
    tranche_count = min(normalized_qty, max(1, int(split_count)))
    base_qty, remainder = divmod(normalized_qty, tranche_count)
    return [base_qty + (1 if index < remainder else 0) for index in range(tranche_count)]


def _buy_order_filled(client: PensionKISClient, *, code: str, order_id: str, qty: int) -> bool:
    fills = client.daily_order_fills(code=code, order_id=order_id, side="02")
    filled_qty = sum(_to_int(fill.get("filled_qty")) for fill in fills)
    return filled_qty >= qty


def _wait_for_buy_fill(
    client: PensionKISClient,
    result: dict[str, Any],
    *,
    env: dict[str, str] | None = None,
) -> bool:
    code = str(result.get("code") or "").strip()
    order_id = str(result.get("order_id") or "").strip()
    qty = _to_int(result.get("qty"))
    if not order_id or qty <= 0:
        return False

    timeout_sec = max(0, _env_int("PENSION_REBALANCE_BUY_FILL_TIMEOUT_SEC", 60, env))
    poll_sec = max(1, _env_int("PENSION_REBALANCE_BUY_FILL_POLL_SEC", 5, env))
    deadline = time.monotonic() + timeout_sec
    while True:
        if _buy_order_filled(client, code=code, order_id=order_id, qty=qty):
            return True
        if time.monotonic() >= deadline:
            print("buy_fill_pending", result)
            return False
        time.sleep(min(poll_sec, max(0.0, deadline - time.monotonic())))


def _execute_orders(
    client: PensionKISClient,
    orders: list[PensionOrderPlan],
    *,
    env: dict[str, str] | None = None,
) -> int:
    buy_split_count = max(1, _env_int("PENSION_REBALANCE_BUY_SPLIT_COUNT", 3, env))
    for order in orders:
        tranche_qtys = _split_order_qty(order.qty, buy_split_count) if order.side == "BUY" else [order.qty]
        for tranche_index, tranche_qty in enumerate(tranche_qtys, start=1):
            order_price = (
                _aggressive_limit_price(side=order.side, price=order.price)
                if order.side == "SELL"
                else order.price
            )
            result = client.place_order(side=order.side, code=order.code, qty=tranche_qty, price=order_price)
            print(
                "order_result",
                {
                    **result,
                    "tranche_index": tranche_index,
                    "tranche_count": len(tranche_qtys),
                },
            )
            if not result.get("success"):
                return 1
            if order.side == "BUY" and not _wait_for_buy_fill(client, result, env=env):
                order_id = str(result.get("order_id") or "").strip()
                if order_id:
                    client.cancel_order(order_id)
                return 1
    return 0


def _sell_order_filled(client: PensionKISClient, *, code: str, order_id: str, qty: int) -> bool:
    fills = client.daily_order_fills(code=code, order_id=order_id, side="01")
    filled_qty = sum(_to_int(fill.get("filled_qty")) for fill in fills)
    return filled_qty >= qty


def _wait_for_sell_fills(
    client: PensionKISClient,
    sell_results: list[dict[str, Any]],
    *,
    env: dict[str, str] | None = None,
) -> bool:
    timeout_sec = max(0, _env_int("PENSION_REBALANCE_SELL_FILL_TIMEOUT_SEC", 60, env))
    poll_sec = max(1, _env_int("PENSION_REBALANCE_SELL_FILL_POLL_SEC", 5, env))
    deadline = time.monotonic() + timeout_sec
    while True:
        pending: list[dict[str, Any]] = []
        for result in sell_results:
            if not result.get("success"):
                return False
            code = str(result.get("code") or "").strip()
            order_id = str(result.get("order_id") or "").strip()
            qty = _to_int(result.get("qty"))
            if not order_id:
                pending.append(result)
                continue
            if _sell_order_filled(client, code=code, order_id=order_id, qty=qty):
                continue
            pending.append(result)

        if not pending:
            return True
        if time.monotonic() >= deadline:
            print("sell_fill_pending", pending)
            for result in pending:
                order_id = str(result.get("order_id") or "").strip()
                if order_id:
                    client.cancel_order(order_id)
            return False
        time.sleep(poll_sec)


def _refresh_prices(client: PensionKISClient, holdings: list[PensionHolding], assets: list[PensionAsset]) -> dict[str, int]:
    prices = {holding.code: holding.price for holding in holdings if holding.price > 0}
    for asset in assets:
        if asset.buyable and asset.code not in prices:
            prices[asset.code] = int(client.quote(asset.code).get("price") or 0)
    return prices


def _orderable_cash_for_buys(
    *,
    client: PensionKISClient,
    assets: list[PensionAsset],
    prices: dict[str, int],
    cash: int,
    env: dict[str, str] | None = None,
) -> int:
    del client, assets, prices
    return orderable_cash_for_buys(
        cash=cash,
        cash_buffer_pct=_env_float("PENSION_REBALANCE_ORDER_CASH_BUFFER_PCT", 0.10, env),
    )


def _review_and_validate_sell_orders(
    *,
    client: PensionKISClient,
    env: dict[str, str],
    holdings: list[PensionHolding],
    cash: int,
    assets: list[PensionAsset],
    target_weights: dict[str, float],
    plan: PensionRebalancePlan,
    signal: QuarterlyMarketSignal,
    sell_split_count: int,
) -> tuple[list[PensionOrderPlan], list[PensionHolding], int, dict[str, int], dict[str, int]]:
    sell_orders = cap_pension_sell_orders(
        [order for order in plan.orders if order.side == "SELL"],
        holdings=holdings,
        split_count=sell_split_count,
    )
    if sell_orders:
        exit_review = review_pension_sell_orders(
            holdings=holdings,
            cash=cash,
            assets=assets,
            target_weights=target_weights,
            sell_orders=sell_orders,
            regime=signal.regime,
            monthly_prices_by_code=_load_exit_review_monthly_prices(
                client=client,
                assets=assets,
            ),
            output_dir=str(
                Path(
                    env.get("PENSION_REBALANCE_EXIT_REVIEW_OUTPUT_DIR")
                    or DEFAULT_EXIT_REVIEW_OUTPUT_DIR
                )
                / date.today().strftime("%Y%m%d")
            ),
            model=str(
                env.get("PENSION_REBALANCE_EXIT_AI_MODEL")
                or env.get("PENSION_REBALANCE_MOMENTUM_AI_MODEL")
                or "gpt-5.5"
            ).strip(),
            reasoning_effort=str(
                env.get("PENSION_REBALANCE_EXIT_AI_REASONING_EFFORT") or "high"
            ).strip(),
        )
        print(
            "pension_exit_review",
            {
                "approved_codes": exit_review.approved_codes,
                "summary": exit_review.summary,
                "balance_assessment": exit_review.balance_assessment,
                "route": exit_review.route,
                "chart_paths": exit_review.chart_paths,
                "decisions": [asdict(decision) for decision in exit_review.decisions],
            },
        )
        approved_codes = (
            set(exit_review.approved_codes)
            if exit_review.route in {"paid", "local"}
            else set()
        )
        sell_orders = [order for order in sell_orders if order.code in approved_codes]

    latest_holdings, latest_cash = client.balance()
    latest_prices = _refresh_prices(client, latest_holdings, assets)
    sellable_qty_by_code = {
        code: _to_int(client.sell_order_capacity(code).get("ord_psbl_qty"))
        for code in {order.code for order in sell_orders}
    }
    sell_safety = aggregate_and_validate_sell_orders(
        orders=sell_orders,
        holdings=latest_holdings,
        split_count=sell_split_count,
        sellable_qty_by_code=sellable_qty_by_code,
    )
    return (
        sell_safety.orders,
        latest_holdings,
        latest_cash,
        latest_prices,
        sell_safety.max_qty_by_code,
    )


def _submit_and_wait_sell_orders(
    *,
    client: PensionKISClient,
    env: dict[str, str],
    journal: PensionExecutionJournal,
    execution_id: str,
    sell_orders: list[PensionOrderPlan],
) -> bool:
    sell_results: list[dict[str, Any]] = []
    for order in sell_orders:
        order_price = _aggressive_limit_price(side="SELL", price=order.price)
        journal.mark_sell_submitted(
            execution_id=execution_id,
            code=order.code,
            qty=order.qty,
        )
        result = {
            **client.place_order(
                side=order.side,
                code=order.code,
                qty=order.qty,
                price=order_price,
            ),
            "bucket": order.bucket,
            "reason": order.reason,
        }
        print("sell_order_result", result)
        sell_results.append(result)
        if not result.get("success"):
            journal.mark_failed(
                execution_id=execution_id,
                reason=f"sell order rejected: {order.code}",
            )
            return False
    if _wait_for_sell_fills(client, sell_results, env=env):
        journal.mark_sells_filled(execution_id=execution_id)
        return True
    journal.mark_failed(
        execution_id=execution_id,
        reason="sell fill timeout; pending orders cancelled",
    )
    return False


def _build_final_buy_plan(
    *,
    client: PensionKISClient,
    env: dict[str, str],
    holdings: list[PensionHolding],
    cash: int,
    assets: list[PensionAsset],
    prices: dict[str, int],
    signal: QuarterlyMarketSignal,
    min_order_amount: int,
    restore_step: float,
    trend_exit_step_pct: float,
    reserved_cash_amount: int,
) -> tuple[PensionRebalancePlan, int]:
    orderable_cash = _orderable_cash_for_buys(
        client=client,
        assets=assets,
        prices=prices,
        cash=cash,
        env=env,
    )
    plan = build_pension_rebalance_plan(
        holdings=holdings,
        cash=orderable_cash,
        assets=assets,
        prices=prices,
        regime=signal.regime,
        min_order_amount=min_order_amount,
        allow_sells=False,
        deploy_leftover_to=None,
        parking_code=_parking_code_from_env(env),
        gradual_equity_restore_step=restore_step,
        trend_exit_step_pct=trend_exit_step_pct,
        reserved_cash_amount=min(reserved_cash_amount, orderable_cash),
    )
    account_total_value = cash + sum(holding.value for holding in holdings)
    plan.orders[:] = _apply_buy_capacity(
        client=client,
        orders=[order for order in plan.orders if order.side == "BUY"],
        orderable_cash=orderable_cash,
        holdings=holdings,
        total_value=account_total_value,
        max_single_asset_weight_pct=_env_float(
            "PENSION_REBALANCE_MAX_SINGLE_ASSET_WEIGHT_PCT",
            DEFAULT_MAX_SINGLE_ASSET_WEIGHT_PCT,
            env,
        ),
    )
    return plan, orderable_cash


def _print_plan_summary(
    *,
    args: argparse.Namespace,
    signal: QuarterlyMarketSignal,
    plan: PensionRebalancePlan,
    balance_cash: int,
    orderable_cash: int,
) -> None:
    print("mode", "EXECUTE" if args.execute else "DRY_RUN")
    print("job", "CASH_SWEEP" if args.cash_sweep else "REBALANCE")
    print("regime", plan.regime)
    print("quarterly_reference_return_pct", round(signal.reference_return_pct, 2))
    print("quarterly_kospi_return_pct", round(signal.kospi_return_pct, 2))
    print("quarterly_nasdaq_return_pct", round(signal.nasdaq_return_pct, 2))
    print("reference_current_price", signal.current_price)
    print("reference_moving_average_10m", round(signal.moving_average_10m, 2))
    print("reference_drawdown_from_recent_high_pct", round(signal.drawdown_from_recent_high_pct, 2))
    print("reference_three_month_return_pct", round(signal.three_month_return_pct, 2))
    print("selected_momentum_code", signal.selected_momentum_code)
    print("momentum_trend_exit_codes", signal.momentum_trend_exit_codes)
    print("total_value", plan.total_value)
    print("cash", plan.cash)
    if args.execute:
        print("balance_cash_d2", balance_cash)
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


def _run_pension_rebalance(args: argparse.Namespace, env: dict[str, str]) -> int:
    client = PensionKISClient(env)
    if args.execute:
        assert_no_open_orders(client.open_orders())
    signal = _resolve_quarterly_signal(client, env, args.regime)
    holdings, cash = client.balance()
    assets = _assets_from_env(
        env,
        selected_momentum_code=signal.selected_momentum_code,
        momentum_trend_exit_codes=signal.momentum_trend_exit_codes,
        holdings=holdings,
    )
    assets = _validate_buyable_assets(client=client, env=env, assets=assets)

    prices = _refresh_prices(client, holdings, assets)

    restore_step = max(
        0.0,
        min(0.5, _env_float("PENSION_REBALANCE_EQUITY_RESTORE_STEP_PCT", 0.20, env)),
    )
    trend_exit_split_count = max(
        1,
        _env_int("PENSION_REBALANCE_TREND_EXIT_SPLIT_COUNT", 3, env),
    )
    trend_exit_step_pct = 1.0 / trend_exit_split_count
    allow_overweight_sells = _allow_overweight_sells(signal)
    print("overweight_sell_action", "ENABLED" if allow_overweight_sells else "DISABLED_NO_SELECTION")
    plan = build_pension_rebalance_plan(
        holdings=holdings,
        cash=cash,
        assets=assets,
        prices=prices,
        regime=signal.regime,
        min_order_amount=args.min_order_amount,
        allow_sells=not args.cash_sweep and not args.no_sells,
        allow_overweight_sells=allow_overweight_sells,
        deploy_leftover_to=None,
        parking_code=_parking_code_from_env(env),
        gradual_equity_restore_step=restore_step,
        trend_exit_step_pct=trend_exit_step_pct,
    )
    account_target_weights = dict(plan.target_weights)

    if args.if_drift:
        drift_threshold_pct = max(
            0.0,
            min(100.0, _env_float("PENSION_REBALANCE_DRIFT_THRESHOLD_PCT", 10.0, env)),
        )
        drift_pct = max_target_weight_drift_pct(
            holdings=holdings,
            cash=cash,
            assets=assets,
            target_weights=plan.target_weights,
        )
        print("drift_threshold_pct", drift_threshold_pct)
        print("max_target_weight_drift_pct", drift_pct)
        trend_exit_orders = [
            order
            for order in plan.orders
            if order.side == "SELL" and order.code in set(signal.momentum_trend_exit_codes)
        ]
        if drift_pct < drift_threshold_pct and not trend_exit_orders:
            print("drift_action", "SKIP")
            return 0
        if trend_exit_orders:
            print("trend_exit_action", "PARTIAL_SELL")
        print("drift_action", "REBALANCE")

    orderable_cash = cash
    execution_id = ""
    execution_journal: PensionExecutionJournal | None = None
    if args.execute:
        sell_split_count = max(
            2,
            _env_int("PENSION_REBALANCE_SELL_SPLIT_COUNT", trend_exit_split_count, env),
        )
        sell_orders, holdings, cash, prices, max_sell_qty_by_code = (
            _review_and_validate_sell_orders(
                client=client,
                env=env,
                holdings=holdings,
                cash=cash,
                assets=assets,
                target_weights=account_target_weights,
                plan=plan,
                signal=signal,
                sell_split_count=sell_split_count,
            )
        )
        signal_key = pension_signal_key(
            asof_date=date.today().strftime("%Y%m%d"),
            job="CASH_SWEEP" if args.cash_sweep else "REBALANCE",
            regime=signal.regime,
            selected_momentum_code=signal.selected_momentum_code,
            trend_exit_codes=signal.momentum_trend_exit_codes,
        )
        execution_journal = PensionExecutionJournal(
            Path(
                env.get("PENSION_REBALANCE_EXECUTION_STATE_PATH")
                or DEFAULT_EXECUTION_STATE_PATH
            )
        )
        execution_id, sell_plan_hash = execution_journal.begin(
            signal_key=signal_key,
            sell_orders=sell_orders,
        )
        print(
            "sell_execution_plan",
            {
                "execution_id": execution_id,
                "plan_hash": sell_plan_hash,
                "absolute_max_qty_by_code": max_sell_qty_by_code,
                "orders": [asdict(order) for order in sell_orders],
            },
        )
        trend_exit_proceeds = sum(
            order.amount
            for order in sell_orders
            if order.code in set(signal.momentum_trend_exit_codes)
        )
        assert_no_open_orders(client.open_orders())
        try:
            sell_succeeded = not sell_orders or _submit_and_wait_sell_orders(
                client=client,
                env=env,
                journal=execution_journal,
                execution_id=execution_id,
                sell_orders=sell_orders,
            )
        except Exception as exc:
            execution_journal.mark_failed(
                execution_id=execution_id,
                reason=f"sell execution error: {type(exc).__name__}",
            )
            raise
        if not sell_succeeded:
            return 1
        if sell_orders:
            holdings, cash = client.balance()
            prices = _refresh_prices(client, holdings, assets)
        try:
            plan, orderable_cash = _build_final_buy_plan(
                client=client,
                env=env,
                holdings=holdings,
                cash=cash,
                assets=assets,
                prices=prices,
                signal=signal,
                min_order_amount=args.min_order_amount,
                restore_step=restore_step,
                trend_exit_step_pct=trend_exit_step_pct,
                reserved_cash_amount=trend_exit_proceeds,
            )
        except Exception as exc:
            execution_journal.mark_failed(
                execution_id=execution_id,
                reason=f"buy plan error: {type(exc).__name__}",
            )
            raise
        buy_plan_hash = execution_journal.record_buy_plan(
            execution_id=execution_id,
            signal_key=signal_key,
            buy_orders=plan.orders,
        )
        print(
            "buy_execution_plan",
            {
                "execution_id": execution_id,
                "plan_hash": buy_plan_hash,
                "orderable_cash": orderable_cash,
                "orders": [asdict(order) for order in plan.orders],
            },
        )

    _print_plan_summary(
        args=args,
        signal=signal,
        plan=plan,
        balance_cash=cash,
        orderable_cash=orderable_cash,
    )

    if not args.execute:
        return 0

    try:
        assert_no_open_orders(client.open_orders())
        result = _execute_orders(client, plan.orders, env=env)
    except Exception as exc:
        if execution_journal is not None and execution_id:
            execution_journal.mark_failed(
                execution_id=execution_id,
                reason=f"buy execution error: {type(exc).__name__}",
            )
        raise
    if execution_journal is not None and execution_id:
        if result == 0:
            execution_journal.mark_success(execution_id=execution_id)
        else:
            execution_journal.mark_failed(
                execution_id=execution_id,
                reason="buy execution failed or timed out",
            )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan or execute KIS pension-account rebalancing.")
    parser.add_argument("--regime", default="auto", help="auto, rising, falling, neutral, crash")
    parser.add_argument("--execute", action="store_true", help="place limit orders; default is dry-run")
    parser.add_argument("--no-sells", action="store_true", help="only plan buys with available cash")
    parser.add_argument("--min-order-amount", type=int, default=50_000)
    parser.add_argument("--cash-sweep", action="store_true", help="daily cash/parking sweep without quarterly rebalance")
    parser.add_argument(
        "--if-drift",
        action="store_true",
        help="rebalance only when a core bucket differs from its target by the configured threshold",
    )
    args = parser.parse_args()
    if args.cash_sweep and args.if_drift:
        parser.error("--cash-sweep and --if-drift cannot be used together")

    env = {**_load_env_file(DEFAULT_RUNTIME_ENV), **os.environ}
    lock_path = Path(
        env.get("PENSION_REBALANCE_EXECUTION_LOCK_PATH") or DEFAULT_EXECUTION_LOCK_PATH
    )
    lock_context = pension_execution_lock(lock_path) if args.execute else nullcontext()
    with lock_context:
        return _run_pension_rebalance(args, env)


if __name__ == "__main__":
    raise SystemExit(main())
