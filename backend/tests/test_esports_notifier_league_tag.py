from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from backend.services.news import esports_notifier

KST = timezone(timedelta(hours=9))


class TestEsportsNotifierLeagueTag(IsolatedAsyncioTestCase):
    async def test_notify_match_start_respects_explicit_lck_cl_tag(self) -> None:
        with patch.object(
            esports_notifier,
            "now_kst",
            return_value=datetime(2026, 2, 9, 14, 5, tzinfo=KST),  # Monday
        ), patch.object(
            esports_notifier, "send_telegram_message", new=AsyncMock()
        ) as send_mock:
            ok = await esports_notifier.notify_match_start(
                match_id=1310969,
                videogame="league-of-legends",
                name="Upper bracket quarterfinal 1: NS.EA vs HLE",
                league_tag="LCK-CL",
            )
            self.assertTrue(ok)
            send_mock.assert_awaited_once()

    async def test_notify_match_start_without_league_tag_can_be_skipped(self) -> None:
        with patch.object(
            esports_notifier,
            "now_kst",
            return_value=datetime(2026, 2, 9, 14, 5, tzinfo=KST),  # Monday
        ), patch.object(
            esports_notifier, "send_telegram_message", new=AsyncMock()
        ) as send_mock:
            ok = await esports_notifier.notify_match_start(
                match_id=1310969,
                videogame="league-of-legends",
                name="Upper bracket quarterfinal 1: NS.EA vs HLE",
            )
            self.assertTrue(ok)
            send_mock.assert_not_awaited()

    async def test_notify_pre_match_respects_explicit_lck_cl_tag(self) -> None:
        with patch.object(
            esports_notifier,
            "now_kst",
            return_value=datetime(2026, 2, 9, 13, 55, tzinfo=KST),  # Monday
        ), patch.object(
            esports_notifier, "send_telegram_message", new=AsyncMock()
        ) as send_mock:
            ok = await esports_notifier.notify_pre_match(
                match_id=1310969,
                name="Upper bracket quarterfinal 1: NS.EA vs HLE",
                scheduled_at=datetime(2026, 2, 9, 5, 0, tzinfo=timezone.utc).replace(
                    tzinfo=None
                ),
                videogame="league-of-legends",
                league_tag="LCK-CL",
            )
            self.assertTrue(ok)
            send_mock.assert_awaited_once()
