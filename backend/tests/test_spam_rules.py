import os
import tempfile
import unittest

from fastapi.testclient import TestClient

_temp_dir = tempfile.TemporaryDirectory()
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_temp_dir.name}/test.db")
os.environ["API_TOKEN"] = "test-token"

from backend.main import app  # noqa: E402
from backend.core.db import SessionLocal  # noqa: E402
from backend.core.models import SpamRule  # noqa: E402


class SpamRulesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.headers = {"X-API-Token": "test-token"}
        db = SessionLocal()
        try:
            db.query(SpamRule).delete()
            db.commit()
        finally:
            db.close()

    def test_requires_api_token(self) -> None:
        response = self.client.get("/api/spam-rules")
        self.assertEqual(response.status_code, 401)

    def test_create_and_list_rules(self) -> None:
        payload = {
            "rule_type": "contains",
            "pattern": "promo",
            "category": "general",
            "note": "test",
        }
        create_response = self.client.post(
            "/api/spam-rules",
            headers=self.headers,
            json=payload,
        )
        self.assertEqual(create_response.status_code, 200)
        created = create_response.json()
        self.assertEqual(created["pattern"], "promo")

        list_response = self.client.get("/api/spam-rules", headers=self.headers)
        self.assertEqual(list_response.status_code, 200)
        rules = list_response.json()
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["pattern"], "promo")
