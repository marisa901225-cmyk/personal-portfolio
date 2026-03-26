from __future__ import annotations

import pandas as pd
from datetime import datetime
from typing import Any

from .interfaces import TradingAPI
from .utils import compute_sma, normalize_bar_date, parse_numeric


def _is_in_cooldown(asof: str, last_panic_date: str | None, days: int = 3) -> bool:
    if not last_panic_date:
        return False
    try:
        # 형식: YYYYMMDD
        d_asof = datetime.strptime(asof, "%Y%m%d")
        d_panic = datetime.strptime(last_panic_date, "%Y%m%d")
        diff = (d_asof - d_panic).days
        # 패닉 발생 후 지정된 영업일(근사치) 동안 RISK_OFF 유지
        return 0 < diff <= days
    except Exception:
        return False


def _find_recent_panic_date(bars: pd.DataFrame, close_s: pd.Series, *, fallback_date: str) -> str | None:
    pct_change = close_s.pct_change()
    recent_panic = pct_change.tail(3)
    recent_panic = recent_panic[recent_panic <= -0.05]
    if recent_panic.empty:
        return None

    if "date" not in bars.columns:
        return normalize_bar_date(fallback_date)

    panic_dates = bars.loc[recent_panic.index, "date"]
    if panic_dates.empty:
        return normalize_bar_date(fallback_date)
    return normalize_bar_date(panic_dates.iloc[-1])


def _single_regime(
    api: TradingAPI, 
    asof: str, 
    code: str, 
    vol_threshold: float = 0.05
) -> tuple[str, str | None]:
    """
    Returns (regime, detected_panic_date)
    """
    bars = api.daily_bars(code=code, end=asof, lookback=80)
    if bars is None or bars.empty or len(bars) < 60:
        return "NEUTRAL", None

    # ✅ 정렬 강제 (과거 -> 최신)
    if "date" in bars.columns:
        bars = bars.sort_values("date", ascending=True)
    else:
        bars = bars.sort_index(ascending=True)

    close_s = pd.to_numeric(bars.get("close"), errors="coerce").dropna()
    if len(close_s) < 60:
        return "NEUTRAL", None

    # 최근 3거래일 창에서 패닉을 다시 보더라도 실제 패닉 발생일을 유지한다.
    panic_date = _find_recent_panic_date(bars, close_s, fallback_date=asof)
    if panic_date is not None:
        return "RISK_OFF", panic_date

    pct_change = close_s.pct_change()

    # 2. ✅ 볼라(변동성) 게이트: 20일 표준편차
    vol = pct_change.rolling(20).std().iloc[-1]
    if not pd.isna(vol) and vol > vol_threshold:
        return "RISK_OFF", None

    # 3. SMA 트렌드 로직
    ma20 = compute_sma(close_s, 20).iloc[-1]
    ma60 = compute_sma(close_s, 60).iloc[-1]
    close = float(close_s.iloc[-1])

    if pd.isna(ma20) or pd.isna(ma60):
        return "NEUTRAL", None
    
    if close > ma60 and ma20 > ma60:
        return "RISK_ON", None
    if close < ma60 and ma20 < ma60:
        return "RISK_OFF", None
    
    return "NEUTRAL", None


def detect_intraday_circuit_breaker(
    api: TradingAPI,
    *,
    asof: str,
    code: str,
    one_bar_drop_pct: float = -1.2,
    window_minutes: int = 5,
    window_drop_pct: float = -2.0,
    day_change_pct: float = -3.0,
) -> tuple[bool, dict[str, Any]]:
    """
    Intraday panic detector using minute bars when available.

    Returns:
      (is_triggered, metadata)
      metadata keys: reason, day_change_pct, last_bar_drop_pct, window_drop_pct
    """
    intraday_fn = getattr(api, "intraday_bars", None)
    if not callable(intraday_fn):
        return False, {"reason": "UNSUPPORTED"}

    normalized_asof = _normalize_yyyymmdd(asof)
    lookback = max(15, int(window_minutes) + 5)
    try:
        bars = intraday_fn(code=code, asof=normalized_asof, lookback=lookback)
    except Exception:
        return False, {"reason": "FETCH_FAILED"}

    if bars is None or bars.empty:
        return False, {"reason": "NO_DATA"}

    bars = _sort_intraday_bars(bars)
    close_s = pd.to_numeric(bars.get("close"), errors="coerce").dropna()
    if len(close_s) < 2:
        return False, {"reason": "INSUFFICIENT_DATA"}

    day_chg = _resolve_day_change_pct(api, code, bars)
    if day_chg is not None and day_chg <= day_change_pct:
        return True, {
            "reason": "DAY_CHANGE_DROP",
            "day_change_pct": round(float(day_chg), 4),
        }

    last_bar_drop = (float(close_s.iloc[-1]) / float(close_s.iloc[-2]) - 1.0) * 100.0
    if last_bar_drop <= one_bar_drop_pct:
        return True, {
            "reason": "INTRADAY_BAR_DROP",
            "last_bar_drop_pct": round(float(last_bar_drop), 4),
        }

    n = max(2, int(window_minutes))
    if len(close_s) >= (n + 1):
        window_drop = (float(close_s.iloc[-1]) / float(close_s.iloc[-(n + 1)]) - 1.0) * 100.0
        if window_drop <= window_drop_pct:
            return True, {
                "reason": "INTRADAY_WINDOW_DROP",
                "window_drop_pct": round(float(window_drop), 4),
                "window_minutes": n,
            }

    return False, {
        "reason": "OK",
        "day_change_pct": round(float(day_chg), 4) if day_chg is not None else None,
        "last_bar_drop_pct": round(float(last_bar_drop), 4),
    }


def get_regime(
    api: TradingAPI,
    asof: str,
    *,
    primary_code: str = "069500",
    confirmation_code: str = "229200",
    use_confirmation: bool = False,
    last_panic_date: str | None = None,
    vol_threshold: float = 0.05,
) -> tuple[str, str | None]:
    """
    Returns (regime_string, detected_panic_date)
    """
    # 0. ✅ 쿨다운 체크
    if _is_in_cooldown(asof, last_panic_date, days=3):
        return "RISK_OFF", None

    # 1. Primary 로직
    primary_regime, primary_panic_date = _single_regime(api, asof, primary_code, vol_threshold)
    
    if not use_confirmation:
        return primary_regime, primary_panic_date

    # 2. Confirmation 로직
    confirm_regime, confirm_panic_date = _single_regime(api, asof, confirmation_code, vol_threshold)
    detected_panic_date = max(
        [d for d in (primary_panic_date, confirm_panic_date) if d is not None],
        default=None,
    )
    
    if primary_regime == "RISK_OFF" or confirm_regime == "RISK_OFF":
        return "RISK_OFF", detected_panic_date
    if primary_regime == "RISK_ON" and confirm_regime == "RISK_ON":
        return "RISK_ON", detected_panic_date
        
    return "NEUTRAL", detected_panic_date


def _normalize_yyyymmdd(text: str) -> str:
    if not text:
        return text
    raw = str(text).strip()
    if "-" in raw:
        raw = raw.replace("-", "")
    return raw[:8]


def _sort_intraday_bars(bars: pd.DataFrame) -> pd.DataFrame:
    if bars is None or bars.empty:
        return bars

    view = bars.copy()
    if "timestamp" in view.columns:
        return view.sort_values("timestamp", ascending=True)

    if "date" in view.columns and "time" in view.columns:
        key = view["date"].astype(str) + view["time"].astype(str).str.zfill(6)
        return view.assign(_k=key).sort_values("_k", ascending=True).drop(columns=["_k"])

    if "date" in view.columns:
        return view.sort_values("date", ascending=True)

    return view.sort_index(ascending=True)


def _resolve_day_change_pct(api: TradingAPI, code: str, bars: pd.DataFrame) -> float | None:
    if "change_pct" in bars.columns:
        cp = pd.to_numeric(bars["change_pct"], errors="coerce").dropna()
        if not cp.empty:
            return float(cp.iloc[-1])

    quote_fn = getattr(api, "quote", None)
    if callable(quote_fn):
        try:
            q = quote_fn(code)
            return parse_numeric(q.get("change_pct"))
        except Exception:
            return None
    return None
