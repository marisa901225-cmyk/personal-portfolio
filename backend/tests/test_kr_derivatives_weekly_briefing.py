from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core.db import Base
from backend.core.models_misc import KrOptionBoardSnapshot
from backend.services.economy import kr_derivatives_weekly_briefing as briefing


class TestKrDerivativesWeeklyBriefing(unittest.TestCase):
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

        self.legacy_file = Path(self._tmp.name) / "legacy_snapshots.jsonl"
        self.session_patch = patch.object(briefing, "SessionLocal", self.TestSessionLocal)
        self.file_patch = patch.object(briefing, "SNAPSHOT_FILE", self.legacy_file)
        self.session_patch.start()
        self.file_patch.start()
        briefing._LEGACY_MIGRATION_DONE = False

    def tearDown(self) -> None:
        self.file_patch.stop()
        self.session_patch.stop()
        self.engine.dispose()
        briefing._LEGACY_MIGRATION_DONE = False
        self._tmp.cleanup()

    def _write_snapshot(self, **kwargs) -> None:
        collected_at_raw = kwargs.get("collected_at")
        collected_at = datetime.fromisoformat(collected_at_raw) if isinstance(collected_at_raw, str) else datetime.now()
        if collected_at.tzinfo is not None:
            collected_at = collected_at.astimezone(briefing.KST).replace(tzinfo=None)

        row = KrOptionBoardSnapshot(
            collected_at=collected_at,
            trading_date=kwargs.get("trading_date"),
            maturity_month="202602",
            market_cls="",
            call_bid_total=kwargs.get("call_bid_total", 1000),
            call_ask_total=kwargs.get("call_ask_total", 900),
            put_bid_total=kwargs.get("put_bid_total", 900),
            put_ask_total=kwargs.get("put_ask_total", 850),
            call_oi_change_total=kwargs.get("call_oi_change_total", 100),
            put_oi_change_total=kwargs.get("put_oi_change_total", 80),
            bid_pressure=kwargs.get("bid_pressure", 0.05),
            oi_pressure=kwargs.get("oi_pressure", 0.1),
            put_call_bid_ratio=kwargs.get("put_call_bid_ratio", 0.9),
        )
        with self.TestSessionLocal() as db:
            db.add(row)
            db.commit()

    def test_score_week_direction(self) -> None:
        bullish = briefing._score_week(
            {
                "avg_pcr": 0.8,
                "avg_bid_pressure": 0.2,
                "avg_oi_pressure": 0.1,
            }
        )
        bearish = briefing._score_week(
            {
                "avg_pcr": 1.3,
                "avg_bid_pressure": -0.3,
                "avg_oi_pressure": -0.2,
            }
        )
        self.assertGreater(bullish["score"], bearish["score"])

    def test_build_weekly_derivatives_briefing(self) -> None:
        # 전주(2026-01-19~23): 약세 데이터
        for d, pcr, bid, oi in [
            ("20260119", 1.25, -0.20, -0.25),
            ("20260120", 1.22, -0.18, -0.20),
            ("20260121", 1.20, -0.15, -0.18),
            ("20260122", 1.18, -0.10, -0.15),
            ("20260123", 1.16, -0.08, -0.10),
        ]:
            self._write_snapshot(
                collected_at=f"{d[:4]}-{d[4:6]}-{d[6:8]}T15:50:00+09:00",
                trading_date=d,
                put_call_bid_ratio=pcr,
                bid_pressure=bid,
                oi_pressure=oi,
                call_oi_change_total=90,
                put_oi_change_total=180,
            )

        # 지난주(2026-01-26~30): 강세 데이터
        for d, pcr, bid, oi in [
            ("20260126", 0.95, 0.05, 0.08),
            ("20260127", 0.90, 0.09, 0.12),
            ("20260128", 0.88, 0.12, 0.18),
            ("20260129", 0.86, 0.15, 0.20),
            ("20260130", 0.84, 0.18, 0.24),
        ]:
            self._write_snapshot(
                collected_at=f"{d[:4]}-{d[4:6]}-{d[6:8]}T15:50:00+09:00",
                trading_date=d,
                put_call_bid_ratio=pcr,
                bid_pressure=bid,
                oi_pressure=oi,
                call_oi_change_total=180,
                put_oi_change_total=70,
            )

        async def fake_returns(week_windows):
            return {window: 1.5 for window in week_windows}

        now = datetime.fromisoformat("2026-02-02T07:00:00+09:00")
        with patch.object(briefing, "_fetch_kospi_week_returns", side_effect=fake_returns):
            message = asyncio.run(briefing.build_weekly_derivatives_briefing(now=now))

        self.assertIsNotNone(message)
        assert message is not None
        self.assertIn("[주간 국내 파생심리 브리핑]", message)
        self.assertIn("지난주(", message)
        self.assertIn("전주(", message)
        self.assertIn("점수 변화:", message)

    def test_get_latest_option_snapshot_summary(self) -> None:
        self._write_snapshot(
            collected_at="2026-01-30T15:50:00+09:00",
            trading_date="20260130",
            call_bid_total=1200,
            put_bid_total=1000,
            put_call_bid_ratio=0.83,
        )
        self._write_snapshot(
            collected_at="2026-02-02T15:50:00+09:00",
            trading_date="20260202",
            call_bid_total=1500,
            put_bid_total=900,
            put_call_bid_ratio=0.60,
        )

        now = datetime.fromisoformat("2026-02-03T07:00:00+09:00")
        summary = briefing.get_latest_option_snapshot_summary(now=now)

        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertEqual(summary["trading_date"], "20260202")
        self.assertEqual(summary["call_bid_total"], 1500)
        self.assertEqual(summary["put_bid_total"], 900)

    def test_collect_snapshot_upsert_by_trading_date(self) -> None:
        first = briefing.OptionBoardSnapshot(
            collected_at="2026-02-03T15:50:00+09:00",
            trading_date="20260203",
            maturity_month="202602",
            market_cls="",
            call_bid_total=100,
            call_ask_total=200,
            put_bid_total=300,
            put_ask_total=400,
            call_oi_change_total=10,
            put_oi_change_total=20,
            bid_pressure=0.1,
            oi_pressure=0.2,
            put_call_bid_ratio=3.0,
        )
        second = briefing.OptionBoardSnapshot(
            collected_at="2026-02-03T15:55:00+09:00",
            trading_date="20260203",
            maturity_month="202602",
            market_cls="",
            call_bid_total=110,
            call_ask_total=210,
            put_bid_total=310,
            put_ask_total=410,
            call_oi_change_total=11,
            put_oi_change_total=21,
            bid_pressure=0.11,
            oi_pressure=0.21,
            put_call_bid_ratio=2.81,
        )

        briefing._append_snapshot(first)
        briefing._append_snapshot(second)

        with self.TestSessionLocal() as db:
            rows = db.query(KrOptionBoardSnapshot).filter(KrOptionBoardSnapshot.trading_date == "20260203").all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].call_bid_total, 110)

    def test_legacy_jsonl_migration_on_empty_db(self) -> None:
        legacy_payload = {
            "collected_at": "2026-01-31T15:50:00+09:00",
            "trading_date": "20260131",
            "maturity_month": "202602",
            "market_cls": "",
            "call_bid_total": 1000,
            "call_ask_total": 900,
            "put_bid_total": 800,
            "put_ask_total": 700,
            "call_oi_change_total": 50,
            "put_oi_change_total": 30,
            "bid_pressure": 0.11,
            "oi_pressure": 0.22,
            "put_call_bid_ratio": 0.8,
        }
        self.legacy_file.write_text(f"{json.dumps(legacy_payload, ensure_ascii=False)}\n", encoding="utf-8")
        briefing._LEGACY_MIGRATION_DONE = False

        summary = briefing.get_latest_option_snapshot_summary(
            now=datetime.fromisoformat("2026-02-01T07:00:00+09:00")
        )
        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertEqual(summary["trading_date"], "20260131")


if __name__ == "__main__":
    unittest.main()
