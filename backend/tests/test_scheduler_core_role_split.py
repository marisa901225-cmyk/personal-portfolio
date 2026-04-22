import unittest
from unittest.mock import MagicMock, patch

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
        self.assertNotIn("trading_engine_cycle_entry_window_open_1", registered_ids)
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
        self.assertIn("trading_engine_cycle_entry_window_open_1", registered_ids)
        self.assertIn("trading_engine_cycle_entry_window_open_2", registered_ids)
        self.assertIn("trading_engine_cycle_intraday_morning", registered_ids)
        self.assertIn("trading_engine_cycle_intraday_midday", registered_ids)
        self.assertIn("trading_engine_cycle_intraday_afternoon", registered_ids)
        self.assertIn("trading_engine_finalize", registered_ids)
        fake_scheduler.start.assert_called_once()


if __name__ == "__main__":
    unittest.main()
