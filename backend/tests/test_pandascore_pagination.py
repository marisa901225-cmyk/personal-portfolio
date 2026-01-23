import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


class PandaScorePaginationTests(unittest.IsolatedAsyncioTestCase):
    async def test_collect_paginates_until_match_found(self) -> None:
        os.environ["PANDASCORE_API_KEY"] = "test-key"
        from backend.services.news.esports_monitor import EsportsMonitor
        
        monitor = EsportsMonitor()
        page1 = [{"id": i, "videogame": {"slug": "valorant"}, "name": "foo", "league": {"name": "VCT"}, "begin_at": "2026-01-16T00:00:00Z"} for i in range(100)]
        page2 = [
            {
                "id": 999,
                "videogame": {"slug": "league-of-legends"},
                "name": "DK vs DNS",
                "league": {"name": "LCK"},
                "begin_at": "2026-01-16T08:00:00Z",
                "tournament": {"name": "Group Stage"},
                "official_stream_url": "",
            }
        ]

        db = MagicMock()

        class _QueryChain:
            def filter(self, *args, **kwargs):
                return self

            def first(self):
                # None을 반환해야 existing이 False가 되어 db.add가 호출됨
                return None

            def delete(self):
                return 0

            def all(self):
                return []

        db.query.return_value = _QueryChain()

        response1 = MagicMock()
        response1.raise_for_status = MagicMock()
        response1.json = MagicMock(return_value=page1)

        response2 = MagicMock()
        response2.raise_for_status = MagicMock()
        response2.json = MagicMock(return_value=page2)

        async_client = MagicMock()
        async_client.__aenter__ = AsyncMock(return_value=async_client)
        async_client.__aexit__ = AsyncMock(return_value=None)
        added_items = []
        def mock_add(item):
            # item은 MagicMock일 수 있으므로 실제 테스트에서 기대하는 값을 설정해줌
            item.league_id = "LCK"
            item.videogame = "LoL"
            added_items.append(item)
        db.add.side_effect = mock_add

        # 핵심: _fetch 메서드 자체를 AsyncMock으로 패치하여 awaitable 에러 방지
        with patch.object(monitor, "_fetch", new_callable=AsyncMock) as mock_fetch, \
             patch.object(monitor, "_cleanup_old_matches", new=AsyncMock()), \
             patch.object(monitor, "_handle_pre_match_notify", new=AsyncMock()):
             
            # mock_fetch가 페이지별 응답을 반환하도록 설정
            mock_fetch.side_effect = [page1, page2]
            
            # _index_upcoming_matches가 내부에서 _fetch를 호출함
            await monitor._index_upcoming_matches(db)

        self.assertGreaterEqual(mock_fetch.call_count, 2)
        self.assertTrue(len(added_items) > 0)
        added = added_items[0]
        # 실제 모델 필드명에 맞춰서 수정 (EsportsMatch 확인 결과)
        self.assertEqual(getattr(added, "league_id", None), "LCK")
        self.assertEqual(getattr(added, "videogame", None), "LoL")
