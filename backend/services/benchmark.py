from __future__ import annotations

from bisect import bisect_right
from datetime import date, datetime, timedelta
from pathlib import Path
import logging

import requests
import yaml

logger = logging.getLogger(__name__)

DEFAULT_BENCHMARK_NAME = "SPY TR"
DEFAULT_BENCHMARK_EXCHANGE = "AMS"
DEFAULT_BENCHMARK_SYMBOL = "SPY"
DEFAULT_PRODUCT_TYPE = "529"


def _parse_number(value: str | float | int | None) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def _load_kis_config() -> dict:
    cfg_path = Path.home() / "KIS" / "config" / "kis_user.yaml"
    if not cfg_path.exists():
        raise RuntimeError("kis_user.yaml not found in ~/KIS/config")
    return yaml.safe_load(cfg_path.read_text(encoding="utf-8"))


def _load_kis_token() -> str:
    config_dir = Path.home() / "KIS" / "config"
    candidates = sorted(config_dir.glob("KIS20*"), reverse=True)
    now = datetime.now()
    for path in candidates:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        token = data.get("token")
        valid = data.get("valid-date")
        if token and valid and valid > now:
            return token
    raise RuntimeError("No valid KIS token file found")


def _kis_get(cfg: dict, token: str, api_url: str, tr_id: str, params: dict) -> dict:
    headers = {
        "content-type": "application/json",
        "accept": "text/plain",
        "authorization": f"Bearer {token}",
        "appkey": cfg["my_app"],
        "appsecret": cfg["my_sec"],
        "tr_id": tr_id,
        "custtype": "P",
    }
    url = f"{cfg['prod']}{api_url}"
    res = requests.get(url, headers=headers, params=params, timeout=15)
    res.raise_for_status()
    body = res.json()
    if body.get("rt_cd") != "0":
        raise RuntimeError(body.get("msg1") or "KIS API error")
    return body


def _fetch_overseas_prices(
    cfg: dict,
    token: str,
    exchange: str,
    symbol: str,
    start_date: date,
    end_date: date,
) -> dict[date, float]:
    api_url = "/uapi/overseas-price/v1/quotations/dailyprice"
    prices: dict[date, float] = {}
    current = end_date
    seen: set[date] = set()

    while True:
        params = {
            "AUTH": "",
            "EXCD": exchange,
            "SYMB": symbol,
            "GUBN": "0",
            "BYMD": current.strftime("%Y%m%d"),
            "MODP": "1",
        }
        body = _kis_get(cfg, token, api_url, "HHDFS76240000", params)
        output = body.get("output2") or []
        if not output:
            break

        batch_dates: list[date] = []
        for row in output:
            raw_date = row.get("xymd")
            raw_close = row.get("clos")
            if not raw_date or not raw_close:
                continue
            try:
                d = datetime.strptime(raw_date, "%Y%m%d").date()
            except ValueError:
                continue
            close = _parse_number(raw_close)
            if close is None:
                continue
            prices[d] = close
            batch_dates.append(d)

        if not batch_dates:
            break

        earliest = min(batch_dates)
        if earliest <= start_date:
            break

        next_day = earliest - timedelta(days=1)
        if next_day in seen:
            break
        seen.add(next_day)
        current = next_day

    return {d: v for d, v in prices.items() if start_date <= d <= end_date}


def _fetch_overseas_dividends(
    cfg: dict,
    token: str,
    symbol: str,
    start_date: date,
    end_date: date,
) -> list[tuple[date, float]]:
    api_url = "/uapi/overseas-price/v1/quotations/period-rights"
    params = {
        "RGHT_TYPE_CD": "03",
        "INQR_DVSN_CD": "02",
        "INQR_STRT_DT": start_date.strftime("%Y%m%d"),
        "INQR_END_DT": end_date.strftime("%Y%m%d"),
        "PDNO": symbol,
        "PRDT_TYPE_CD": DEFAULT_PRODUCT_TYPE,
        "CTX_AREA_NK50": "",
        "CTX_AREA_FK50": "",
    }
    dividends: list[tuple[date, float]] = []

    while True:
        body = _kis_get(cfg, token, api_url, "CTRGT011R", params)
        output = body.get("output") or []
        for row in output:
            if row.get("pdno") != symbol:
                continue
            raw_date = row.get("bass_dt")
            raw_div = row.get("alct_frcr_unpr")
            if not raw_date or not raw_div:
                continue
            try:
                d = datetime.strptime(raw_date, "%Y%m%d").date()
            except ValueError:
                continue
            div = _parse_number(raw_div)
            if div is None:
                continue
            dividends.append((d, div))

        tr_cont = body.get("tr_cont") or ""
        if tr_cont not in ("M", "F"):
            break
        params["CTX_AREA_NK50"] = body.get("ctx_area_nk50") or ""
        params["CTX_AREA_FK50"] = body.get("ctx_area_fk50") or ""

    return sorted(dividends, key=lambda x: x[0])


def _price_on_or_before(prices: dict[date, float], target: date) -> float | None:
    if not prices:
        return None
    dates = sorted(prices.keys())
    idx = bisect_right(dates, target)
    if idx == 0:
        return None
    return prices[dates[idx - 1]]


def compute_total_return(
    start_date: date,
    end_date: date,
) -> float:
    cfg = _load_kis_config()
    token = _load_kis_token()

    prices = _fetch_overseas_prices(
        cfg,
        token,
        DEFAULT_BENCHMARK_EXCHANGE,
        DEFAULT_BENCHMARK_SYMBOL,
        start_date,
        end_date,
    )
    if not prices:
        raise RuntimeError("No benchmark prices fetched")

    start_price = _price_on_or_before(prices, start_date)
    end_price = _price_on_or_before(prices, end_date)
    if start_price is None or end_price is None:
        raise RuntimeError("Missing benchmark price for start/end date")

    dividends = _fetch_overseas_dividends(
        cfg,
        token,
        DEFAULT_BENCHMARK_SYMBOL,
        start_date,
        end_date,
    )

    units = 1.0
    for d, div in dividends:
        price = _price_on_or_before(prices, d)
        if price is None:
            continue
        units += units * div / price

    end_value = units * end_price
    total_return = (end_value / start_price - 1) * 100
    logger.info(
        "Benchmark TR computed: start=%s end=%s return=%.4f%%",
        start_date,
        end_date,
        total_return,
    )
    return total_return


def compute_calendar_year_total_return(
    today: date | None = None,
) -> tuple[str, float, bool]:
    today = today or date.today()
    start_date = date(today.year, 1, 1)
    year_end = date(today.year, 12, 31)
    end_date = today if today < year_end else year_end

    total_return = compute_total_return(start_date, end_date)
    is_partial = end_date != year_end
    label = f"{DEFAULT_BENCHMARK_NAME} {today.year}"
    if is_partial:
        label = f"{label} (YTD)"
    return label, total_return, is_partial
