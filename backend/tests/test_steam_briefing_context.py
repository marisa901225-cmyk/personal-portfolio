import os
import sqlite3
import tempfile
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

from backend.services.news.steam import load_monthly_steam_ranking_summary
from backend.services.news.rss import load_recent_inven_game_digest
from backend.services.news.weather_message import (
    _build_weather_snapshot_prefix,
    _ensure_weather_snapshot_prefix,
    _format_weekly_derivatives_briefing,
    _select_culture_context,
)


class SteamBriefingContextTests(unittest.TestCase):
    def _make_db(self) -> str:
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        self.addCleanup(lambda: os.path.exists(tmp.name) and os.remove(tmp.name))

        conn = sqlite3.connect(tmp.name)
        conn.executescript(
            """
            CREATE TABLE game_news (
                id INTEGER PRIMARY KEY,
                source_name TEXT,
                source_type TEXT,
                title TEXT,
                full_content TEXT,
                published_at TEXT
            );
            """
        )
        conn.commit()
        conn.close()
        return tmp.name

    def test_load_monthly_steam_ranking_summary_aggregates_recent_rows(self):
        db_path = self._make_db()
        conn = sqlite3.connect(db_path)
        conn.executemany(
            """
            INSERT INTO game_news (source_name, source_type, title, full_content, published_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    "SteamSpy",
                    "news",
                    "[Steam Ranking] Counter-Strike 2",
                    "Rank: 1\nOwners: 10,000,000\nPositive/Negative: 100/5",
                    "2026-03-17 06:00:00",
                ),
                (
                    "SteamSpy",
                    "news",
                    "[Steam Ranking] Counter-Strike 2",
                    "Rank: 2\nOwners: 9,500,000\nPositive/Negative: 90/6",
                    "2026-03-10 06:00:00",
                ),
                (
                    "SteamSpy",
                    "news",
                    "[Steam Ranking] Apex Legends",
                    "Rank: 3\nOwners: 8,000,000\nPositive/Negative: 80/8",
                    "2026-03-16 06:00:00",
                ),
                (
                    "SteamSpy",
                    "news",
                    "[Steam Ranking] R.E.P.O.",
                    "Rank: 18\nOwners: 2,000,000\nPositive/Negative: 75/9",
                    "2026-03-17 06:00:00",
                ),
                (
                    "SteamSpy",
                    "news",
                    "[Steam Ranking] Schedule I",
                    "Rank: 27\nOwners: 1,500,000\nPositive/Negative: 70/10",
                    "2026-03-16 06:00:00",
                ),
                (
                    "SteamSpy",
                    "news",
                    "[Steam Ranking] Old Game",
                    "Rank: 1\nOwners: 1,000\nPositive/Negative: 10/1",
                    "2026-01-10 06:00:00",
                ),
            ],
        )
        conn.commit()
        conn.close()

        summary = load_monthly_steam_ranking_summary(
            db_path=db_path,
            now=datetime(2026, 3, 18, 7, 0, tzinfo=ZoneInfo("Asia/Seoul")),
            top_games=3,
        )

        self.assertIn("최근 30일 Steam 인기게임 월간 흐름", summary)
        self.assertIn("상위권:", summary)
        self.assertIn("중위권:", summary)
        self.assertIn("Counter-Strike 2(2회 포착, 최신 #1, 보유자 10,000,000)", summary)
        self.assertIn("Apex Legends(1회 포착, 최신 #3, 보유자 8,000,000)", summary)
        self.assertIn("R.E.P.O.(1회 포착, 최신 #18, 보유자 2,000,000)", summary)
        self.assertIn("Schedule I(1회 포착, 최신 #27, 보유자 1,500,000)", summary)
        self.assertNotIn("Old Game", summary)

    def test_load_monthly_steam_ranking_summary_falls_back_to_latest_snapshot(self):
        db_path = self._make_db()
        conn = sqlite3.connect(db_path)
        conn.executemany(
            """
            INSERT INTO game_news (source_name, source_type, title, full_content, published_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    "SteamSpy",
                    "news",
                    "[Steam Ranking] Palworld",
                    "Rank: 4\nOwners: 7,000,000\nPositive/Negative: 70/7",
                    "2026-01-23 05:37:01",
                ),
                (
                    "SteamSpy",
                    "news",
                    "[Steam Ranking] PUBG: BATTLEGROUNDS",
                    "Rank: 5\nOwners: 6,000,000\nPositive/Negative: 60/8",
                    "2026-01-23 05:37:01",
                ),
            ],
        )
        conn.commit()
        conn.close()

        summary = load_monthly_steam_ranking_summary(
            db_path=db_path,
            now=datetime(2026, 3, 18, 7, 0, tzinfo=ZoneInfo("Asia/Seoul")),
            top_games=2,
        )

        self.assertIn("최근 30일 Steam 월간 데이터는 비어 있음.", summary)
        self.assertIn("2026-01-23", summary)
        self.assertIn("Palworld", summary)

    def test_select_culture_context_prefers_lec_then_steam(self):
        self.assertEqual(
            _select_culture_context("최근 LEC 경기 결과: G2 3-1 FNC", "Steam summary", "Inven digest"),
            "최근 LEC 경기 결과: G2 3-1 FNC",
        )
        self.assertEqual(
            _select_culture_context("", "최근 30일 Steam 인기게임 월간 흐름", "최근 Inven 게임 기사"),
            "최근 30일 Steam 인기게임 월간 흐름\n최근 Inven 게임 기사",
        )
        self.assertEqual(_select_culture_context("", "", ""), "없음")

    def test_format_weekly_derivatives_briefing_strips_html(self):
        raw = (
            "<b>[주간 국내 파생심리 브리핑]</b>\n"
            "- 지난주: 점수 33.46 / 상승 우위\n"
            "- 전주: 점수 10.8 / 중립"
        )

        formatted = _format_weekly_derivatives_briefing(raw)

        self.assertTrue(formatted.startswith("주간 국내 파생심리 참고:"))
        self.assertIn("지난주는 점수 33.46로 상승 우위였다.", formatted)
        self.assertIn("전주는 점수 10.8로 중립이었다.", formatted)
        self.assertNotIn("[주간 국내 파생심리 브리핑]", formatted)
        self.assertNotIn("\n-", formatted)
        self.assertNotIn("<b>", formatted)

    def test_load_recent_inven_game_digest_formats_registered_feeds(self):
        db_path = self._make_db()
        conn = sqlite3.connect(db_path)
        conn.executemany(
            """
            INSERT INTO game_news (source_name, source_type, title, full_content, published_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                ("Inven Game Intro", "news", "기대작 소개", "", "2026-03-17 12:00:00"),
                ("Inven Game Review", "news", "액션 RPG 리뷰", "", "2026-03-16 12:00:00"),
                ("Inven Ranking Analysis", "news", "MMO 순위 분석", "", "2026-03-15 12:00:00"),
            ],
        )
        conn.commit()
        conn.close()

        digest = load_recent_inven_game_digest(
            db_path=db_path,
            now=datetime(2026, 3, 18, 7, 0, tzinfo=ZoneInfo("Asia/Seoul")),
        )

        self.assertIn("최근 Inven 게임 기사:", digest)
        self.assertIn("[소개] 기대작 소개", digest)
        self.assertIn("[리뷰] 액션 RPG 리뷰", digest)
        self.assertIn("[순위분석] MMO 순위 분석", digest)

    def test_weather_snapshot_prefix_is_added_when_weather_details_are_missing(self):
        original = "특히 파생상품 시장 쪽을 보면 더 확실해. 오늘은 변동성이 커 보이더라."

        enriched = _ensure_weather_snapshot_prefix(
            text=original,
            temp="12",
            weather_status="구름많음 ☁️",
            pop="30",
            max_temp="20",
        )

        self.assertTrue(enriched.startswith(_build_weather_snapshot_prefix(
            temp="12",
            weather_status="구름많음 ☁️",
            pop="30",
            max_temp="20",
        )))
        self.assertIn(original, enriched)

    def test_weather_snapshot_prefix_is_not_added_when_weather_details_already_exist(self):
        original = (
            "오늘 서울 날씨는 구름많음이고 기온은 12°C야. 낮 최고기온은 20°C, "
            "강수확률은 30% 정도라서 우산은 굳이 필요 없겠어."
        )

        enriched = _ensure_weather_snapshot_prefix(
            text=original,
            temp="12",
            weather_status="구름많음 ☁️",
            pop="30",
            max_temp="20",
        )

        self.assertEqual(enriched, original)
