from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Mapping, Protocol

import pandas as pd

from backend.services.prompt_loader import load_prompt
from backend.services.trading_engine.chart_review_renderer import render_monthly_chart_png
from backend.services.trading_engine.day_chart_review import file_to_data_url, parse_review_response

from .pension_rebalancing import (
    PensionAsset,
    PensionHolding,
    PensionOrderPlan,
    bucket_values,
)


PENSION_EXIT_REVIEW_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "pension_exit_review",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "summary": {"type": "string"},
                "balance_assessment": {"type": "string"},
                "decisions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "code": {"type": "string"},
                            "decision": {
                                "type": "string",
                                "enum": ["SELL_PARTIAL", "HOLD"],
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
            "required": ["summary", "balance_assessment", "decisions"],
        },
    },
}


@dataclass(frozen=True)
class PensionExitDecision:
    code: str
    decision: str
    reason: str
    confidence: float


@dataclass(frozen=True)
class PensionExitReview:
    approved_codes: list[str]
    summary: str
    balance_assessment: str
    route: str
    chart_paths: list[str]
    decisions: list[PensionExitDecision]


class _LLMSettings(Protocol):
    def is_paid_configured(self) -> bool: ...

    def is_remote_configured(self) -> bool: ...


class PensionExitReviewer(Protocol):
    settings: _LLMSettings

    def generate_paid_chat(self, messages: list[dict], **kwargs: object) -> str: ...

    def generate_chat(self, messages: list[dict], **kwargs: object) -> str: ...


def pension_exit_chart_codes(
    *,
    assets: list[PensionAsset],
) -> list[str]:
    codes = [asset.code for asset in assets if asset.bucket in {"sp500", "momentum"}]
    return list(dict.fromkeys(codes))


def _account_payload(
    *,
    holdings: list[PensionHolding],
    cash: int,
    assets: list[PensionAsset],
    target_weights: Mapping[str, float],
    sell_orders: list[PensionOrderPlan],
    regime: str,
) -> dict[str, object]:
    total_value = max(0, int(cash)) + sum(max(0, holding.value) for holding in holdings)
    asset_by_code = {asset.code: asset for asset in assets}
    current_values = bucket_values(holdings, assets)
    holding_by_code = {holding.code: holding for holding in holdings}
    projected_values = dict(current_values)
    projected_cash = max(0, int(cash))
    for order in sell_orders:
        if order.side != "SELL":
            continue
        projected_values[order.bucket] = max(0, projected_values.get(order.bucket, 0) - order.amount)
        projected_cash += order.amount
    purchase_amount = sum(max(0.0, holding.avg_price) * max(0, holding.qty) for holding in holdings)
    total_pnl = sum(holding.pnl for holding in holdings)
    return {
        "task": "연금계좌 포트폴리오 매도 전 최종 균형 검토",
        "account": {
            "regime": regime,
            "total_value": total_value,
            "cash": max(0, int(cash)),
            "cash_weight_pct": round((cash / total_value) * 100.0, 4) if total_value > 0 else 0.0,
            "total_pnl": total_pnl,
            "total_pnl_rate_pct": round((total_pnl / purchase_amount) * 100.0, 4) if purchase_amount > 0 else 0.0,
            "current_bucket_values": current_values,
            "current_bucket_weights_pct": {
                bucket: round((value / total_value) * 100.0, 4) if total_value > 0 else 0.0
                for bucket, value in current_values.items()
            },
            "target_weights_pct": {
                bucket: round(float(weight) * 100.0, 4) for bucket, weight in target_weights.items()
            },
            "projected_cash_after_sells": projected_cash,
            "projected_cash_weight_pct": round((projected_cash / total_value) * 100.0, 4)
            if total_value > 0
            else 0.0,
            "projected_bucket_values_after_sells": projected_values,
            "projected_bucket_weights_pct_after_sells": {
                bucket: round((value / total_value) * 100.0, 4) if total_value > 0 else 0.0
                for bucket, value in projected_values.items()
            },
        },
        "holdings": [
            {
                **asdict(holding),
                "bucket": asset_by_code.get(holding.code).bucket if holding.code in asset_by_code else "other",
                "weight_pct": round((holding.value / total_value) * 100.0, 4) if total_value > 0 else 0.0,
            }
            for holding in holdings
        ],
        "planned_partial_sells": [
            {
                **asdict(order),
                "holding_qty": holding_by_code[order.code].qty if order.code in holding_by_code else 0,
                "planned_holding_fraction_pct": round(
                    (order.qty / holding_by_code[order.code].qty) * 100.0,
                    4,
                )
                if order.code in holding_by_code and holding_by_code[order.code].qty > 0
                else 0.0,
            }
            for order in sell_orders
            if order.side == "SELL"
        ],
        "rules": {
            "allowed_decisions": ["SELL_PARTIAL", "HOLD"],
            "full_liquidation": "forbidden",
            "target_weight_change": "forbidden",
            "new_asset_discovery": "forbidden",
            "monthly_chart_required_buckets": ["sp500", "momentum"],
            "cash_like_chart_policy": "parking과 bond는 월봉 없이 유동성·목표비중으로 판단",
        },
    }


def _build_messages(
    *,
    payload: dict[str, object],
    holdings: list[PensionHolding],
    assets: list[PensionAsset],
    monthly_prices_by_code: dict[str, list[tuple[str, int]]],
    output_dir: str,
) -> tuple[list[dict[str, object]], list[str], set[str]]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    holding_by_code = {holding.code: holding for holding in holdings}
    asset_by_code = {asset.code: asset for asset in assets}
    content: list[dict[str, object]] = [
        {"type": "text", "text": json.dumps(payload, ensure_ascii=False)},
    ]
    chart_paths: list[str] = []
    chart_codes: set[str] = set()
    for code, prices in monthly_prices_by_code.items():
        normalized = [(str(date_key), int(close)) for date_key, close in prices if int(close) > 0]
        if not normalized:
            continue
        chart_path = output_path / f"{code}_monthly.png"
        frame = pd.DataFrame(normalized, columns=["date", "close"])
        render_monthly_chart_png(path=str(chart_path), code=code, monthly_bars=frame)
        holding = holding_by_code.get(code)
        asset = asset_by_code.get(code)
        content.append(
            {
                "type": "text",
                "text": (
                    f"월봉 차트 code={code} name={holding.name if holding else ''} "
                    f"asset_name={asset.name if asset else ''} "
                    f"bucket={asset.bucket if asset else 'other'} months={len(normalized)}"
                ),
            }
        )
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": file_to_data_url(str(chart_path)), "detail": "high"},
            }
        )
        chart_paths.append(str(chart_path))
        chart_codes.add(code)
    return (
        [
            {"role": "system", "content": load_prompt("pension_exit_review_system")},
            {"role": "user", "content": content},
        ],
        chart_paths,
        chart_codes,
    )


def review_pension_sell_orders(
    *,
    holdings: list[PensionHolding],
    cash: int,
    assets: list[PensionAsset],
    target_weights: Mapping[str, float],
    sell_orders: list[PensionOrderPlan],
    regime: str,
    monthly_prices_by_code: dict[str, list[tuple[str, int]]],
    output_dir: str,
    llm: PensionExitReviewer | None = None,
    model: str = "gpt-5.5",
    reasoning_effort: str = "high",
) -> PensionExitReview:
    sell_codes = {order.code for order in sell_orders if order.side == "SELL"}
    asset_by_code = {asset.code: asset for asset in assets}
    chart_required_codes = {
        code
        for code in sell_codes
        if code in asset_by_code and asset_by_code[code].bucket in {"sp500", "momentum"}
    }
    if not sell_codes:
        return PensionExitReview(
            approved_codes=[],
            summary="매도 계획이 없습니다.",
            balance_assessment="균형 검토 불필요",
            route="no_orders",
            chart_paths=[],
            decisions=[],
        )

    payload = _account_payload(
        holdings=holdings,
        cash=cash,
        assets=assets,
        target_weights=target_weights,
        sell_orders=sell_orders,
        regime=regime,
    )
    messages, chart_paths, chart_codes = _build_messages(
        payload=payload,
        holdings=holdings,
        assets=assets,
        monthly_prices_by_code=monthly_prices_by_code,
        output_dir=output_dir,
    )
    if llm is None:
        from backend.services.llm.service import LLMService

        llm = LLMService.get_instance()

    if llm.settings.is_paid_configured():
        raw = llm.generate_paid_chat(
            messages,
            max_tokens=1200,
            temperature=0.1,
            model=model,
            reasoning_effort=reasoning_effort,
            response_format=PENSION_EXIT_REVIEW_RESPONSE_FORMAT,
        )
        route = "paid"
    elif llm.settings.is_remote_configured():
        raw = llm.generate_chat(
            messages,
            max_tokens=1200,
            temperature=0.1,
            allow_paid_fallback=False,
            response_format=PENSION_EXIT_REVIEW_RESPONSE_FORMAT,
        )
        route = "local"
    else:
        return PensionExitReview(
            approved_codes=[],
            summary="AI 검토 백엔드가 없습니다.",
            balance_assessment="매도 보류",
            route="no_backend",
            chart_paths=chart_paths,
            decisions=[],
        )

    parsed = parse_review_response(raw)
    if not parsed:
        return PensionExitReview(
            approved_codes=[],
            summary="AI 검토 응답을 해석하지 못했습니다.",
            balance_assessment="매도 보류",
            route=f"{route}_parse_failed",
            chart_paths=chart_paths,
            decisions=[],
        )

    approved_codes: list[str] = []
    decisions: list[PensionExitDecision] = []
    for decision in parsed.get("decisions") or []:
        if not isinstance(decision, dict):
            continue
        code = str(decision.get("code") or "").strip()
        verdict = str(decision.get("decision") or "").strip().upper()
        if code not in sell_codes or verdict not in {"SELL_PARTIAL", "HOLD"}:
            continue
        reason = str(decision.get("reason") or "").strip()
        if verdict == "SELL_PARTIAL" and code in chart_required_codes and code not in chart_codes:
            verdict = "HOLD"
            reason = f"{reason} / 월봉 차트 누락으로 매도 보류".strip(" /")
        try:
            confidence = float(decision.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        decisions.append(PensionExitDecision(code, verdict, reason, max(0.0, min(1.0, confidence))))
        if verdict == "SELL_PARTIAL":
            approved_codes.append(code)
    return PensionExitReview(
        approved_codes=list(dict.fromkeys(approved_codes)),
        summary=str(parsed.get("summary") or "").strip(),
        balance_assessment=str(parsed.get("balance_assessment") or "").strip(),
        route=route,
        chart_paths=chart_paths,
        decisions=decisions,
    )
