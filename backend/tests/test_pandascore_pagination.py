import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


class PandaScorePaginationTests(unittest.IsolatedAsyncioTestCase):
    async def test_collect_paginates_until_match_found(self) -> None:
        os.environ["PANDASCORE_API_KEY"] = "test-key"
        from backend.services.news import esports as esports_module

        db = MagicMock()

        class _QueryChain:
            def filter(self, *args, **kwargs):
                return self

            def first(self):
                return None

            def delete(self):
                return 0

            def all(self):
                return []

        db.query.return_value = _QueryChain()

        page1 = [{"videogame": {"name": "Valorant"}, "name": "foo", "league": {"name": "VCT"}, "begin_at": "2026-01-16T00:00:00Z"}] * 100
        page2 = [
            {
                "videogame": {"name": "League of Legends"},
                "name": "DK vs DNS",
                "league": {"name": "LCK"},
                "begin_at": "2026-01-16T08:00:00Z",
                "tournament": {"name": "Group Stage"},
                "official_stream_url": "",
            }
        ]

        response1 = MagicMock()
        response1.raise_for_status = MagicMock()
        response1.json = MagicMock(return_value=page1)

        response2 = MagicMock()
        response2.raise_for_status = MagicMock()
        response2.json = MagicMock(return_value=page2)

        async_client = MagicMock()
        async_client.__aenter__ = AsyncMock(return_value=async_client)
        async_client.__aexit__ = AsyncMock(return_value=None)
        async_client.get = AsyncMock(side_effect=[response1, response2])

        with patch.object(esports_module, "cleanup_old_schedules", new=AsyncMock()), patch(
            "backend.services.news.esports.httpx.AsyncClient",
            return_value=async_client,
        ):
            await esports_module.collect_pandascore_schedules(db)

        self.assertGreaterEqual(async_client.get.await_count, 2)
        self.assertTrue(db.add.called)
        added = db.add.call_args[0][0]
        self.assertEqual(getattr(added, "league_tag", None), "LCK")
        self.assertEqual(getattr(added, "game_tag", None), "LoL")
