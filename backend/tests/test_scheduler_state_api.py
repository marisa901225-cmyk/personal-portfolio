import unittest
from fastapi.testclient import TestClient
from datetime import datetime
from backend.main import app
from backend.core.db import get_db, Base, engine
from backend.core.models import SchedulerState
from sqlalchemy.orm import Session

class TestSchedulerStateApi(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        # We need a valid token to bypass dependencies=[Depends(verify_api_token)]
        # However, for simplicity in tests, we can mock the dependency or use a known one.
        # Here we'll just test the logic if possible.
        
    def test_get_scheduler_state(self):
        # We need to mock the dependency in the app, not just the function call
        from backend.core.auth import verify_api_token
        app.dependency_overrides[verify_api_token] = lambda: True
        
        try:
            response = self.client.get("/api/scheduler/state")
            self.assertEqual(response.status_code, 200)
            self.assertIsInstance(response.json(), list)
        finally:
            app.dependency_overrides.clear()

if __name__ == "__main__":
    unittest.main()
