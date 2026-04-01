import unittest
import tempfile
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core.db import Base
from backend.core.models import SpamRule
from backend.services.spam_rule_service import (
    create_spam_rule,
    delete_spam_rule,
    get_recent_spam_rules,
    list_spam_rules,
    set_spam_rule_enabled,
)


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


if __name__ == "__main__":
    unittest.main()
