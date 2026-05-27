import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.services.scheduler import core


class TestSchedulerRoleSplit(unittest.TestCase):
    def test_periodic_minute_field_excludes_explicit_window_starts(self):
        self.assertEqual(core._periodic_minute_field(interval=2, exclude_minutes={5, 55}), "0,2,4,6,8,10,12,14,16,18,20,22,24,26,28,30,32,34,36,38,40,42,44,46,48,50,52,54,56,58")
        self.assertEqual(core._periodic_minute_field(interval=2, exclude_minutes={0, 55}), "2,4,6,8,10,12,14,16,18,20,22,24,26,28,30,32,34,36,38,40,42,44,46,48,50,52,54,56,58")

    def test_scheduler_role_defaults_to_all(self):
        with patch.dict("os.environ", {}, clear=False):
            self.assertEqual(core._scheduler_role(), "all")

    def test_scheduler_role_invalid_falls_back_to_all(self):
        with patch.dict("os.environ", {"SCHEDULER_ROLE": "weird"}, clear=False):
            self.assertEqual(core._scheduler_role(), "all")

    def test_start_scheduler_news_role_skips_trading_jobs(self):
        fake_scheduler = MagicMock()
        fake_scheduler.running = False

        with patch.object(core, "scheduler", fake_scheduler):
            with patch.dict(
                "os.environ",
                {
                    "SCHEDULER_ROLE": "news",
                    "TRADING_ENGINE_ENABLED": "1",
                },
                clear=False,
            ):
                core.start_scheduler()

        registered_ids = [call.kwargs["id"] for call in fake_scheduler.add_job.call_args_list]
        self.assertIn("collect_game_news", registered_ids)
        self.assertIn("morning_briefing", registered_ids)
        self.assertNotIn("trading_engine_cycle_preopen", registered_ids)
        self.assertNotIn("trading_engine_cycle_intraday_morning", registered_ids)
        self.assertNotIn("trading_engine_finalize", registered_ids)
        fake_scheduler.start.assert_called_once()

    def test_start_scheduler_trading_role_skips_news_jobs(self):
        fake_scheduler = MagicMock()
        fake_scheduler.running = False

        with patch.object(core, "scheduler", fake_scheduler):
            with patch.dict(
                "os.environ",
                {
                    "SCHEDULER_ROLE": "trading",
                    "TRADING_ENGINE_ENABLED": "1",
                },
                clear=False,
            ):
                core.start_scheduler()

        registered_ids = [call.kwargs["id"] for call in fake_scheduler.add_job.call_args_list]
        self.assertNotIn("collect_game_news", registered_ids)
        self.assertNotIn("morning_briefing", registered_ids)
        self.assertIn("trading_engine_cycle_preopen", registered_ids)
        self.assertIn("trading_engine_cycle_intraday_morning", registered_ids)
        self.assertIn("trading_engine_cycle_intraday_midday", registered_ids)
        self.assertIn("trading_engine_cycle_intraday_afternoon", registered_ids)
        self.assertIn("trading_engine_cycle_intraday_close", registered_ids)
        self.assertIn("trading_engine_finalize", registered_ids)
        finalize_call = next(
            call for call in fake_scheduler.add_job.call_args_list if call.kwargs["id"] == "trading_engine_finalize"
        )
        finalize_trigger = finalize_call.args[1]
        self.assertEqual(str(finalize_trigger.fields[5]), "15")
        self.assertEqual(str(finalize_trigger.fields[6]), "34")
        fake_scheduler.start.assert_called_once()

    def test_start_scheduler_registers_global_signal_prefetch_job(self):
        fake_scheduler = MagicMock()
        fake_scheduler.running = False

        with patch.object(core, "scheduler", fake_scheduler):
            with patch.dict(
                "os.environ",
                {
                    "SCHEDULER_ROLE": "trading",
                    "TRADING_ENGINE_ENABLED": "1",
                },
                clear=False,
            ):
                core.start_scheduler()

        registered_ids = [call.kwargs["id"] for call in fake_scheduler.add_job.call_args_list]
        self.assertIn("trading_engine_prefetch_global_signal", registered_ids)
        self.assertIn("trading_engine_cycle_preopen", registered_ids)


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


if __name__ == "__main__":
    unittest.main()
