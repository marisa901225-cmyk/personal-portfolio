from __future__ import annotations

import json
from datetime import date, timedelta

from backend.services.pension_momentum import (
    analyze_pension_momentum_candidate,
    rank_pension_momentum_candidates,
    review_pension_momentum_candidates,
)


def _prices(values: list[int]) -> list[tuple[str, int]]:
    start = date(2025, 1, 1)
    return [((start + timedelta(days=index)).strftime("%Y%m%d"), value) for index, value in enumerate(values)]


def test_pension_momentum_requires_enough_weekly_history() -> None:
    candidate = analyze_pension_momentum_candidate(
        code="426030",
        name="TIME 미국나스닥100액티브",
        daily_prices=_prices([100 + index for index in range(60)]),
    )

    assert not candidate.eligible
    assert "INSUFFICIENT_HISTORY" in candidate.reasons


def test_pension_momentum_ranks_intact_weekly_growth_above_broken_trend() -> None:
    intact = analyze_pension_momentum_candidate(
        code="426030",
        name="TIME 미국나스닥100액티브",
        daily_prices=_prices([100 + index for index in range(220)]),
    )
    broken_values = [100 + index for index in range(160)] + [260 - (index * 3) for index in range(60)]
    broken = analyze_pension_momentum_candidate(
        code="237350",
        name="KODEX 코스피100",
        daily_prices=_prices(broken_values),
    )

    ranked = rank_pension_momentum_candidates([broken, intact])

    assert intact.eligible
    assert not broken.eligible
    assert ranked[0].code == "426030"


def test_pension_momentum_blocks_deep_drawdown_and_excessive_volatility() -> None:
    volatile_values = [100 + index for index in range(180)] + [280, 210] * 20
    candidate = analyze_pension_momentum_candidate(
        code="237350",
        name="KODEX 코스피100",
        daily_prices=_prices(volatile_values),
    )

    assert not candidate.eligible
    assert "DEEP_26W_DRAWDOWN" in candidate.reasons
    assert "EXCESSIVE_VOLATILITY" in candidate.reasons


def test_ai_review_can_only_select_quantitatively_eligible_candidate() -> None:
    intact = analyze_pension_momentum_candidate(
        code="426030",
        name="TIME 미국나스닥100액티브",
        daily_prices=_prices([100 + index for index in range(220)]),
    )
    broken_values = [100 + index for index in range(160)] + [260 - (index * 3) for index in range(60)]
    broken = analyze_pension_momentum_candidate(
        code="237350",
        name="KODEX 코스피100",
        daily_prices=_prices(broken_values),
    )

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
            payload = json.loads(messages[-1]["content"])
            assert [candidate["code"] for candidate in payload["candidates"]] == ["426030"]
            return json.dumps(
                {
                    "candidates": [
                        {"code": "426030", "decision": "ENTER", "reason": "주봉 상승 추세 유지"}
                    ],
                    "selected_code": "426030",
                    "summary": "정량 1위 후보 승인",
                }
            )

    review = review_pension_momentum_candidates([broken, intact], llm=LLM())

    assert review.selected_code == "426030"
    assert review.approved_codes == ["426030"]


def test_ai_review_fails_closed_for_out_of_shortlist_selection() -> None:
    intact = analyze_pension_momentum_candidate(
        code="426030",
        name="TIME 미국나스닥100액티브",
        daily_prices=_prices([100 + index for index in range(220)]),
    )

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
            return json.dumps(
                {
                    "candidates": [
                        {"code": "237350", "decision": "ENTER", "reason": "목록 밖 후보"}
                    ],
                    "selected_code": "237350",
                    "summary": "잘못된 선택",
                }
            )

    review = review_pension_momentum_candidates([intact], llm=LLM())

    assert review.selected_code == ""
    assert review.approved_codes == []
