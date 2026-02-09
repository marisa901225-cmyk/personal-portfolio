from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from backend.services.economy import kr_derivatives_weekly_briefing as briefing


class TestKrDerivativesWeeklyBriefing(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.snapshot_dir = Path(self._tmp.name)
        self.snapshot_file = self.snapshot_dir / "snapshots.jsonl"

        self.dir_patch = patch.object(briefing, "SNAPSHOT_DIR", self.snapshot_dir)
        self.file_patch = patch.object(briefing, "SNAPSHOT_FILE", self.snapshot_file)
        self.dir_patch.start()
        self.file_patch.start()

    def tearDown(self) -> None:
        self.file_patch.stop()
        self.dir_patch.stop()
        self._tmp.cleanup()

    def _write_snapshot(self, **kwargs) -> None:
        payload = {
            "collected_at": kwargs.get("collected_at"),
            "trading_date": kwargs.get("trading_date"),
            "maturity_month": "202602",
            "market_cls": "",
            "call_bid_total": kwargs.get("call_bid_total", 1000),
            "call_ask_total": kwargs.get("call_ask_total", 900),
            "put_bid_total": kwargs.get("put_bid_total", 900),
            "put_ask_total": kwargs.get("put_ask_total", 850),
            "call_oi_change_total": kwargs.get("call_oi_change_total", 100),
            "put_oi_change_total": kwargs.get("put_oi_change_total", 80),
            "bid_pressure": kwargs.get("bid_pressure", 0.05),
            "oi_pressure": kwargs.get("oi_pressure", 0.1),
            "put_call_bid_ratio": kwargs.get("put_call_bid_ratio", 0.9),
        }
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        with open(self.snapshot_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")

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


if __name__ == "__main__":
    unittest.main()

