import unittest
from unittest.mock import MagicMock, patch
import asyncio
from backend.services.retry import async_retry, sync_retry

class TestSchedulerRetry(unittest.IsolatedAsyncioTestCase):
    def test_sync_retry_succeeds_after_failure(self):
        mock_func = MagicMock()
        # Fail twice, then succeed
        mock_func.side_effect = [ValueError("Transient"), ValueError("Transient"), "Success"]
        
        # We need to reduce the wait time for tests
        with patch("tenacity.nap.time.sleep", side_effect=None):
            result = sync_retry(mock_func)()
            
        self.assertEqual(result, "Success")
        self.assertEqual(mock_func.call_count, 3)

    async def test_async_retry_succeeds_after_failure(self):
        mock_func = MagicMock()
        # Async mock function
        async def side_effect_func(*args, **kwargs):
            val = mock_func()
            if isinstance(val, Exception):
                raise val
            return val
            
        mock_func.side_effect = [ValueError("Transient"), "Success"]
        
        # We need to reduce the wait time for tests
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

if __name__ == "__main__":
    unittest.main()
