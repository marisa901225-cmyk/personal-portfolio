def test_execution_and_state_public_imports_smoke() -> None:
    from backend.services.trading_engine.bot import HybridTradingBot
    from backend.services.trading_engine.execution import (
        FillResult,
        enter_position,
        exit_position,
        handle_open_orders,
        increment_bars_held,
    )
    from backend.services.trading_engine.position_helpers import (
        is_swing_trend_broken,
        lock_profitable_existing_position,
        reconcile_state_with_broker_positions,
    )
    from backend.services.trading_engine.state import (
        PositionState,
        TradeState,
        load_state,
        save_state,
    )

    assert HybridTradingBot is not None
    assert FillResult is not None
    assert enter_position is not None
    assert exit_position is not None
    assert handle_open_orders is not None
    assert increment_bars_held is not None
    assert reconcile_state_with_broker_positions is not None
    assert is_swing_trend_broken is not None
    assert lock_profitable_existing_position is not None
    assert PositionState is not None
    assert TradeState is not None
    assert load_state is not None
    assert save_state is not None
