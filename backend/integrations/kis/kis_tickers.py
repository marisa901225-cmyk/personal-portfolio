from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, TYPE_CHECKING

from . import kis_client as core

if TYPE_CHECKING:
    import pandas as pd  # noqa: F401
else:
    pd = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


def _require_pandas() -> None:
    global pd
    if pd is not None:
        return
    try:
        import pandas as _pd  # type: ignore
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "pandas is required for KIS ticker search (master excel parsing). "
            "Install backend requirements or disable KIS via KIS_ENABLED=0."
        ) from exc
    pd = _pd


@lru_cache
def _load_domestic_master() -> pd.DataFrame:
    """
    코스피/코스닥/코넥스 종목 마스터 엑셀을 로드한다.

    - open-trading-api/stocks_info 디렉터리에서
      kis_kospi_code_mst.py, kis_kosdaq_code_mst.py 등을 실행해
      kospi_code.xlsx, kosdaq_code.xlsx 등이 생성되어 있어야 한다.
    """
    _require_pandas()
    base = core._stocks_info_dir()

    preferred_files = [
        base / "kospi_code.xlsx",
        base / "kosdaq_code.xlsx",
        base / "konex_code.xlsx",
    ]

    excel_paths: List[Path] = []
    for p in preferred_files:
        if p.exists():
            excel_paths.append(p)
    for p in base.glob("*.xlsx"):
        if p not in excel_paths:
            excel_paths.append(p)

    frames: List[pd.DataFrame] = []
    for path in excel_paths:
        try:
            xls = pd.ExcelFile(path)  # type: ignore[union-attr]
        except Exception as exc:  # pragma: no cover
            logger.warning("국내 마스터 엑셀 열기 실패: %s (%s)", path, exc)
            continue

        for sheet in xls.sheet_names:
            try:
                df_sheet = xls.parse(sheet)
            except Exception as exc:  # pragma: no cover
                logger.warning("국내 마스터 시트 로드 실패: %s [%s] (%s)", path, sheet, exc)
                continue

            cols = set(df_sheet.columns)
            if "단축코드" not in cols:
                continue

            if not any(c in cols for c in ("한글명", "한글종목명", "종목명")):
                continue

            frames.append(df_sheet)

    if not frames:
        raise RuntimeError(
            "국내 종목 마스터 파일을 찾을 수 없습니다. "
            "open-trading-api/stocks_info 디렉터리에 "
            "kospi/kosdaq/konex 마스터 엑셀 파일을 위치시켜 주세요."
        )

    df = pd.concat(frames, ignore_index=True)  # type: ignore[union-attr]

    code_col = None
    for c in ("단축코드",):
        if c in df.columns:
            code_col = c
            break

    name_candidates = [c for c in ("한글명", "한글종목명", "종목명") if c in df.columns]

    if not code_col or not name_candidates:
        raise RuntimeError("국내 마스터 파일에서 코드/이름 컬럼을 찾지 못했습니다.")

    # 여러 이름 컬럼이 있는 경우(예: 한글명, 한글종목명)를 한 컬럼으로 통합
    name_series = df[name_candidates[0]].astype(str)
    for col in name_candidates[1:]:
        other = df[col].astype(str)
        name_series = name_series.where(
            name_series.str.strip().ne(""), other
        )

    result = df[[code_col]].copy()
    result["name"] = name_series
    return result.rename(columns={code_col: "code"})


@lru_cache
def _load_overseas_master() -> pd.DataFrame:
    """
    해외 종목 마스터 엑셀을 로드한다.

    - open-trading-api/stocks_info/overseas_stock_code(all).xlsx 필요
      (overseas_stock_code.py 실행 시 생성)
    """
    _require_pandas()
    base = core._stocks_info_dir()
    path = base / "overseas_stock_code(all).xlsx"
    if not path.exists():
        raise RuntimeError(
            "해외 종목 마스터 파일을 찾을 수 없습니다. "
            "open-trading-api/stocks_info 디렉터리에서 overseas_stock_code.py를 실행해 "
            "overseas_stock_code(all).xlsx 파일을 생성해주세요."
        )

    try:
        xls = pd.ExcelFile(path)  # type: ignore[union-attr]
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(f"해외 종목 마스터 파일 로드 실패: {exc}") from exc

    # 파일 안에 여러 시트가 있을 수 있으므로,
    # KOSPI/KOSDAQ/해외 시트를 모두 합쳐 하나의 DataFrame으로 사용한다.
    required = ["Exchange code", "Symbol", "Korea name", "English name", "currency"]
    frames: List[pd.DataFrame] = []

    for sheet in xls.sheet_names:
        try:
            df_sheet = xls.parse(sheet)
        except Exception as exc:  # pragma: no cover
            logger.warning("해외 마스터 시트 로드 실패: %s [%s] (%s)", path, sheet, exc)
            continue

        if not all(col in df_sheet.columns for col in required):
            # 우리가 기대하는 종목 마스터 포맷이 아닌 시트는 건너뛴다.
            continue

        frames.append(df_sheet)

    if not frames:
        raise RuntimeError("해외 마스터 파일 컬럼 구성이 예상과 다릅니다.")

    return pd.concat(frames, ignore_index=True)  # type: ignore[union-attr]


def search_tickers_by_name(query: str, limit: int = 5) -> list[Dict[str, str | None]]:
    """
    종목명(한글/영문)으로 국내/해외 종목을 검색한다.

    - 국내: KOSPI/KOSDAQ/코넥스 마스터(엑셀) 기반
    - 해외: 해외 종목 마스터(엑셀) 기반
    """
    q = (query or "").strip()
    if not q:
        return []

    results: list[Dict[str, str | None]] = []

    # 국내
    try:
        df_dom = _load_domestic_master()
    except RuntimeError as exc:
        logger.warning("국내 마스터 사용 불가: %s", exc)
        df_dom = None

    if df_dom is not None:
        mask = df_dom["name"].astype(str).str.contains(q, case=False, na=False)
        for _, row in df_dom[mask].head(limit).iterrows():
            code = str(row["code"]).zfill(6)
            name = str(row["name"])
            results.append(
                {
                    "symbol": code,
                    "name": name,
                    "exchange": "KRX",
                    "currency": "KRW",
                    "type": "DOMESTIC",
                }
            )

    # 해외 (국내 결과가 충분하면 굳이 더 찾지 않아도 됨)
    remaining = max(limit - len(results), 0)
    if remaining > 0:
        try:
            df_ov = _load_overseas_master()
        except RuntimeError as exc:
            logger.warning("해외 마스터 사용 불가: %s", exc)
            df_ov = None

        if df_ov is not None:
            # 한글/영문명 모두에서 검색
            name_kr = df_ov["Korea name"].astype(str)
            name_en = df_ov["English name"].astype(str)
            mask = name_kr.str.contains(q, case=False, na=False) | name_en.str.contains(
                q, case=False, na=False
            )
            for _, row in df_ov[mask].head(remaining).iterrows():
                exch_code = str(row["Exchange code"]).upper()
                sym = str(row["Symbol"]).upper()
                name = row["Korea name"] or row["English name"] or sym
                currency = (row.get("currency") or "").upper() or "USD"

                # 일부 환경에서는 KOSPI/KOSDAQ 종목이 overseas_stock_code(all).xlsx 안의
                # 별도 시트로 포함되어 있을 수 있다.
                # - Symbol: 6자리 숫자
                # - Exchange code: 국내 거래소 계열
                # 이런 경우는 국내 종목으로 간주하여, 포트폴리오에서 바로 사용할 수 있는
                # 6자리 종목코드 포맷으로 반환한다.
                is_domestic_from_overseas_master = (
                    sym.isdigit()
                    and len(sym) == 6
                    and exch_code in {"KOSPI", "KOSDAQ", "KONEX", "KRX"}
                )

                if is_domestic_from_overseas_master:
                    symbol = sym.zfill(6)
                    results.append(
                        {
                            "symbol": symbol,
                            "name": str(name),
                            "exchange": "KRX",
                            "currency": "KRW",
                            "type": "DOMESTIC",
                        }
                    )
                else:
                    symbol = f"{exch_code}:{sym}"
                    results.append(
                        {
                            "symbol": symbol,
                            "name": str(name),
                            "exchange": exch_code,
                            "currency": currency,
                            "type": "OVERSEAS",
                        }
                    )

    return results


def search_tickers(query: str) -> list[Dict[str, str | None]]:
    """
    KIS 기준으로 티커/종목코드 정보를 해석한다.

    - 입력 예시:
        - 국내: "005930"
        - 해외: "AAPL", "NAS:AAPL", "NYS:KO"
    - 반환: [{symbol, name, exchange, currency, type}]
      * symbol: 포트폴리오에서 사용할 최종 티커 문자열 (예: 005930, NAS:AAPL)
    """
    q = (query or "").strip()
    if not q:
        return []

    core._ensure_auth()

    results: list[Dict[str, str | None]] = []

    # 1) 국내 6자리 코드 또는 ETN (Q로 시작)
    if core._DOMESTIC_TICKER_RE.match(q) or (
        len(q) == 7 and q[0].upper() == "Q" and q[1:].isdigit()
    ):
        try:
            df = core._domestic_search_stock_info("300", q)  # type: ignore[misc]
        except Exception as exc:  # pragma: no cover - 외부 API 예외
            logger.warning("국내 종목 기본정보 조회 실패 q=%s error=%s", q, exc)
            df = None

        if df is not None and not df.empty:
            row = df.iloc[0]
            name = (
                row.get("prdt_name")
                or row.get("prdt_name120")
                or row.get("prdt_eng_name")
                or q
            )
            results.append(
                {
                    "symbol": q,
                    "name": str(name),
                    "exchange": "KRX",
                    "currency": "KRW",
                    "type": "DOMESTIC",
                }
            )
            return results

    # 2) 해외 티커 처리
    ex_code: str | None = None
    sym: str | None = None

    if ":" in q:
        left, right = q.split(":", 1)
        ex_code = left.strip().upper() or None
        sym = right.strip().upper() or None
    else:
        sym = q.upper()

    # EXCD ↔ 상품유형 코드 맵핑 (미국 3개 시장 우선)
    ex_to_prdt = {
        "NAS": "512",  # 미국 나스닥
        "NYS": "513",  # 미국 뉴욕
        "AMS": "529",  # 미국 아멕스
    }

    candidates: list[tuple[str, str]] = []
    if ex_code and sym:
        prdt = ex_to_prdt.get(ex_code)
        if prdt:
            candidates.append((prdt, ex_code))
    elif sym:
        # 거래소 미지정인 경우: 나스닥 → 뉴욕 → 아멕스 순으로 시도
        candidates = [("512", "NAS"), ("513", "NYS"), ("529", "AMS")]

    for prdt_type_cd, exch in candidates:
        if not sym:
            break
        try:
            df = core._overseas_search_info(  # type: ignore[misc]
                prdt_type_cd=prdt_type_cd,
                pdno=sym,
            )
        except Exception as exc:  # pragma: no cover
            logger.warning(
                "해외 상품 기본정보 조회 실패 q=%s prdt_type_cd=%s error=%s",
                q,
                prdt_type_cd,
                exc,
            )
            continue

        if df is None or df.empty:
            continue

        row = df.iloc[0]
        name = (
            row.get("prdt_eng_name")
            or row.get("ovrs_item_name")
            or row.get("prdt_name")
            or sym
        )

        symbol = f"{exch}:{sym}"
        results.append(
            {
                "symbol": symbol,
                "name": str(name),
                "exchange": exch,
                "currency": "USD",
                "type": "OVERSEAS",
            }
        )
        break

    return results
