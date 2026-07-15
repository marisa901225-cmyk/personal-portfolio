from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from backend.services.pension_momentum import (
    PensionIndexCandidate,
    analyze_pension_momentum_candidate,
    pension_index_family,
    rank_pension_momentum_candidates,
    review_pension_momentum_candidates,
    requires_momentum_trend_exit,
    select_liquid_pension_index_candidates,
)


def _prices(values: list[int]) -> list[tuple[str, int]]:
    start = date(2025, 1, 1)
    return [((start + timedelta(days=index)).strftime("%Y%m%d"), value) for index, value in enumerate(values)]


@pytest.mark.parametrize(
    ("name", "expected_family"),
    [
        ("KODEX 코스피100", "korea_kospi"),
        ("TIGER 미국나스닥100", "us_nasdaq100"),
        ("ACE 일본Nikkei225(H)", "japan_nikkei225"),
        ("TIGER 일본TOPIX(합성 H)", "japan_topix"),
        ("TIGER 차이나CSI300", "china_csi300"),
        ("KODEX 인도Nifty50", "india_nifty50"),
        ("ACE 베트남VN30(합성)", "vietnam_vn30"),
        ("KIWOOM 독일DAX", "germany_dax"),
        ("ACE MSCI인도네시아(합성)", "indonesia_msci"),
        ("KODEX 미국S&P500", ""),
        ("TIGER 미국다우존스30", ""),
        ("KODEX 미국러셀2000(H)", ""),
        ("KODEX MSCI선진국", ""),
        ("PLUS 글로벌MSCI(합성 H)", ""),
        ("KODEX 코스닥150", ""),
        ("TIGER 미국나스닥100레버리지(합성)", ""),
        ("KODEX 미국나스닥100선물인버스(H)", ""),
        ("TIGER 미국필라델피아반도체나스닥", ""),
    ],
)
def test_pension_index_family_allows_country_indices_and_blocks_unsafe_etfs(
    name: str,
    expected_family: str,
) -> None:
    assert pension_index_family(name) == expected_family


def test_liquid_index_selection_filters_low_value_and_keeps_one_etf_per_family() -> None:
    selected = select_liquid_pension_index_candidates(
        [
            PensionIndexCandidate("426030", "TIME 미국나스닥100액티브", "us_nasdaq100", 6_000_000_000),
            PensionIndexCandidate("133690", "TIGER 미국나스닥100", "us_nasdaq100", 100_000_000_000),
            PensionIndexCandidate("241180", "TIGER 일본니케이225", "japan_nikkei225", 4_900_000_000),
            PensionIndexCandidate("453870", "TIGER 인도니프티50", "india_nifty50", 7_000_000_000),
        ],
        min_avg_value_20d=5_000_000_000,
        preferred_codes={"426030"},
    )

    assert [candidate.code for candidate in selected] == ["453870", "426030"]


def test_pension_momentum_requires_enough_weekly_history() -> None:
    candidate = analyze_pension_momentum_candidate(
        code="426030",
        name="TIME 미국나스닥100액티브",
        daily_prices=_prices([100 + index for index in range(60)]),
    )

    assert not candidate.eligible
    assert "INSUFFICIENT_HISTORY" in candidate.reasons


def test_pension_momentum_uses_explicit_weekly_history_for_26_week_return() -> None:
    weekly_start = date(2025, 1, 3)
    weekly_prices = [
        ((weekly_start + timedelta(days=index * 7)).strftime("%Y%m%d"), 100 + index)
        for index in range(30)
    ]
    candidate = analyze_pension_momentum_candidate(
        code="241180",
        name="TIGER 일본니케이225",
        daily_prices=_prices([100 + index for index in range(100)]),
        weekly_prices=weekly_prices,
    )

    assert candidate.return_26w_pct > 0


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
    assert requires_momentum_trend_exit(broken)
    assert not requires_momentum_trend_exit(intact)


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
    assert requires_momentum_trend_exit(candidate)


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
