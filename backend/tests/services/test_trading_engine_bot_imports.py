from backend.services.trading_engine.bot import HybridTradingBot
from backend.services.trading_engine.bot_entry_flow import BotEntryFlowMixin
from backend.services.trading_engine.bot_position_management import BotPositionManagementMixin
from backend.services.trading_engine.day_chart_review import (
    DayChartReviewResult,
    review_day_candidates_with_llm,
    review_swing_candidates_with_llm,
)


def test_public_bot_entry_and_review_imports_smoke() -> None:
    assert BotEntryFlowMixin is not None
    assert BotPositionManagementMixin is not None
    assert HybridTradingBot is not None
    assert DayChartReviewResult is not None
    assert callable(review_day_candidates_with_llm)
    assert callable(review_swing_candidates_with_llm)
