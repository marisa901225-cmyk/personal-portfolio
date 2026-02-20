from __future__ import annotations

import pandas as pd

from .interfaces import TradingAPI
from .utils import compute_sma, parse_numeric


def _single_regime(api: TradingAPI, asof: str, code: str) -> str:
    bars = api.daily_bars(code=code, end=asof, lookback=80)
    if bars is None or bars.empty or len(bars) < 60:
        return "NEUTRAL"

    close_s = pd.to_numeric(bars.get("close"), errors="coerce")
    ma20 = compute_sma(close_s, 20).iloc[-1]
    ma60 = compute_sma(close_s, 60).iloc[-1]
    close = parse_numeric(close_s.iloc[-1])

    if close is None or pd.isna(ma20) or pd.isna(ma60):
        return "NEUTRAL"
    if close > ma60 and ma20 > ma60:
        return "RISK_ON"
    if close < ma60 and ma20 < ma60:
        return "RISK_OFF"
    return "NEUTRAL"


def get_regime(
    api: TradingAPI,
    asof: str,
    *,
    primary_code: str = "069500",
    confirmation_code: str = "229200",
    use_confirmation: bool = False,
) -> str:
    primary = _single_regime(api, asof, primary_code)
    if not use_confirmation:
        return primary

    confirm = _single_regime(api, asof, confirmation_code)
    if primary == "RISK_OFF" or confirm == "RISK_OFF":
        return "RISK_OFF"
    if primary == "RISK_ON" and confirm == "RISK_ON":
        return "RISK_ON"
    return "NEUTRAL"
