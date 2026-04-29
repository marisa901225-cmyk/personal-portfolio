import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.services.scheduler import core


class TestTradingLockMonitor(unittest.IsolatedAsyncioTestCase):
    async def test_lock_monitor_runs_even_while_cycle_lock_is_held(self) -> None:
        bot = MagicMock()
        bot.has_armed_day_profit_locks.return_value = True

        await core._trading_engine_cycle_lock.acquire()
        try:
            with (
                patch.object(core, "get_or_create_bot", return_value=bot),
                patch.object(core, "is_regular_market_open", return_value=True),
                patch.object(core.asyncio, "to_thread", new=AsyncMock(return_value={"status": "OK"})) as mock_to_thread,
            ):
                await core.job_trading_engine_lock_monitor()
        finally:
            core._trading_engine_cycle_lock.release()

        mock_to_thread.assert_awaited_once()
        call_args = mock_to_thread.await_args
        assert call_args is not None
        self.assertIs(call_args.args[0], bot.run_locked_profit_monitor)

