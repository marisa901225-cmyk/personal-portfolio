from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("PANDASCORE_API_KEY", "test-key")

from backend.core.db import Base
from backend.core.models_misc import EsportsMatch
from backend.services.news.esports_monitor import EsportsMonitor


class TestEsportsMonitor(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test.db"
        self.engine = create_engine(
            f"sqlite:///{self.db_path.as_posix()}",
            connect_args={"check_same_thread": False},
            future=True,
        )
        Base.metadata.create_all(bind=self.engine)
        self.TestSessionLocal = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            future=True,
        )
        self.monitor = EsportsMonitor()

    def tearDown(self) -> None:
        self.engine.dispose()
        self._tmp.cleanup()

    def test_update_esports_cache_promotes_match_to_running_with_international_tag(self) -> None:
        with self.TestSessionLocal() as db:
            db.add(
                EsportsMatch(
                    match_id=1384019,
                    league_id=1,
                    serie_id=10,
                    tournament_id=20,
                    videogame="league-of-legends",
                    name="GEN vs JDG",
                    status="not_started",
                    scheduled_at=datetime(2026, 3, 17, 13, 0),
                )
            )
            db.commit()

            running_ids, pending_notifications = self.monitor._update_esports_cache(
                db,
                [
                    {
                        "id": 1384019,
                        "_videogame": "league-of-legends",
                        "league": {"name": "First Stand 2026", "id": 1},
                        "serie": {"id": 10},
                        "tournament": {"id": 20},
                        "name": "GEN vs JDG",
                        "scheduled_at": "2026-03-17T13:00:00Z",
                        "begin_at": "2026-03-17T13:05:00Z",
                        "official_stream_url": "https://example.com/live",
                    }
                ],
            )

            match = db.query(EsportsMatch).filter(EsportsMatch.match_id == 1384019).one()
            self.assertEqual(running_ids, {1384019})
            self.assertEqual(match.status, "running")
            self.assertIsNotNone(match.start_notified_at)
            self.assertEqual(len(pending_notifications), 1)
            self.assertEqual(pending_notifications[0]["league_tag"], "Worlds/MSI")

    def test_has_imminent_match_keeps_short_grace_after_scheduled_start(self) -> None:
        with self.TestSessionLocal() as db:
            db.add(
                EsportsMatch(
                    match_id=2001,
                    videogame="league-of-legends",
                    name="Late Match",
                    status="not_started",
                    scheduled_at=datetime(2026, 3, 17, 17, 0),
                )
            )
            db.commit()

            with patch("backend.services.news.esports_monitor.utcnow", return_value=datetime(2026, 3, 17, 17, 5)):
                self.assertTrue(self.monitor._has_imminent_match(db))

            with patch("backend.services.news.esports_monitor.utcnow", return_value=datetime(2026, 3, 17, 17, 31)):
                self.assertFalse(self.monitor._has_imminent_match(db))
