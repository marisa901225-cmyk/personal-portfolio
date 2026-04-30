import unittest
from unittest.mock import MagicMock, patch

from backend.services.scheduler import core


class TestTradingEngineGlobalSignalScheduler(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
