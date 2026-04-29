from __future__ import annotations

import base64
import json
import logging
import re
from typing import TYPE_CHECKING

from ..llm.service import LLMService
from .day_chart_review_context import (
    DayChartReviewResult,
    ReviewMessage,
    ReviewPayload,
    build_day_review_assets,
    build_swing_review_assets,
    candidate_meta_text as _candidate_meta_text,
)
from ..prompt_loader import load_prompt

if TYPE_CHECKING:
    from .config import TradeEngineConfig
    from .interfaces import TradingAPI
    from .strategy import Candidates
    from .types import QuoteMap

logger = logging.getLogger(__name__)

REVIEW_MAX_TOKENS = 700
CHART_REVIEW_RESPONSE_FORMAT = {
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


def review_day_candidates_with_llm(
    *,
    api: "TradingAPI",
    trade_date: str,
    ranked_codes: list[str],
    candidates: "Candidates",
    quotes: "QuoteMap",
    config: "TradeEngineConfig",
    output_dir: str,
) -> DayChartReviewResult | None:
    if not getattr(config, "day_chart_review_enabled", False):
        return None

    llm = LLMService.get_instance()
    if not llm.settings.is_remote_configured() and not llm.settings.is_paid_configured():
        return None

    assets = build_day_review_assets(
        api=api,
        trade_date=trade_date,
        ranked_codes=ranked_codes,
        candidates=candidates,
        quotes=quotes,
        config=config,
        output_dir=output_dir,
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
    api: "TradingAPI",
    trade_date: str,
    ranked_codes: list[str],
    candidates: "Candidates",
    quotes: "QuoteMap",
    config: "TradeEngineConfig",
    output_dir: str,
) -> DayChartReviewResult | None:
    if not getattr(config, "swing_chart_review_enabled", False):
        return None

    llm = LLMService.get_instance()
    if not llm.settings.is_remote_configured() and not llm.settings.is_paid_configured():
        return None

    assets = build_swing_review_assets(
        api=api,
        trade_date=trade_date,
        ranked_codes=ranked_codes,
        candidates=candidates,
        quotes=quotes,
        config=config,
        output_dir=output_dir,
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


def _run_chart_review_hybrid(
    *,
    llm: LLMService,
    assets,
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
        local_messages = build_review_messages(
            system_prompt_name=system_prompt_name,
            header_text=header_text,
            assets=assets,
        )
        local_raw = llm.generate_chat(
            local_messages,
            max_tokens=REVIEW_MAX_TOKENS,
            temperature=0.1,
            response_format=CHART_REVIEW_RESPONSE_FORMAT,
            allow_paid_fallback=False,
        )
        local_parsed = parse_review_response(local_raw)
        if local_parsed:
            local_result = build_review_result(
                assets=assets,
                parsed=local_parsed,
                route="local",
            )
        else:
            logger.warning("local chart review parse failed raw=%s", (local_raw or "")[:400])

    if local_result is None:
        if not paid_available:
            return None
        paid_messages = build_review_messages(
            system_prompt_name=system_prompt_name,
            header_text=header_text,
            assets=assets,
        )
        paid_raw = llm.generate_paid_chat(
            paid_messages,
            max_tokens=REVIEW_MAX_TOKENS,
            temperature=0.1,
            model=paid_model,
            reasoning_effort=paid_reasoning_effort,
            response_format=CHART_REVIEW_RESPONSE_FORMAT,
        )
        paid_parsed = parse_review_response(paid_raw)
        if not paid_parsed:
            logger.warning("paid chart review parse failed raw=%s", (paid_raw or "")[:400])
            return None
        return build_review_result(assets=assets, parsed=paid_parsed, route="paid_only")

    if len(local_result.approved_codes) <= 1 or not paid_available:
        return local_result

    finalist_assets, reference_codes = build_paid_finalist_assets(
        assets=assets,
        approved_codes=local_result.approved_codes,
        min_count=paid_min_candidates,
    )
    if len(finalist_assets) <= 1:
        return local_result

    finalist_header = build_paid_finalist_header(
        header_text=header_text,
        approved_codes=local_result.approved_codes,
        reference_codes=reference_codes,
    )
    paid_messages = build_review_messages(
        system_prompt_name=system_prompt_name,
        header_text=finalist_header,
        assets=finalist_assets,
    )
    paid_raw = llm.generate_paid_chat(
        paid_messages,
        max_tokens=REVIEW_MAX_TOKENS,
        temperature=0.1,
        model=paid_model,
        reasoning_effort=paid_reasoning_effort,
        response_format=CHART_REVIEW_RESPONSE_FORMAT,
    )
    paid_parsed = parse_review_response(paid_raw)
    if not paid_parsed:
        logger.warning("paid chart review tie-break parse failed raw=%s", (paid_raw or "")[:400])
        return local_result

    paid_result = build_review_result(
        assets=finalist_assets,
        parsed=paid_parsed,
        route="hybrid_paid_tiebreak",
        summary_prefix="로컬 1차 통과 후보를 유료 2차로 재정렬. ",
    )
    if reference_codes:
        paid_result = restrict_paid_result_to_local_approvals(
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


def file_to_data_url(path: str) -> str:
    with open(path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def build_review_messages(
    *,
    system_prompt_name: str,
    header_text: str,
    assets,
) -> list[dict[str, object]]:
    content: list[dict[str, object]] = [{"type": "text", "text": header_text}]
    for asset in assets:
        content.append({"type": "text", "text": asset.meta_text})
        content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": file_to_data_url(asset.chart_path),
                    "detail": "high",
                },
            }
        )
    return [
        {"role": "system", "content": load_prompt(system_prompt_name)},
        {"role": "user", "content": content},
    ]


def build_paid_finalist_assets(
    *,
    assets,
    approved_codes: list[str],
    min_count: int,
):
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


def build_paid_finalist_header(
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


def build_review_result(
    *,
    assets,
    parsed: ReviewPayload,
    route: str,
    summary_prefix: str | None = None,
) -> DayChartReviewResult:
    shortlist = [asset.code for asset in assets]
    approved_codes = approved_codes_from_review(shortlist=shortlist, parsed=parsed)
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


def restrict_paid_result_to_local_approvals(
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


def parse_review_response(raw_text: str) -> ReviewPayload | None:
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


def approved_codes_from_review(*, shortlist: list[str], parsed: ReviewPayload) -> list[str]:
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


__all__ = [
    "approved_codes_from_review",
    "build_paid_finalist_assets",
    "build_paid_finalist_header",
    "build_review_messages",
    "build_review_result",
    "CHART_REVIEW_RESPONSE_FORMAT",
    "DayChartReviewResult",
    "file_to_data_url",
    "parse_review_response",
    "REVIEW_MAX_TOKENS",
    "ReviewMessage",
    "ReviewPayload",
    "restrict_paid_result_to_local_approvals",
    "_candidate_meta_text",
    "review_day_candidates_with_llm",
    "review_swing_candidates_with_llm",
]
