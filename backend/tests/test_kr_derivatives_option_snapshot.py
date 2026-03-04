import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from backend.services.economy import kr_derivatives_weekly_briefing as briefing


KST = ZoneInfo("Asia/Seoul")


class TestKrDerivativesOptionSnapshot(unittest.IsolatedAsyncioTestCase):
    async def test_collect_snapshot_switches_to_next_maturity_when_primary_empty(self) -> None:
        empty_payload = {
            "rt_cd": "0",
            "output1": [{"total_bidp_rsqn": "0", "total_askp_rsqn": "0", "otst_stpl_qty_icdc": "0"}],
            "output2": [{"total_bidp_rsqn": "0", "total_askp_rsqn": "0", "otst_stpl_qty_icdc": "0"}],
        }
        active_payload = {
            "rt_cd": "0",
            "output1": [{"total_bidp_rsqn": "100", "total_askp_rsqn": "80", "otst_stpl_qty_icdc": "10"}],
            "output2": [{"total_bidp_rsqn": "120", "total_askp_rsqn": "70", "otst_stpl_qty_icdc": "12"}],
        }

        fetch_mock = AsyncMock(side_effect=[empty_payload, active_payload])
        with (
            patch("backend.integrations.kis.kis_client.get_options_display_board", new=fetch_mock),
            patch.object(briefing, "_append_snapshot") as append_mock,
        ):
            snapshot = await briefing.collect_option_board_snapshot(maturity_month=None)

        self.assertIsNotNone(snapshot)
        self.assertTrue(briefing._has_activity(snapshot))  # noqa: SLF001 - internal helper verification
        self.assertEqual(fetch_mock.await_count, 2)

        first_month = fetch_mock.await_args_list[0].kwargs["maturity_month"]
        second_month = fetch_mock.await_args_list[1].kwargs["maturity_month"]
        self.assertEqual(second_month, briefing._next_month_yyyymm(first_month))  # noqa: SLF001
        self.assertEqual(snapshot.maturity_month, second_month)
        append_mock.assert_called_once()

    async def test_collect_snapshot_skips_when_all_months_empty(self) -> None:
        empty_payload = {
            "rt_cd": "0",
            "output1": [{"total_bidp_rsqn": "0", "total_askp_rsqn": "0", "otst_stpl_qty_icdc": "0"}],
            "output2": [{"total_bidp_rsqn": "0", "total_askp_rsqn": "0", "otst_stpl_qty_icdc": "0"}],
        }

        fetch_mock = AsyncMock(side_effect=[empty_payload, empty_payload])
        with (
            patch("backend.integrations.kis.kis_client.get_options_display_board", new=fetch_mock),
            patch.object(briefing, "_append_snapshot") as append_mock,
        ):
            snapshot = await briefing.collect_option_board_snapshot(maturity_month=None)

        self.assertIsNone(snapshot)
        append_mock.assert_not_called()

    def test_latest_summary_prefers_recent_active_snapshot(self) -> None:
        active = briefing.OptionBoardSnapshot(
            collected_at=datetime(2026, 2, 24, 15, 50, tzinfo=KST).isoformat(),
            trading_date="20260224",
            maturity_month="202603",
            market_cls="",
            call_bid_total=100,
            call_ask_total=80,
            put_bid_total=120,
            put_ask_total=70,
            call_oi_change_total=10,
            put_oi_change_total=12,
            bid_pressure=0.0,
            oi_pressure=0.0,
            put_call_bid_ratio=1.2,
        )
        empty_newer = briefing.OptionBoardSnapshot(
            collected_at=datetime(2026, 2, 25, 15, 50, tzinfo=KST).isoformat(),
            trading_date="20260225",
            maturity_month="202602",
            market_cls="",
            call_bid_total=0,
            call_ask_total=0,
            put_bid_total=0,
            put_ask_total=0,
            call_oi_change_total=0,
            put_oi_change_total=0,
            bid_pressure=0.0,
            oi_pressure=0.0,
            put_call_bid_ratio=1.0,
        )

        with patch.object(briefing, "_load_snapshots", return_value=[active, empty_newer]):
            summary = briefing.get_latest_option_snapshot_summary(
                now=datetime(2026, 2, 26, 7, 0, tzinfo=KST),
                days=14,
            )

        self.assertIsNotNone(summary)
        self.assertEqual(summary["trading_date"], "20260224")
        self.assertEqual(summary["put_call_bid_ratio"], 1.2)


if __name__ == "__main__":
    unittest.main()
