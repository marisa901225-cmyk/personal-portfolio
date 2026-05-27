from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from backend.core.esports_config import (
    infer_league_tag_from_name,
    is_league_in_active_window,
    is_valid_competitive_match,
    lol_league_tagger,
)
from backend.services.news import esports_notifier

KST = timezone(timedelta(hours=9))


def test_lol_league_tagger_maps_international_events() -> None:
    for league_name in (
        "First Stand 2026",
        "First-Stand 2026",
        "Mid-Season Invitational 2026",
        "2026 World Championship",
        "Esports World Cup 2026",
        "EWC 2026",
    ):
        assert lol_league_tagger({"league": {"name": league_name}}) == "Worlds/MSI"


def test_infer_league_tag_from_name_recognizes_international_and_major_regions() -> None:
    assert (
        infer_league_tag_from_name(
            "GEN vs JDG - First Stand 2026",
            "league-of-legends",
        )
        == "Worlds/MSI"
    )
    assert (
        infer_league_tag_from_name(
            "FNC vs G2 - LEC Spring 2026",
            "league-of-legends",
        )
        == "LEC"
    )
    assert (
        infer_league_tag_from_name(
            "NS.EA vs HLE - LCK Challengers Spring 2026",
            "league-of-legends",
        )
        == "LCK-CL"
    )


def test_is_valid_competitive_match_accepts_vct_main_event() -> None:
    assert is_valid_competitive_match(
        {
            "league": {"name": "Valorant Champions Tour 2026"},
            "serie": {"full_name": "VCT 2026: Pacific Stage 1"},
            "tournament": {"name": "Regular Season"},
            "name": "GEN.G vs DRX",
        },
        "valorant",
    )


def test_is_valid_competitive_match_rejects_game_changers_even_with_parent_vct_name() -> None:
    assert not is_valid_competitive_match(
        {
            "league": {"name": "Valorant Champions Tour 2026"},
            "serie": {"full_name": "Game Changers North America Stage 1 2026"},
            "tournament": {"name": "Main Event"},
            "name": "SR GC vs FLY GC",
        },
        "valorant",
    )


def test_lpl_window_crosses_midnight_correctly() -> None:
    # LPL은 14:30 ~ 익일 01:00 윈도우를 사용한다.
    assert is_league_in_active_window("LPL", "league-of-legends", 0, 23 * 60)
    assert is_league_in_active_window("LPL", "league-of-legends", 1, 30)
    assert not is_league_in_active_window("LPL", "league-of-legends", 1, 60)
    assert not is_league_in_active_window("LPL", "league-of-legends", 0, 14 * 60)


class TestEsportsNotifierLeagueTag(IsolatedAsyncioTestCase):
    async def test_notify_match_start_respects_explicit_lck_cl_tag(self) -> None:
        with patch.object(
            esports_notifier,
            "now_kst",
            return_value=datetime(2026, 2, 9, 14, 5, tzinfo=KST),
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
            return_value=datetime(2026, 2, 9, 14, 5, tzinfo=KST),
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
            return_value=datetime(2026, 2, 9, 13, 55, tzinfo=KST),
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
