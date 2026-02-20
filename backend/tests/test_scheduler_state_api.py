import unittest
from fastapi.testclient import TestClient
from datetime import datetime
from backend.main import app
from backend.core.db import get_db, Base, engine
from backend.core.models import SchedulerState
from sqlalchemy.orm import Session

class TestSchedulerStateApi(unittest.TestCase):
    def setUp(self):
        # 테스트 전용 테이블 생성
        Base.metadata.create_all(bind=engine)
        self.client = TestClient(app)
        
    def tearDown(self):
        # 테스트 후 테이블 삭제 (독립성 보장)
        Base.metadata.drop_all(bind=engine)
        
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
