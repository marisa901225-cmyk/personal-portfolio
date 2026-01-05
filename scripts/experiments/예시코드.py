from __future__ import annotations

from bisect import bisect_right
from datetime import date, datetime, timedelta
from pathlib import Path
import json
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

import requests
import yaml

ROOT = Path(__file__).resolve().parents[2]
XLSX_PATH = ROOT / "combined_statements_valuation.xlsx"


def _load_shared_strings(xlsx_path: Path) -> list[str]:
    with zipfile.ZipFile(xlsx_path) as zf:
        shared = zf.read("xl/sharedStrings.xml")
    root = ET.fromstring(shared)
    ns = {"ss": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    strings: list[str] = []
    for si in root.findall("ss:si", ns):
        texts = []
        for t in si.findall(".//ss:t", ns):
            texts.append(t.text or "")
        strings.append("".join(texts))
    return strings


def _sheet_name_to_path(xlsx_path: Path) -> dict[str, str]:
    with zipfile.ZipFile(xlsx_path) as zf:
        wb = ET.fromstring(zf.read("xl/workbook.xml"))
        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rels_map = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in rels.findall("{http://schemas.openxmlformats.org/package/2006/relationships}Relationship")
    }
    ns = {"ss": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    mapping: dict[str, str] = {}
    for sheet in wb.findall("ss:sheets/ss:sheet", ns):
        name = sheet.attrib.get("name")
        rid = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        target = rels_map.get(rid or "")
        if name and target:
            mapping[name] = f"xl/{target}"
    return mapping


def _col_to_index(col: str) -> int:
    idx = 0
    for ch in col:
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx - 1


def _iter_rows(xlsx_path: Path, sheet_path: str, shared_strings: list[str]):
    ns = {"ss": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(xlsx_path) as zf:
        data = zf.read(sheet_path)
    root = ET.fromstring(data)
    for row in root.findall("ss:sheetData/ss:row", ns):
        row_vals: dict[int, str] = {}
        for cell in row.findall("ss:c", ns):
            ref = cell.attrib.get("r")
            cell_type = cell.attrib.get("t")
            value_node = cell.find("ss:v", ns)
            if ref is None or value_node is None:
                continue
            col = re.match(r"[A-Z]+", ref)
            if not col:
                continue
            col_idx = _col_to_index(col.group(0))
            raw = value_node.text or ""
            if cell_type == "s":
                try:
                    val = shared_strings[int(raw)]
                except Exception:
                    val = raw
            else:
                val = raw
            row_vals[col_idx] = val
        if row_vals:
            max_col = max(row_vals.keys())
            yield [row_vals.get(i, "") for i in range(max_col + 1)]


def _parse_number(value: str | float | int | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    text = text.replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def _excel_serial_to_date(value: str | float | int | None) -> date | None:
    num = _parse_number(value)
    if num is None:
        return None
    base = datetime(1899, 12, 30)
    return (base + timedelta(days=num)).date()


def _load_cashflows(xlsx_path: Path) -> list[tuple[date, float]]:
    shared_strings = _load_shared_strings(xlsx_path)
    sheet_map = _sheet_name_to_path(xlsx_path)
    sheet_path = sheet_map.get("Cashflows_For_XIRR")
    if not sheet_path:
        raise RuntimeError("Cashflows_For_XIRR sheet not found")

    rows = _iter_rows(xlsx_path, sheet_path, shared_strings)
    header = next(rows)
    header_map = {name: idx for idx, name in enumerate(header)}
    date_idx = header_map.get("거래일자")
    amount_idx = header_map.get("현금흐름")
    if date_idx is None or amount_idx is None:
        raise RuntimeError("Missing 거래일자 or 현금흐름 column")

    flows: list[tuple[date, float]] = []
    for row in rows:
        raw_date = row[date_idx] if date_idx < len(row) else ""
        raw_amount = row[amount_idx] if amount_idx < len(row) else ""
        d = _excel_serial_to_date(raw_date)
        amt = _parse_number(raw_amount)
        if d is None or amt is None or amt == 0:
            continue
        flows.append((d, amt))
    return flows


def _load_eval_value(xlsx_path: Path) -> tuple[date, float]:
    shared_strings = _load_shared_strings(xlsx_path)
    sheet_map = _sheet_name_to_path(xlsx_path)

    inputs_path = sheet_map.get("Inputs")
    perf_path = sheet_map.get("Performance")
    if not inputs_path or not perf_path:
        raise RuntimeError("Inputs or Performance sheet not found")

    eval_date = None
    eval_value = None

    for row in _iter_rows(xlsx_path, inputs_path, shared_strings):
        if len(row) >= 2 and str(row[0]).strip() == "평가기준일":
            eval_date = _excel_serial_to_date(row[1])
        if len(row) >= 2 and str(row[0]).strip() == "평가금액(총합,원) - 입력":
            eval_value = _parse_number(row[1])

    for row in _iter_rows(xlsx_path, perf_path, shared_strings):
        if len(row) >= 2 and str(row[0]).strip() == "평가금액(입력)":
            eval_value = _parse_number(row[1])

    if eval_date is None or eval_value is None:
        raise RuntimeError("Evaluation date/value not found")

    return eval_date, eval_value


def _xirr(flows: list[tuple[date, float]]) -> float | None:
    if not flows:
        return None
    flows = sorted(flows, key=lambda x: x[0])
    t0 = flows[0][0]
    days = [(d - t0).days for d, _ in flows]
    amounts = [amt for _, amt in flows]

    def f(rate: float) -> float:
        total = 0.0
        for delta, amt in zip(days, amounts):
            total += amt / ((1 + rate) ** (delta / 365.0))
        return total

    def fprime(rate: float) -> float:
        total = 0.0
        for delta, amt in zip(days, amounts):
            total += -(delta / 365.0) * amt / ((1 + rate) ** (delta / 365.0 + 1))
        return total

    for guess in (0.1, 0.2, 0.05, 0.0, 0.3, -0.1, 0.5):
        rate = guess
        for _ in range(100):
            y = f(rate)
            dy = fprime(rate)
            if dy == 0:
                break
            new_rate = rate - y / dy
            if abs(new_rate - rate) < 1e-10:
                return new_rate
            rate = new_rate

    low, high = -0.9999, 10.0
    f_low, f_high = f(low), f(high)
    if f_low * f_high > 0:
        return None
    for _ in range(200):
        mid = (low + high) / 2
        f_mid = f(mid)
        if abs(f_mid) < 1e-10:
            return mid
        if f_low * f_mid < 0:
            high = mid
            f_high = f_mid
        else:
            low = mid
            f_low = f_mid
    return (low + high) / 2


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
    res = requests.get(url, headers=headers, params=params)
    res.raise_for_status()
    body = res.json()
    if body.get("rt_cd") != "0":
        raise RuntimeError(body.get("msg1") or "KIS API error")
    return body


def _fetch_spy_prices(cfg: dict, token: str, start_date: date, end_date: date) -> dict[date, float]:
    api_url = "/uapi/overseas-price/v1/quotations/dailyprice"
    prices: dict[date, float] = {}
    current = end_date
    seen: set[date] = set()

    while True:
        params = {
            "AUTH": "",
            "EXCD": "AMS",
            "SYMB": "SPY",
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


def _fetch_spy_dividends(cfg: dict, token: str, start_date: date, end_date: date) -> list[tuple[date, float]]:
    api_url = "/uapi/overseas-price/v1/quotations/period-rights"
    params = {
        "RGHT_TYPE_CD": "03",
        "INQR_DVSN_CD": "02",
        "INQR_STRT_DT": start_date.strftime("%Y%m%d"),
        "INQR_END_DT": end_date.strftime("%Y%m%d"),
        "PDNO": "SPY",
        "PRDT_TYPE_CD": "529",
        "CTX_AREA_NK50": "",
        "CTX_AREA_FK50": "",
    }
    dividends: list[tuple[date, float]] = []

    tr_cont = ""
    while True:
        body = _kis_get(cfg, token, api_url, "CTRGT011R", params)
        output = body.get("output") or []
        for row in output:
            if row.get("pdno") != "SPY":
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
        nk50 = body.get("ctx_area_nk50") or ""
        fk50 = body.get("ctx_area_fk50") or ""
        if tr_cont not in ("M", "F"):
            break
        params["CTX_AREA_NK50"] = nk50
        params["CTX_AREA_FK50"] = fk50

    return sorted(dividends, key=lambda x: x[0])


def _price_on_or_before(prices: dict[date, float], d: date) -> float | None:
    if not prices:
        return None
    dates = sorted(prices.keys())
    idx = bisect_right(dates, d)
    if idx == 0:
        return None
    return prices[dates[idx - 1]]


def main() -> int:
    if not XLSX_PATH.exists():
        print(f"Missing input file: {XLSX_PATH}")
        return 1

    flows = _load_cashflows(XLSX_PATH)
    eval_date, eval_value = _load_eval_value(XLSX_PATH)
    if not flows:
        print("No cashflows found.")
        return 1

    # Remove the final evaluation value entry from flows
    flows_sorted = sorted(flows, key=lambda x: x[0])
    flows_wo_value = flows_sorted.copy()
    removed = False
    for i, (d, amt) in enumerate(flows_wo_value):
        if d == eval_date and abs(amt - eval_value) < 1e-6:
            flows_wo_value.pop(i)
            removed = True
            break
    if not removed:
        print("Evaluation cashflow not found in Cashflows_For_XIRR.")
        return 1

    portfolio_xirr = _xirr(flows_sorted)
    if portfolio_xirr is None:
        print("Failed to compute portfolio XIRR.")
        return 1

    start_date = min(d for d, _ in flows_wo_value)

    cfg = _load_kis_config()
    token = _load_kis_token()

    prices = _fetch_spy_prices(cfg, token, start_date, eval_date)
    if not prices:
        print("No SPY prices fetched.")
        return 1

    dividends = _fetch_spy_dividends(cfg, token, start_date, eval_date)

    events: list[tuple[date, str, float]] = []
    for d, amt in flows_wo_value:
        events.append((d, "cash", amt))
    for d, div in dividends:
        events.append((d, "div", div))
    events.sort(key=lambda x: (x[0], 0 if x[1] == "cash" else 1))

    units = 0.0
    missing = 0
    for d, kind, value in events:
        price = _price_on_or_before(prices, d)
        if price is None:
            missing += 1
            continue
        if kind == "cash":
            units += -value / price
        else:
            units += units * value / price

    eval_price = _price_on_or_before(prices, eval_date)
    if eval_price is None:
        print("Missing SPY price for evaluation date.")
        return 1

    bench_value = units * eval_price
    bench_xirr = _xirr(flows_wo_value + [(eval_date, bench_value)])
    if bench_xirr is None:
        print("Failed to compute benchmark XIRR.")
        return 1

    print("=== SPY Total Return (dividend reinvest) benchmark ===")
    print(f"eval_date: {eval_date}")
    print(f"portfolio_xirr: {portfolio_xirr:.6%}")
    print(f"spy_tr_xirr: {bench_xirr:.6%}")
    print(f"spy_tr_value: {bench_value:,.0f}")
    if missing > 0:
        print(f"warning: {missing} events skipped due to missing price data")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
