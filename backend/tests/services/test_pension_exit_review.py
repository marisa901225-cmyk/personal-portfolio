from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.services.pension_exit_review import (
    pension_exit_chart_codes,
    review_pension_sell_orders,
)
from backend.services.pension_rebalancing import PensionAsset, PensionHolding, PensionOrderPlan


HOLDINGS = [
    PensionHolding(
        "360200",
        "ACE 미국S&P500",
        10,
        10_000,
        100_000,
        avg_price=9_000,
        pnl=10_000,
        pnl_rate=11.11,
    ),
    PensionHolding("426030", "TIME 미국나스닥100액티브", 10, 20_000, 200_000),
]
ASSETS = [
    PensionAsset("360200", "sp500", "ACE 미국S&P500"),
    PensionAsset("426030", "momentum", "TIME 미국나스닥100액티브"),
]
SELL_ORDERS = [
    PensionOrderPlan("SELL", "360200", "sp500", 4, 10_000, 40_000, "sp500 overweight"),
    PensionOrderPlan("SELL", "426030", "momentum", 4, 20_000, 80_000, "momentum weekly trend exit"),
]


def _monthly_prices(start: int) -> list[tuple[str, int]]:
    return [(f"{2023 + index // 12}{index % 12 + 1:02d}28", start + index * 100) for index in range(30)]


def test_exit_review_sends_account_balance_and_monthly_charts(tmp_path) -> None:
    captured: dict[str, object] = {}

    class Settings:
        @staticmethod
        def is_paid_configured() -> bool:
            return True

        @staticmethod
        def is_remote_configured() -> bool:
            return False

    class LLM:
        settings = Settings()

        @staticmethod
        def generate_paid_chat(messages: list[dict], **kwargs) -> str:
            captured["messages"] = messages
            captured["response_format"] = kwargs["response_format"]
            return json.dumps(
                {
                    "summary": "S&P500만 비중 축소",
                    "balance_assessment": "나스닥은 이미 축소되어 추가 매도 불필요",
                    "decisions": [
                        {
                            "code": "360200",
                            "decision": "SELL_PARTIAL",
                            "reason": "목표 비중 초과",
                            "confidence": 0.85,
                        },
                        {
                            "code": "426030",
                            "decision": "HOLD",
                            "reason": "추가 축소 불필요",
                            "confidence": 0.8,
                        },
                    ],
                },
                ensure_ascii=False,
            )

    review = review_pension_sell_orders(
        holdings=HOLDINGS,
        cash=100_000,
        assets=ASSETS,
        target_weights={"sp500": 0.4, "momentum": 0.6, "other": 0.0},
        sell_orders=SELL_ORDERS,
        regime="falling",
        monthly_prices_by_code={
            "360200": _monthly_prices(9_000),
            "426030": _monthly_prices(18_000),
        },
        output_dir=str(tmp_path),
        llm=LLM(),
    )

    assert review.approved_codes == ["360200"]
    assert review.route == "paid"
    assert [(decision.code, decision.decision) for decision in review.decisions] == [
        ("360200", "SELL_PARTIAL"),
        ("426030", "HOLD"),
    ]
    assert len(review.chart_paths) == 2
    assert all(Path(path).read_bytes().startswith(b"\x89PNG") for path in review.chart_paths)

    messages = captured["messages"]
    user_content = messages[-1]["content"]
    payload = json.loads(user_content[0]["text"])
    assert payload["account"]["total_value"] == 400_000
    assert payload["account"]["cash_weight_pct"] == 25.0
    assert payload["account"]["target_weights_pct"]["sp500"] == 40.0
    assert payload["account"]["projected_cash_after_sells"] == 220_000
    assert payload["account"]["projected_bucket_values_after_sells"]["sp500"] == 60_000
    assert payload["holdings"][0]["pnl"] == 10_000
    assert payload["planned_partial_sells"][0]["planned_holding_fraction_pct"] == 40.0
    assert len([part for part in user_content if part["type"] == "image_url"]) == 2


def test_exit_review_rejects_sell_approval_without_monthly_chart(tmp_path) -> None:
    class Settings:
        @staticmethod
        def is_paid_configured() -> bool:
            return False

        @staticmethod
        def is_remote_configured() -> bool:
            return True

    class LLM:
        settings = Settings()

        @staticmethod
        def generate_chat(messages: list[dict], **kwargs) -> str:
            return json.dumps(
                {
                    "summary": "매도 승인",
                    "balance_assessment": "비중 축소 필요",
                    "decisions": [
                        {
                            "code": "426030",
                            "decision": "SELL_PARTIAL",
                            "reason": "추세 훼손",
                            "confidence": 0.9,
                        }
                    ],
                },
                ensure_ascii=False,
            )

    review = review_pension_sell_orders(
        holdings=HOLDINGS,
        cash=100_000,
        assets=ASSETS,
        target_weights={"sp500": 0.4, "momentum": 0.6, "other": 0.0},
        sell_orders=SELL_ORDERS,
        regime="falling",
        monthly_prices_by_code={"360200": _monthly_prices(9_000)},
        output_dir=str(tmp_path),
        llm=LLM(),
    )

    assert review.approved_codes == []
    assert review.route == "local"
    assert [(decision.code, decision.decision) for decision in review.decisions] == [
        ("426030", "HOLD"),
    ]
    assert "월봉 차트 누락" in review.decisions[0].reason


def test_exit_review_fails_closed_without_ai_backend(tmp_path) -> None:
    class Settings:
        @staticmethod
        def is_paid_configured() -> bool:
            return False

        @staticmethod
        def is_remote_configured() -> bool:
            return False

    class LLM:
        settings = Settings()

    review = review_pension_sell_orders(
        holdings=HOLDINGS,
        cash=100_000,
        assets=ASSETS,
        target_weights={"sp500": 0.4, "momentum": 0.6, "other": 0.0},
        sell_orders=SELL_ORDERS,
        regime="falling",
        monthly_prices_by_code={
            "360200": _monthly_prices(9_000),
            "426030": _monthly_prices(18_000),
        },
        output_dir=str(tmp_path),
        llm=LLM(),
    )

    assert review.approved_codes == []
    assert review.route == "no_backend"


def test_exit_chart_codes_exclude_non_equity_sell_candidates() -> None:
    assets = [*ASSETS, PensionAsset("0048J0", "bond", "KODEX 미국머니마켓액티브")]
    assets.insert(1, PensionAsset("237350", "momentum", "KODEX 코스피100"))

    assert pension_exit_chart_codes(assets=assets) == ["360200", "237350", "426030"]


@pytest.mark.parametrize("bucket", ["parking", "bond"])
def test_exit_review_allows_cash_like_sell_without_monthly_chart(tmp_path, bucket) -> None:
    holding = PensionHolding("0048J0", "KODEX 미국머니마켓액티브", 10, 10_000, 100_000)
    asset = PensionAsset("0048J0", bucket, "KODEX 미국머니마켓액티브")
    order = PensionOrderPlan("SELL", "0048J0", bucket, 4, 10_000, 40_000, f"{bucket} funding")

    class Settings:
        @staticmethod
        def is_paid_configured() -> bool:
            return True

        @staticmethod
        def is_remote_configured() -> bool:
            return False

    class LLM:
        settings = Settings()

        @staticmethod
        def generate_paid_chat(messages: list[dict], **kwargs) -> str:
            assert not any(part["type"] == "image_url" for part in messages[-1]["content"])
            payload = json.loads(messages[-1]["content"][0]["text"])
            cash_like_policy = payload["rules"]["cash_like_chart_policy"]
            assert "대기자금" in cash_like_policy
            assert "매도 후 현금 완충분" in cash_like_policy
            return json.dumps(
                {
                    "summary": "현금성 자산 일부 사용",
                    "balance_assessment": "목표자산 매수 재원으로 적절",
                    "decisions": [
                        {
                            "code": "0048J0",
                            "decision": "SELL_PARTIAL",
                            "reason": "현금성 자산에서 매수 재원 충당",
                            "confidence": 0.9,
                        }
                    ],
                },
                ensure_ascii=False,
            )

    review = review_pension_sell_orders(
        holdings=[holding],
        cash=0,
        assets=[asset],
        target_weights={bucket: 0.0, "sp500": 1.0, "other": 0.0},
        sell_orders=[order],
        regime="rising",
        monthly_prices_by_code={},
        output_dir=str(tmp_path),
        llm=LLM(),
    )

    assert review.approved_codes == ["0048J0"]
    assert review.decisions[0].decision == "SELL_PARTIAL"
