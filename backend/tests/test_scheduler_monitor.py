# backend/tests/test_scheduler_monitor.py
import asyncio
import unittest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch

from backend.core.db import Base, engine
from backend.main import app
from backend.services.retry import async_retry, sync_retry
from backend.services.scheduler import core
from backend.services import scheduler_monitor


class _FakeSchedulerState:
    job_id = "job_id"

    def __init__(self, job_id: str):
        self.job_id = job_id
        self.status = None
        self.last_run_at = None
        self.last_success_at = None
        self.last_failure_at = None
        self.message = None


class TestSchedulerMonitor(unittest.TestCase):
    def _build_db(self, existing_state=None):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = existing_state
        return db

    def test_monitor_job_success_creates_and_marks_success(self):
        db = self._build_db(existing_state=None)

        with patch.object(scheduler_monitor, "SchedulerState", _FakeSchedulerState):
            with scheduler_monitor.monitor_job("job-1", db):
                pass

        state = db.add.call_args[0][0]
        self.assertEqual(state.job_id, "job-1")
        self.assertEqual(state.status, "success")
        self.assertIsNotNone(state.last_run_at)
        self.assertIsNotNone(state.last_success_at)
        self.assertIsNone(state.message)
        self.assertGreaterEqual(db.commit.call_count, 2)

    def test_monitor_job_failure_marks_failure_and_reraises(self):
        db = self._build_db(existing_state=None)

        with patch.object(scheduler_monitor, "SchedulerState", _FakeSchedulerState):
            with self.assertRaises(ValueError):
                with scheduler_monitor.monitor_job("job-2", db):
                    raise ValueError("boom")

        state = db.add.call_args[0][0]
        self.assertEqual(state.job_id, "job-2")
        self.assertEqual(state.status, "failure")
        self.assertIsNotNone(state.last_run_at)
        self.assertIsNotNone(state.last_failure_at)
        self.assertEqual(state.message, "boom")
        self.assertGreaterEqual(db.commit.call_count, 2)

    def test_monitor_job_uses_existing_state(self):
        existing = _FakeSchedulerState("existing-job")
        db = self._build_db(existing_state=existing)

        with patch.object(scheduler_monitor, "SchedulerState", _FakeSchedulerState):
            with scheduler_monitor.monitor_job("existing-job", db):
                pass

        # Should not call db.add for existing state
        db.add.assert_not_called()
        self.assertEqual(existing.status, "success")

    def test_monitor_job_async_failure_marks_failure_and_notifies(self):
        async def _run():
            db = self._build_db(existing_state=None)

            with patch.object(scheduler_monitor, "SchedulerState", _FakeSchedulerState):
                with patch.object(
                    scheduler_monitor,
                    "send_telegram_message",
                    new=AsyncMock(return_value=True),
                ) as mock_send:
                    with self.assertRaises(ValueError):
                        async with scheduler_monitor.monitor_job_async("job-async", db):
                            raise ValueError("async-boom")

            state = db.add.call_args[0][0]
            self.assertEqual(state.status, "failure")
            self.assertEqual(state.message, "async-boom")
            mock_send.assert_awaited_once()

        asyncio.run(_run())


class TestSchedulerSupport(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        Base.metadata.create_all(bind=engine)
        self.client = TestClient(app)

    def tearDown(self):
        Base.metadata.drop_all(bind=engine)

    def test_get_scheduler_state(self):
        from backend.core.auth import verify_api_token

        app.dependency_overrides[verify_api_token] = lambda: True
        try:
            response = self.client.get("/api/scheduler/state")
            self.assertEqual(response.status_code, 200)
            self.assertIsInstance(response.json(), list)
        finally:
            app.dependency_overrides.clear()

    def test_sync_retry_succeeds_after_failure(self):
        mock_func = MagicMock()
        mock_func.side_effect = [ValueError("Transient"), ValueError("Transient"), "Success"]

        with patch("tenacity.nap.time.sleep", side_effect=None):
            result = sync_retry(mock_func)()

        self.assertEqual(result, "Success")
        self.assertEqual(mock_func.call_count, 3)

    async def test_async_retry_succeeds_after_failure(self):
        mock_func = MagicMock()

        async def side_effect_func(*args, **kwargs):
            del args, kwargs
            val = mock_func()
            if isinstance(val, Exception):
                raise val
            return val

        mock_func.side_effect = [ValueError("Transient"), "Success"]

        with patch("tenacity.nap.time.sleep", side_effect=None):
            result = await async_retry(side_effect_func)()

        self.assertEqual(result, "Success")
        self.assertEqual(mock_func.call_count, 2)

    def test_sync_retry_fails_after_max_attempts(self):
        mock_func = MagicMock()
        mock_func.side_effect = ValueError("Permanent")

        with patch("tenacity.nap.time.sleep", side_effect=None):
            with self.assertRaises(ValueError):
                sync_retry(mock_func)()

        self.assertEqual(mock_func.call_count, 3)


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
        self.assertIn("cleanup_old_spam_data", registered_ids)
        self.assertNotIn("trading_engine_cycle_preopen", registered_ids)
        self.assertNotIn("trading_engine_cycle_intraday_morning", registered_ids)
        self.assertNotIn("trading_engine_finalize", registered_ids)

        cleanup_call = next(
            call for call in fake_scheduler.add_job.call_args_list if call.kwargs["id"] == "cleanup_old_spam_data"
        )
        cleanup_trigger = cleanup_call.args[1]
        self.assertEqual(str(cleanup_trigger.fields[4]), "sun")
        self.assertEqual(str(cleanup_trigger.fields[5]), "4")
        self.assertEqual(str(cleanup_trigger.fields[6]), "30")
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
        self.assertNotIn("cleanup_old_spam_data", registered_ids)
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
