from __future__ import annotations

import base64
import json
import logging
import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeAlias

import pandas as pd

from ..llm.service import LLMService
from ..prompt_loader import load_prompt
from .candidate_scoring import _day_intraday_structure_score, _resolve_change_pct
from .chart_review_renderer import render_candidate_chart_png
from .config import TradeEngineConfig
from .interfaces import TradingAPI
from .intraday import sort_intraday_bars
from .types import Quote, QuoteMap
from .utils import parse_numeric

if TYPE_CHECKING:
    from .strategy import Candidates

logger = logging.getLogger(__name__)

ReviewPayload: TypeAlias = dict[str, object]
ReviewMessage: TypeAlias = dict[str, object]

_REVIEW_MAX_TOKENS = 700
_CHART_REVIEW_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "day_chart_review",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "selected_code": {"type": ["string", "null"]},
                "summary": {"type": "string"},
                "candidates": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "code": {"type": "string"},
                            "decision": {
                                "type": "string",
                                "enum": ["ENTER", "PASS", "UNSURE"],
                            },
                            "reason": {"type": "string"},
                            "confidence": {
                                "type": "number",
                                "minimum": 0.0,
                                "maximum": 1.0,
                            },
                        },
                        "required": ["code", "decision", "reason", "confidence"],
                    },
                },
            },
            "required": ["selected_code", "summary", "candidates"],
        },
    },
}


@dataclass(slots=True)
class DayChartReviewResult:
    shortlisted_codes: list[str]
    approved_codes: list[str]
    selected_code: str | None
    summary: str
    chart_paths: list[str]
    raw_response: ReviewPayload | None = None


@dataclass(slots=True)
class _ReviewAsset:
    code: str
    meta_text: str
    chart_path: str


def review_day_candidates_with_llm(
    *,
    api: TradingAPI,
    trade_date: str,
    ranked_codes: list[str],
    candidates: Candidates,
    quotes: QuoteMap,
    config: TradeEngineConfig,
    output_dir: str,
) -> DayChartReviewResult | None:
    if not getattr(config, "day_chart_review_enabled", False):
        return None
    shortlist = _build_day_shortlist(
        ranked_codes=ranked_codes,
        quotes=quotes,
        config=config,
    )
    if not shortlist:
        return None

    llm = LLMService.get_instance()
    if not llm.settings.is_remote_configured() and not llm.settings.is_paid_configured():
        return None

    chart_dir = os.path.join(output_dir, "day_chart_review")
    os.makedirs(chart_dir, exist_ok=True)

    reviewed_shortlist: list[str] = []
    assets: list[_ReviewAsset] = []
    for rank, code in enumerate(shortlist, start=1):
        row = _find_candidate_row(candidates, code)
        daily_bars = _safe_daily_bars(api, code=code, trade_date=trade_date, lookback=80)
        intraday_bars = _safe_intraday_bars(api, code=code, trade_date=trade_date, lookback=80)
        if (daily_bars is None or daily_bars.empty) and (intraday_bars is None or intraday_bars.empty):
            continue

        chart_path = os.path.join(chart_dir, f"{trade_date}_{rank}_{code}.png")
        render_candidate_chart_png(
            path=chart_path,
            code=code,
            daily_bars=daily_bars,
            intraday_bars=intraday_bars,
        )
        reviewed_shortlist.append(code)
        quote = quotes.get(str(code), {})
        assets.append(
            _ReviewAsset(
                code=code,
                meta_text=_candidate_meta_text(rank=rank, code=code, row=row, quote=quote),
                chart_path=chart_path,
            )
        )

    if not assets:
        return None

    return _run_chart_review_hybrid(
        llm=llm,
        assets=assets,
        header_text=(
            f"거래일: {trade_date}\n"
            f"후보 수: {len(assets)}\n"
            "각 후보에 대해 ENTER/PASS/UNSURE를 주고, selected_code는 가장 나은 1개만 선택해줘."
        ),
        system_prompt_name="trading_day_chart_review_system",
        paid_min_candidates=max(2, int(getattr(config, "day_chart_review_paid_min_candidates", 2))),
        paid_model=str(config.day_chart_review_model or "gpt-5.5"),
        paid_reasoning_effort=str(config.day_chart_review_reasoning_effort or "high"),
    )


def review_swing_candidates_with_llm(
    *,
    api: TradingAPI,
    trade_date: str,
    ranked_codes: list[str],
    candidates: Candidates,
    quotes: QuoteMap,
    config: TradeEngineConfig,
    output_dir: str,
) -> DayChartReviewResult | None:
    if not getattr(config, "swing_chart_review_enabled", False):
        return None
    shortlist = _build_shortlist(ranked_codes, max_count=max(1, int(config.swing_chart_review_top_n)))
    if not shortlist:
        return None

    llm = LLMService.get_instance()
    if not llm.settings.is_remote_configured() and not llm.settings.is_paid_configured():
        return None

    chart_dir = os.path.join(output_dir, "swing_chart_review")
    os.makedirs(chart_dir, exist_ok=True)

    reviewed_shortlist: list[str] = []
    assets: list[_ReviewAsset] = []
    for rank, code in enumerate(shortlist, start=1):
        row = _find_candidate_row(candidates, code)
        daily_bars = _safe_daily_bars(api, code=code, trade_date=trade_date, lookback=90)
        if daily_bars is None or daily_bars.empty:
            continue

        recent_zoom = daily_bars.tail(24).copy()
        chart_path = os.path.join(chart_dir, f"{trade_date}_{rank}_{code}.png")
        render_candidate_chart_png(
            path=chart_path,
            code=code,
            daily_bars=daily_bars,
            intraday_bars=recent_zoom,
        )
        reviewed_shortlist.append(code)
        quote = quotes.get(str(code), {})
        assets.append(
            _ReviewAsset(
                code=code,
                meta_text=_candidate_meta_text(rank=rank, code=code, row=row, quote=quote),
                chart_path=chart_path,
            )
        )

    if not assets:
        return None

    return _run_chart_review_hybrid(
        llm=llm,
        assets=assets,
        header_text=(
            f"거래일: {trade_date}\n"
            f"후보 수: {len(assets)}\n"
            "각 후보에 대해 ENTER/PASS/UNSURE를 주고, 스윙 관점에서 가장 나은 1개만 selected_code로 골라줘."
        ),
        system_prompt_name="trading_swing_chart_review_system",
        paid_min_candidates=max(2, int(getattr(config, "swing_chart_review_paid_min_candidates", 2))),
        paid_model=str(config.swing_chart_review_model or "gpt-5.5"),
        paid_reasoning_effort=str(config.swing_chart_review_reasoning_effort or "high"),
    )


def _build_shortlist(ranked_codes: list[str], *, max_count: int) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for code in ranked_codes:
        code_str = str(code or "").strip()
        if not code_str or code_str in seen:
            continue
        seen.add(code_str)
        ordered.append(code_str)
        if len(ordered) >= max_count:
            break
    return ordered


def _build_day_shortlist(
    *,
    ranked_codes: list[str],
    quotes: QuoteMap,
    config: TradeEngineConfig,
) -> list[str]:
    base_count = max(1, int(config.day_chart_review_top_n))
    shortlist = _build_shortlist(ranked_codes, max_count=base_count)

    wildcard_slots = max(0, int(getattr(config, "day_chart_review_chart_wildcard_slots", 0)))
    if wildcard_slots <= 0:
        return shortlist

    shortlisted_codes = set(shortlist)
    remaining_seen: set[str] = set()
    chart_scored_remaining: list[tuple[float, int, str]] = []
    for rank_index, code in enumerate(ranked_codes):
        code_str = str(code or "").strip()
        if not code_str or code_str in shortlisted_codes or code_str in remaining_seen:
            continue
        remaining_seen.add(code_str)
        quote = quotes.get(code_str, {})
        chart_score = float(_day_intraday_structure_score(quote))
        chart_scored_remaining.append((chart_score, rank_index, code_str))

    if not chart_scored_remaining:
        return shortlist

    chart_scored_remaining.sort(key=lambda item: (-item[0], item[1], item[2]))
    extended = list(shortlist)
    for _, _, code_str in chart_scored_remaining[:wildcard_slots]:
        if code_str in shortlisted_codes:
            continue
        extended.append(code_str)
        shortlisted_codes.add(code_str)
    return extended


def _find_candidate_row(candidates: Candidates, code: str) -> pd.Series | None:
    for attr_name in ("popular", "model", "etf", "merged"):
        frame = getattr(candidates, attr_name, None)
        if frame is None or getattr(frame, "empty", True) or "code" not in frame.columns:
            continue
        rows = frame[frame["code"].astype(str) == str(code)]
        if rows.empty:
            continue
        return rows.iloc[0]
    return None


def _safe_daily_bars(api: TradingAPI, *, code: str, trade_date: str, lookback: int) -> pd.DataFrame:
    try:
        bars = api.daily_bars(code=code, end=trade_date, lookback=lookback)
    except Exception:
        logger.debug("day chart review daily_bars failed code=%s", code, exc_info=True)
        return pd.DataFrame()
    return bars.copy() if isinstance(bars, pd.DataFrame) else pd.DataFrame()


def _safe_intraday_bars(api: TradingAPI, *, code: str, trade_date: str, lookback: int) -> pd.DataFrame:
    intraday_fn = getattr(api, "intraday_bars", None)
    if not callable(intraday_fn):
        return pd.DataFrame()
    try:
        bars = intraday_fn(code=code, asof=trade_date, lookback=lookback)
    except Exception:
        logger.debug("day chart review intraday_bars failed code=%s", code, exc_info=True)
        return pd.DataFrame()
    if not isinstance(bars, pd.DataFrame):
        return pd.DataFrame()
    return sort_intraday_bars(bars)


def _candidate_meta_text(
    *,
    rank: int,
    code: str,
    row: pd.Series | None,
    quote: Quote,
) -> str:
    name = str(row.get("name") if row is not None else quote.get("name") or "").strip() or code
    avg_value_label, avg_value = _resolve_candidate_avg_value(row)
    change_pct = _resolve_change_pct(row, {str(code): quote}) if row is not None else None
    if change_pct is None:
        change_pct = parse_numeric(quote.get("change_pct")) or parse_numeric(quote.get("change_rate"))
    breakout_vs_prev_high = parse_numeric(row.get("breakout_vs_prev_high_10d_pct")) if row is not None else None
    close = parse_numeric(quote.get("price"))
    if close is None and row is not None:
        close = parse_numeric(row.get("close"))
    return (
        f"후보 {rank}: {name}({code})\n"
        f"- 현재가: {close if close is not None else 'N/A'}\n"
        f"- 등락률: {change_pct if change_pct is not None else 'N/A'}%\n"
        f"- {avg_value_label}: "
        f"{round(avg_value / 1e8, 1) if avg_value is not None else 'N/A'}억\n"
        f"- 직전 10일 최고 종가 대비: {breakout_vs_prev_high if breakout_vs_prev_high is not None else 'N/A'}%"
    )


def _resolve_candidate_avg_value(row: pd.Series | None) -> tuple[str, float | None]:
    if row is None:
        return "평균 거래대금", None
    avg_value_5d = parse_numeric(row.get("avg_value_5d"))
    if avg_value_5d is not None:
        return "5일 평균 거래대금", avg_value_5d
    avg_value_20d = parse_numeric(row.get("avg_value_20d"))
    if avg_value_20d is not None:
        return "20일 평균 거래대금", avg_value_20d
    return "평균 거래대금", None


def _file_to_data_url(path: str) -> str:
    with open(path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _build_review_messages(
    *,
    system_prompt_name: str,
    header_text: str,
    assets: list[_ReviewAsset],
) -> list[ReviewMessage]:
    content: list[ReviewMessage] = [{"type": "text", "text": header_text}]
    for asset in assets:
        content.append({"type": "text", "text": asset.meta_text})
        content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": _file_to_data_url(asset.chart_path),
                    "detail": "high",
                },
            }
        )
    return [
        {"role": "system", "content": load_prompt(system_prompt_name)},
        {"role": "user", "content": content},
    ]


def _build_review_result(
    *,
    assets: list[_ReviewAsset],
    parsed: ReviewPayload,
    route: str,
    summary_prefix: str | None = None,
) -> DayChartReviewResult:
    shortlist = [asset.code for asset in assets]
    approved_codes = _approved_codes_from_review(shortlist=shortlist, parsed=parsed)
    selected_code = parsed.get("selected_code")
    if selected_code is not None:
        selected_code = str(selected_code).strip() or None
    summary = str(parsed.get("summary") or "").strip()
    if summary_prefix:
        summary = f"{summary_prefix}{summary}".strip()
    raw_response = dict(parsed)
    raw_response["_route"] = route
    return DayChartReviewResult(
        shortlisted_codes=shortlist,
        approved_codes=approved_codes,
        selected_code=selected_code,
        summary=summary,
        chart_paths=[asset.chart_path for asset in assets],
        raw_response=raw_response,
    )


def _run_chart_review_hybrid(
    *,
    llm: LLMService,
    assets: list[_ReviewAsset],
    header_text: str,
    system_prompt_name: str,
    paid_min_candidates: int,
    paid_model: str,
    paid_reasoning_effort: str,
) -> DayChartReviewResult | None:
    paid_available = bool(getattr(llm, "paid_backend", None)) and llm.settings.is_paid_configured()
    local_available = llm.settings.is_remote_configured()

    local_result: DayChartReviewResult | None = None
    if local_available:
        local_messages = _build_review_messages(
            system_prompt_name=system_prompt_name,
            header_text=header_text,
            assets=assets,
        )
        local_raw = llm.generate_chat(
            local_messages,
            max_tokens=_REVIEW_MAX_TOKENS,
            temperature=0.1,
            response_format=_CHART_REVIEW_RESPONSE_FORMAT,
            allow_paid_fallback=False,
        )
        local_parsed = _parse_review_response(local_raw)
        if local_parsed:
            local_result = _build_review_result(
                assets=assets,
                parsed=local_parsed,
                route="local",
            )
        else:
            logger.warning("local chart review parse failed raw=%s", (local_raw or "")[:400])

    if local_result is None:
        if not paid_available:
            return None
        paid_messages = _build_review_messages(
            system_prompt_name=system_prompt_name,
            header_text=header_text,
            assets=assets,
        )
        paid_raw = llm.generate_paid_chat(
            paid_messages,
            max_tokens=_REVIEW_MAX_TOKENS,
            temperature=0.1,
            model=paid_model,
            reasoning_effort=paid_reasoning_effort,
            response_format=_CHART_REVIEW_RESPONSE_FORMAT,
        )
        paid_parsed = _parse_review_response(paid_raw)
        if not paid_parsed:
            logger.warning("paid chart review parse failed raw=%s", (paid_raw or "")[:400])
            return None
        return _build_review_result(assets=assets, parsed=paid_parsed, route="paid_only")

    if len(local_result.approved_codes) <= 1 or not paid_available:
        return local_result

    finalist_assets, reference_codes = _build_paid_finalist_assets(
        assets=assets,
        approved_codes=local_result.approved_codes,
        min_count=paid_min_candidates,
    )
    if len(finalist_assets) <= 1:
        return local_result

    finalist_header = _build_paid_finalist_header(
        header_text=header_text,
        approved_codes=local_result.approved_codes,
        reference_codes=reference_codes,
    )
    paid_messages = _build_review_messages(
        system_prompt_name=system_prompt_name,
        header_text=finalist_header,
        assets=finalist_assets,
    )
    paid_raw = llm.generate_paid_chat(
        paid_messages,
        max_tokens=_REVIEW_MAX_TOKENS,
        temperature=0.1,
        model=paid_model,
        reasoning_effort=paid_reasoning_effort,
        response_format=_CHART_REVIEW_RESPONSE_FORMAT,
    )
    paid_parsed = _parse_review_response(paid_raw)
    if not paid_parsed:
        logger.warning("paid chart review tie-break parse failed raw=%s", (paid_raw or "")[:400])
        return local_result

    paid_result = _build_review_result(
        assets=finalist_assets,
        parsed=paid_parsed,
        route="hybrid_paid_tiebreak",
        summary_prefix="로컬 1차 통과 후보를 유료 2차로 재정렬. ",
    )
    if reference_codes:
        paid_result = _restrict_paid_result_to_local_approvals(
            paid_result=paid_result,
            local_result=local_result,
        )
    return DayChartReviewResult(
        shortlisted_codes=local_result.shortlisted_codes,
        approved_codes=paid_result.approved_codes,
        selected_code=paid_result.selected_code,
        summary=paid_result.summary,
        chart_paths=local_result.chart_paths,
        raw_response=paid_result.raw_response,
    )


def _build_paid_finalist_assets(
    *,
    assets: list[_ReviewAsset],
    approved_codes: list[str],
    min_count: int,
) -> tuple[list[_ReviewAsset], list[str]]:
    approved_set = {str(code).strip() for code in approved_codes if str(code).strip()}
    finalists = [asset for asset in assets if asset.code in approved_set]
    reference_codes: list[str] = []
    target_count = max(2, int(min_count))
    if len(finalists) >= target_count:
        return finalists, reference_codes

    for asset in assets:
        if asset.code in approved_set:
            continue
        finalists.append(asset)
        reference_codes.append(asset.code)
        if len(finalists) >= target_count:
            break
    return finalists, reference_codes


def _build_paid_finalist_header(
    *,
    header_text: str,
    approved_codes: list[str],
    reference_codes: list[str],
) -> str:
    approved_text = ",".join(str(code).strip() for code in approved_codes if str(code).strip())
    header_lines = [
        header_text,
        f"로컬 1차 검토 통과 후보: {approved_text}",
    ]
    if reference_codes:
        header_lines.append(f"추가 비교 후보: {','.join(reference_codes)}")
        header_lines.append(
            "selected_code는 로컬 1차 검토 통과 후보 중에서만 골라줘. 추가 비교 후보는 상대 비교 참고용이다."
        )
    else:
        header_lines.append("통과 후보들 중 최종 1개만 더 엄격하게 선택해줘.")
    return "\n".join(header_lines)


def _restrict_paid_result_to_local_approvals(
    *,
    paid_result: DayChartReviewResult,
    local_result: DayChartReviewResult,
) -> DayChartReviewResult:
    allowed_codes = {str(code).strip() for code in local_result.approved_codes if str(code).strip()}
    approved_codes = [code for code in paid_result.approved_codes if code in allowed_codes]
    selected_code = paid_result.selected_code if paid_result.selected_code in allowed_codes else None
    if selected_code is None:
        if approved_codes:
            selected_code = approved_codes[0]
        elif local_result.selected_code in allowed_codes:
            selected_code = local_result.selected_code
        elif local_result.approved_codes:
            selected_code = local_result.approved_codes[0]
    return DayChartReviewResult(
        shortlisted_codes=paid_result.shortlisted_codes,
        approved_codes=approved_codes,
        selected_code=selected_code,
        summary=paid_result.summary,
        chart_paths=paid_result.chart_paths,
        raw_response=paid_result.raw_response,
    )


def _parse_review_response(raw_text: str) -> ReviewPayload | None:
    text = str(raw_text or "").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.DOTALL)
    if fenced:
        try:
            parsed = json.loads(fenced.group(1))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return None
    return None


def _approved_codes_from_review(*, shortlist: list[str], parsed: ReviewPayload) -> list[str]:
    decisions_raw = parsed.get("candidates") or []
    decision_map: dict[str, str] = {}
    if isinstance(decisions_raw, list):
        for item in decisions_raw:
            if not isinstance(item, dict):
                continue
            code = str(item.get("code") or "").strip()
            decision = str(item.get("decision") or "").strip().upper()
            if code and decision:
                decision_map[code] = decision

    approved = [code for code in shortlist if decision_map.get(code, "UNSURE") != "PASS"]
    selected_code = str(parsed.get("selected_code") or "").strip()
    if selected_code and selected_code in approved:
        approved = [selected_code] + [code for code in approved if code != selected_code]
    return approved
