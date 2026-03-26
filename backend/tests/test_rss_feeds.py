import unittest

from backend.services.news.core import RSS_FEEDS
from backend.services.news.rss import _infer_rss_metadata


class RssFeedRegistryTests(unittest.TestCase):
    def test_inven_game_feeds_are_registered(self):
        self.assertEqual(
            RSS_FEEDS.get("Inven Game Intro"),
            "https://webzine.inven.co.kr/news/rss.php?sclass=12",
        )
        self.assertEqual(
            RSS_FEEDS.get("Inven Game Review"),
            "https://webzine.inven.co.kr/news/rss.php?sclass=11",
        )
        self.assertEqual(
            RSS_FEEDS.get("Inven Ranking Analysis"),
            "https://webzine.inven.co.kr/news/rss.php?sclass=26",
        )

    def test_infer_rss_metadata_for_game_feeds(self):
        self.assertEqual(
            _infer_rss_metadata("Inven Game Intro", "신작 소개 기사"),
            ("Gaming", "Preview"),
        )
        self.assertEqual(
            _infer_rss_metadata("Inven Game Review", "RPG 리뷰"),
            ("Gaming", "Review"),
        )
        self.assertEqual(
            _infer_rss_metadata("Inven Ranking Analysis", "MMORPG 순위 분석"),
            ("Gaming", "Ranking"),
        )
