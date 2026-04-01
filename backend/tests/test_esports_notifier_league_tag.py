from __future__ import annotations

from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
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

    async def test_notify_match_finished_sends_even_outside_active_window(self) -> None:
        match = SimpleNamespace(
            match_id=1384019,
            finished_notified_at=None,
            videogame="league-of-legends",
            name="GEN vs JDG",
        )
        api_data = {
            "league": {"name": "First Stand 2026"},
            "winner": {"name": "GEN"},
        }

        with patch.object(
            esports_notifier,
            "now_kst",
            return_value=datetime(2026, 3, 18, 2, 25, tzinfo=KST),
        ), patch.object(
            esports_notifier, "send_telegram_message", new=AsyncMock()
        ) as send_mock:
            ok = await esports_notifier.notify_match_finished(match, api_data)
            self.assertTrue(ok)
            send_mock.assert_awaited_once()
            self.assertIsNotNone(match.finished_notified_at)
