from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta
import json
from typing import Any

from backend.integrations.kis.trading_adapter import KISDirectCredentials, create_trading_api
from backend.services.pension_exit_review import pension_exit_chart_codes
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
    normalized_price_history,
    resolve_pension_product,
    validate_buyable_pension_assets,
)
from backend.services.pension_rebalancing import (
    DEFAULT_MOMENTUM_OUTPERFORMANCE_THRESHOLD_PCT,
    PensionAsset,
    PensionHolding,
    QuarterlyMarketSignal,
    calculate_equity_trend_metrics,
    normalize_regime,
    pct_return,
    quarter_start,
    resolve_quarterly_market_signal,
)
from backend.services.trading_engine.config import TradeEngineConfig
from backend.services.trading_engine.stock_master import load_stock_master_map
from backend.services.trading_engine.utils import compute_avg_value


DEFAULT_PROD_URL = "https://openapi.koreainvestment.com:9443"
DEFAULT_US_SHORT_BOND_CODE = "0048J0"


def to_int(value: Any) -> int:
    try:
        return int(float(str(value or "0").replace(",", "").strip() or "0"))
    except (TypeError, ValueError):
        return 0


def to_float(value: Any) -> float:
    try:
        return float(str(value or "0").replace(",", "").strip() or "0")
    except (TypeError, ValueError):
        return 0.0


def env_float(env: dict[str, str], name: str, default: float) -> float:
    raw = str(env.get(name, "") or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


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
            qty = to_int(row.get("qty"))
            if qty <= 0:
                continue
            price = to_int(row.get("current_price"))
            holdings.append(
                PensionHolding(
                    code=str(row.get("code") or "").strip(),
                    name=str(row.get("name") or "").strip(),
                    qty=qty,
                    price=price,
                    value=qty * price,
                    avg_price=to_float(row.get("avg_price")),
                    pnl=to_int(row.get("pnl")),
                    pnl_rate=to_float(row.get("pnl_rate")),
                )
            )
        return holdings, self.api.cash_available()

    def quote(self, code: str) -> dict[str, Any]:
        return self.api.quote(code)

    def buy_order_capacity(self, code: str, *, price: int = 0, order_type: str = "00") -> dict[str, int]:
        return self.api.buy_order_capacity(code=code, price=price, order_type=order_type)

    def sell_order_capacity(self, code: str) -> dict[str, int]:
        return self.api.sell_order_capacity(code)

    def _prices(
        self,
        code: str,
        *,
        start_date: str,
        end_date: str,
        period: str,
    ) -> list[tuple[str, int]]:
        return normalized_price_history(
            self.api.chart_prices(
                code,
                start_date=start_date,
                end_date=end_date,
                period_div_code=period,
            )
        )

    def daily_prices(self, code: str, *, start_date: str, end_date: str) -> list[tuple[str, int]]:
        return self._prices(code, start_date=start_date, end_date=end_date, period="D")

    def monthly_prices(self, code: str, *, start_date: str, end_date: str) -> list[tuple[str, int]]:
        return self._prices(code, start_date=start_date, end_date=end_date, period="M")

    def weekly_prices(self, code: str, *, start_date: str, end_date: str) -> list[tuple[str, int]]:
        return self._prices(code, start_date=start_date, end_date=end_date, period="W")

    def daily_history(self, code: str, *, end_date: str, lookback: int) -> tuple[list[tuple[str, int]], float]:
        bars = self.api.daily_bars(code=code, end=end_date, lookback=lookback)
        avg_value_20d, _ = compute_avg_value(bars, window=20)
        prices = [
            (str(row.get("date") or ""), to_int(row.get("close")))
            for row in bars.to_dict(orient="records")
            if to_int(row.get("close")) > 0
        ]
        return normalized_price_history(prices), float(avg_value_20d or 0.0)

    def latest_daily_candle(self, code: str, *, end_date: str) -> dict[str, int | str]:
        bars = self.api.daily_bars(code=code, end=end_date, lookback=3)
        records = bars.to_dict(orient="records")
        if not records:
            raise RuntimeError(f"daily candle unavailable: {code}")
        latest = records[-1]
        return {
            "date": str(latest.get("date") or ""),
            "open": to_int(latest.get("open")),
            "close": to_int(latest.get("close")),
        }

    def place_order(self, *, side: str, code: str, qty: int, price: int) -> dict[str, Any]:
        result = self.api.place_order(
            side=side,
            code=code,
            qty=qty,
            order_type="limit",
            price=price,
        )
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
        return self.api.daily_order_fills(
            start_date=today,
            end_date=today,
            code=code,
            order_id=order_id,
            side=side,
        )


def assets_from_env(
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
    parking = parking_code_from_env(env, allow_bond_duplicate=True)
    selected = None if selected_momentum_code is None else str(selected_momentum_code).strip()
    if selected is None:
        momentum_codes = [(kospi, True), (nasdaq, True)]
    elif selected:
        momentum_codes = [(selected, True), (kospi, False), (nasdaq, False)]
    else:
        momentum_codes = [(kospi, False), (nasdaq, False)]

    trend_exits = {str(code).strip() for code in momentum_trend_exit_codes if str(code).strip()}
    assets = [PensionAsset(sp500, "sp500", "S&P500")]
    seen = {sp500}
    for code, buyable in momentum_codes:
        if code and code not in seen:
            assets.append(
                PensionAsset(
                    code,
                    "momentum",
                    "Momentum ETF",
                    buyable=buyable,
                    trend_exit=code in trend_exits,
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
                trend_exit=code in trend_exits,
            )
        )
        seen.add(code)
    for code in sorted(trend_exits - seen):
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


def parking_code_from_env(env: dict[str, str], *, allow_bond_duplicate: bool = False) -> str:
    parking_code = str(env.get("PENSION_REBALANCE_PARKING_CODE") or "").strip()
    bond_code = str(env.get("PENSION_REBALANCE_US_BOND_CODE") or DEFAULT_US_SHORT_BOND_CODE).strip()
    if not allow_bond_duplicate and parking_code and parking_code == bond_code:
        return ""
    return parking_code


def allow_overweight_sells(signal: QuarterlyMarketSignal) -> bool:
    return signal.regime != "rising" or bool(signal.selected_momentum_code)


def quarterly_return(client: PensionKISClient, code: str, *, today: date) -> float:
    prices = normalized_price_history(
        client.daily_prices(
            code,
            start_date=quarter_start(today).strftime("%Y%m%d"),
            end_date=today.strftime("%Y%m%d"),
        )
    )
    if len(prices) >= 2:
        return pct_return(float(prices[0][1]), float(prices[-1][1]))
    if len(prices) == 1:
        current_price = int(client.quote(code).get("price") or prices[-1][1])
        return pct_return(float(prices[0][1]), float(current_price))
    return 0.0


def analyze_momentum_universe(
    client: PensionKISClient,
    env: dict[str, str],
    *,
    kospi_code: str,
    nasdaq_code: str,
    end_date: str,
) -> list[PensionMomentumCandidate]:
    config = TradeEngineConfig()
    try:
        master_map = load_stock_master_map(
            kospi_master_path=config.industry_kospi_master_path,
            kosdaq_master_path=config.industry_kosdaq_master_path,
        )
    except Exception as exc:
        print("pension_momentum_master_error", {"error": type(exc).__name__})
        master_map = {}
    universe_by_code: dict[str, tuple[str, str]] = {}
    for info in master_map.values():
        code = str(info.code or "").strip()
        family = pension_index_family(info.name)
        if info.is_etf and code and not code.upper().startswith("Q") and family:
            if family != "korea_kospi" or code == kospi_code:
                universe_by_code[code] = (str(info.name or "").strip(), family)

    seeds = (
        (kospi_code, "237350", "KODEX 코스피100", "korea_kospi"),
        (nasdaq_code, "426030", "TIME 미국나스닥100액티브", "us_nasdaq100"),
    )
    for code, default_code, default_name, expected_family in seeds:
        if code in universe_by_code:
            continue
        info = master_map.get(code)
        actual_name = str(getattr(info, "name", "") or "").strip()
        actual_family = pension_index_family(actual_name)
        if info is not None and info.is_etf and actual_family == expected_family:
            universe_by_code[code] = (actual_name, actual_family)
        elif info is None and code == default_code:
            universe_by_code[code] = (default_name, expected_family)
        else:
            print(
                "pension_momentum_seed_rejected",
                {"code": code, "name": actual_name, "family": actual_family},
            )

    histories: dict[str, list[tuple[str, int]]] = {}
    liquid: list[PensionIndexCandidate] = []
    for code, (name, family) in sorted(universe_by_code.items()):
        try:
            daily_prices, avg_value = client.daily_history(code, end_date=end_date, lookback=180)
        except Exception as exc:
            print("pension_momentum_history_error", {"code": code, "error": type(exc).__name__})
            continue
        histories[code] = daily_prices
        liquid.append(PensionIndexCandidate(code, name, family, avg_value))

    min_avg_value = max(0.0, env_float(env, "PENSION_REBALANCE_MOMENTUM_MIN_AVG_VALUE_20D", 1_000_000_000.0))
    selected = select_liquid_pension_index_candidates(
        liquid,
        min_avg_value_20d=min_avg_value,
        preferred_codes={kospi_code, nasdaq_code},
    )
    print(
        "pension_momentum_universe",
        {
            "scanned": len(liquid),
            "min_avg_value_20d": int(min_avg_value),
            "selected": [
                {
                    "code": item.code,
                    "name": item.name,
                    "family": item.family,
                    "avg_value_20d": int(item.avg_value_20d),
                }
                for item in selected
            ],
        },
    )
    weekly_start = (datetime.strptime(end_date, "%Y%m%d").date() - timedelta(days=540)).strftime("%Y%m%d")
    analyzed: list[PensionMomentumCandidate] = []
    for candidate in selected:
        try:
            weekly = client.weekly_prices(candidate.code, start_date=weekly_start, end_date=end_date)
        except Exception as exc:
            print("pension_momentum_weekly_error", {"code": candidate.code, "error": type(exc).__name__})
            continue
        analyzed.append(
            analyze_pension_momentum_candidate(
                code=candidate.code,
                name=candidate.name,
                daily_prices=histories[candidate.code],
                weekly_prices=weekly,
                family=candidate.family,
                avg_value_20d=candidate.avg_value_20d,
            )
        )
    return analyzed


def resolve_quarterly_signal(
    client: PensionKISClient,
    env: dict[str, str],
    requested: str,
    holdings: list[PensionHolding] | None = None,
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
    trend_start = (today - timedelta(days=540)).strftime("%Y%m%d")
    trend_end = today.strftime("%Y%m%d")
    signal = resolve_quarterly_market_signal(
        reference_return_pct=quarterly_return(client, sp500_code, today=today),
        kospi_return_pct=quarterly_return(client, kospi_code, today=today),
        nasdaq_return_pct=quarterly_return(client, nasdaq_code, today=today),
        kospi_code=kospi_code,
        nasdaq_code=nasdaq_code,
        momentum_outperformance_threshold_pct=max(
            0.0,
            env_float(
                env,
                "PENSION_REBALANCE_MOMENTUM_OUTPERFORMANCE_PCT",
                DEFAULT_MOMENTUM_OUTPERFORMANCE_THRESHOLD_PCT,
            ),
        ),
        trend_metrics=calculate_equity_trend_metrics(
            daily_prices=client.daily_prices(sp500_code, start_date=trend_start, end_date=trend_end),
            monthly_prices=client.monthly_prices(sp500_code, start_date=trend_start, end_date=trend_end),
        ),
    )
    configured = str(env.get("PENSION_REBALANCE_REGIME") or "").strip()
    if requested != "auto":
        signal = replace(signal, regime=normalize_regime(requested))
    elif configured:
        signal = replace(signal, regime=normalize_regime(configured))

    candidates = analyze_momentum_universe(
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
                    "code": item.code,
                    "name": item.name,
                    "family": item.family,
                    "avg_value_20d": int(item.avg_value_20d),
                    "score": item.score,
                    "eligible": item.eligible,
                    "weekly_ma10": round(item.weekly_ma10, 2),
                    "weekly_ma20": round(item.weekly_ma20, 2),
                    "return_13w_pct": round(item.return_13w_pct, 2),
                    "return_26w_pct": round(item.return_26w_pct, 2),
                    "drawdown_26w_pct": round(item.drawdown_26w_pct, 2),
                    "reasons": item.reasons,
                }
                for item in candidates
            ],
            ensure_ascii=False,
        ),
    )
    trend_exit_codes = tuple(
        sorted(item.code for item in candidates if requires_momentum_trend_exit(item))
    )
    review_enabled = str(env.get("PENSION_REBALANCE_MOMENTUM_AI_REVIEW_ENABLED") or "1").strip().lower()
    if review_enabled not in {"1", "true", "t", "yes", "y", "on"}:
        return replace(signal, selected_momentum_code="", momentum_trend_exit_codes=trend_exit_codes)
    review = review_pension_momentum_candidates(
        candidates,
        holdings=holdings,
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
    eligible_codes = {item.code for item in candidates if item.eligible}
    selected_code = review.selected_code
    if review.route not in {"paid", "local"} or selected_code not in eligible_codes:
        selected_code = ""
    return replace(
        signal,
        selected_momentum_code=selected_code,
        momentum_trend_exit_codes=trend_exit_codes,
    )


def validate_buyable_assets(
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
    avg_values: dict[str, float] = {}
    for asset in assets:
        if asset.buyable:
            _, avg_values[asset.code] = client.daily_history(asset.code, end_date=end_date, lookback=30)
    return validate_buyable_pension_assets(
        assets=assets,
        master_by_code=master_map,
        avg_value_20d_by_code=avg_values,
        min_avg_value_20d=max(
            0.0,
            env_float(
                env,
                "PENSION_REBALANCE_BUYABLE_MIN_AVG_VALUE_20D",
                env_float(env, "PENSION_REBALANCE_MOMENTUM_MIN_AVG_VALUE_20D", 1_000_000_000.0),
            ),
        ),
    )


def load_exit_review_monthly_prices(
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


def refresh_prices(
    client: PensionKISClient,
    holdings: list[PensionHolding],
    assets: list[PensionAsset],
) -> dict[str, int]:
    prices = {holding.code: holding.price for holding in holdings if holding.price > 0}
    for asset in assets:
        if asset.buyable and asset.code not in prices:
            prices[asset.code] = int(client.quote(asset.code).get("price") or 0)
    return prices


__all__ = [
    "PensionKISClient",
    "allow_overweight_sells",
    "analyze_momentum_universe",
    "assets_from_env",
    "env_float",
    "load_exit_review_monthly_prices",
    "parking_code_from_env",
    "quarterly_return",
    "refresh_prices",
    "resolve_quarterly_signal",
    "to_int",
    "validate_buyable_assets",
]
