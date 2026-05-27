import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["API_TOKEN"] = "test-token"

from backend.main import app  # noqa: E402
from backend.core import auth as auth_module  # noqa: E402
from backend.core.auth import create_access_token  # noqa: E402
from backend.core.db import Base, get_db  # noqa: E402
from backend.core.models import SpamRule  # noqa: E402
from backend.services.spam_rule_service import (  # noqa: E402
    create_spam_rule,
    delete_spam_rule,
    get_recent_spam_rules,
    list_spam_rules,
    set_spam_rule_enabled,
)


class SpamRulesTests(unittest.TestCase):
    def setUp(self) -> None:
        self._original_api_token = auth_module.API_TOKEN
        auth_module.API_TOKEN = "test-token"
        self.engine = create_engine(
            "sqlite://",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, autocommit=False, future=True)

        def _override_get_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = _override_get_db
        self.client = TestClient(app)
        self.headers = {
            "X-API-Token": "test-token",
            "Authorization": f"Bearer {create_access_token({'sub': 'test-user'})}",
        }
        db = self.SessionLocal()
        try:
            db.query(SpamRule).delete()
            db.commit()
        finally:
            db.close()

    def tearDown(self) -> None:
        auth_module.API_TOKEN = self._original_api_token
        app.dependency_overrides.clear()
        self.engine.dispose()

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


class SpamRuleServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self._tmpdir.name) / "spam_rules_test.db"
        self.engine = create_engine(f"sqlite:///{db_path}", future=True)
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, autocommit=False, future=True)

    def tearDown(self) -> None:
        self.engine.dispose()
        self._tmpdir.cleanup()

    def test_crud_flow(self) -> None:
        db = self.SessionLocal()
        try:
            created = create_spam_rule(
                db,
                rule_type="contains",
                pattern="promo",
                category="general",
                note="test",
            )
            self.assertEqual(created.pattern, "promo")
            self.assertTrue(created.is_enabled)

            listed = list_spam_rules(db)
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0].id, created.id)

            toggled = set_spam_rule_enabled(db, created.id, enabled=False)
            self.assertFalse(toggled.is_enabled)

            recent = get_recent_spam_rules(db, limit=10)
            self.assertEqual(len(recent), 1)

            delete_spam_rule(db, created.id)
            self.assertEqual(list_spam_rules(db), [])
        finally:
            db.close()
