# backend/tests/test_scheduler_monitor.py
import unittest
from unittest.mock import MagicMock, patch

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


if __name__ == "__main__":
    unittest.main()
