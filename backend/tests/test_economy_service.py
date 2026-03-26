import unittest
import sys
import types
import os
import sqlite3
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo

fredapi_stub = types.ModuleType("fredapi")
pydantic_stub = types.ModuleType("pydantic")
pydantic_settings_stub = types.ModuleType("pydantic_settings")
fred_client_module_stub = types.ModuleType("backend.integrations.fred.fred_client")
ecos_client_module_stub = types.ModuleType("backend.services.economy.ecos_client")


class _DummyFred:
    def __init__(self, *args, **kwargs):
        pass


fredapi_stub.Fred = _DummyFred
sys.modules.setdefault("fredapi", fredapi_stub)


def _field_stub(default=None, *, default_factory=None, **kwargs):
    del kwargs
    if default_factory is not None:
        return default_factory()
    return default


class _BaseSettingsStub:
    def __init__(self, **kwargs):
        annotations = getattr(self.__class__, "__annotations__", {})
        for name in annotations:
            if name in kwargs:
                value = kwargs[name]
            else:
                value = getattr(self.__class__, name, None)
            setattr(self, name, value)


class _SettingsConfigDictStub(dict):
    pass


pydantic_stub.Field = _field_stub
pydantic_settings_stub.BaseSettings = _BaseSettingsStub
pydantic_settings_stub.SettingsConfigDict = _SettingsConfigDictStub

sys.modules.setdefault("pydantic", pydantic_stub)
sys.modules.setdefault("pydantic_settings", pydantic_settings_stub)


class _FredClientStub:
    def get_vix(self):
        return None


class _EcosClientStub:
    pass


fred_client_module_stub.fred_client = _FredClientStub()
ecos_client_module_stub.ecos_client = _EcosClientStub()

sys.modules.setdefault("backend.integrations.fred.fred_client", fred_client_module_stub)
sys.modules.setdefault("backend.services.economy.ecos_client", ecos_client_module_stub)

from backend.services.economy.economy_service import EconomyService
from backend.services.news.core import determine_news_tags


class EconomyServiceFormatSnapshotTests(unittest.TestCase):
    def test_format_snapshot_includes_previous_kospi_close(self):
        snapshot = {
            "us": {},
            "kr": {
                "kospi": 2630.12,
                "kospi_daily": {
                    "output2": [
                        {
                            "stck_bsop_date": "20260307",
                            "bstp_nmix_prpr": "2617.78",
                        },
                        {
                            "stck_bsop_date": "20260308",
                            "bstp_nmix_prpr": "2630.12",
                            "bstp_nmix_prdy_vrss": "12.34",
                            "bstp_nmix_prdy_ctrt": "0.47",
                            "prdy_vrss_sign": "2",
                        },
                    ]
                },
            },
        }

        formatted = EconomyService.format_snapshot_for_llm(snapshot)

        self.assertIn("- 코스피(20260308): <b>2630.12</b> (전일대비 +12.34, +0.47%)", formatted)
        self.assertIn("- 코스피(20260307): <b>2617.78</b>", formatted)

    def test_format_snapshot_uses_latest_two_rows_in_date_order(self):
        snapshot = {
            "us": {},
            "kr": {
                "kosdaq_daily": {
                    "output2": [
                        {
                            "stck_bsop_date": "20260306",
                            "bstp_nmix_prpr": "740.10",
                        },
                        {
                            "stck_bsop_date": "20260308",
                            "bstp_nmix_prpr": "738.55",
                            "bstp_nmix_prdy_vrss": "1.55",
                            "bstp_nmix_prdy_ctrt": "0.21",
                            "prdy_vrss_sign": "5",
                        },
                        {
                            "stck_bsop_date": "20260307",
                            "bstp_nmix_prpr": "740.10",
                        },
                    ]
                },
            },
        }

        formatted = EconomyService.format_snapshot_for_llm(snapshot)

        self.assertIn("- 코스닥(20260308): <b>738.55</b> (전일대비 -1.55, -0.21%)", formatted)
        self.assertIn("- 코스닥(20260307): <b>740.10</b>", formatted)
        self.assertNotIn("20260306", formatted)

    def test_format_snapshot_keeps_today_and_yesterday_for_comparison(self):
        snapshot = {
            "us": {},
            "kr": {
                "kospi_daily": {
                    "output2": [
                        {
                            "stck_bsop_date": "20260312",
                            "bstp_nmix_prpr": "5609.95",
                            "bstp_nmix_prdy_vrss": "0.00",
                            "bstp_nmix_prdy_ctrt": "0.00",
                            "prdy_vrss_sign": "3",
                        },
                        {
                            "stck_bsop_date": "20260311",
                            "bstp_nmix_prpr": "5609.95",
                            "bstp_nmix_prdy_vrss": "77.36",
                            "bstp_nmix_prdy_ctrt": "1.40",
                            "prdy_vrss_sign": "2",
                        },
                    ]
                },
            },
        }

        formatted = EconomyService.format_snapshot_for_llm(snapshot)

        self.assertIn("- 코스피(20260312): <b>5609.95</b> (전일대비 +0.00, +0.00%)", formatted)
        self.assertIn("- 코스피(20260311): <b>5609.95</b> (전일대비 +77.36, +1.40%)", formatted)

    def test_format_snapshot_can_skip_intraday_kr_indices_for_premarket(self):
        snapshot = {
            "us": {},
            "kr": {
                "usd_krw": 1433.20,
                "kospi": 2630.12,
                "kosdaq": 740.10,
                "kospi_daily": {
                    "output2": [
                        {
                            "stck_bsop_date": "20260308",
                            "bstp_nmix_prpr": "2630.12",
                            "bstp_nmix_prdy_vrss": "12.34",
                            "bstp_nmix_prdy_ctrt": "0.47",
                            "prdy_vrss_sign": "2",
                        }
                    ]
                },
            },
        }

        formatted = EconomyService.format_snapshot_for_llm(
            snapshot,
            include_intraday_kr_indices=False,
        )

        self.assertIn("- 원/달러 환율: <b>1433.20원</b>", formatted)
        self.assertNotIn("- 코스피: <b>2630.12</b>", formatted)
        self.assertNotIn("- 코스닥: <b>740.10</b>", formatted)
        self.assertIn("- 코스피(20260308): <b>2630.12</b> (전일대비 +12.34, +0.47%)", formatted)

    def test_load_market_outlook_news_context_includes_naver_and_google(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        self.addCleanup(lambda: os.path.exists(db_path) and os.remove(db_path))

        conn = sqlite3.connect(db_path)
        conn.executescript(
            """
            CREATE TABLE game_news (
                id INTEGER PRIMARY KEY,
                source_type TEXT,
                source_name TEXT,
                category_tag TEXT,
                game_tag TEXT,
                is_international INTEGER,
                title TEXT,
                full_content TEXT,
                published_at TEXT,
                created_at TEXT
            );
            """
        )
        conn.executemany(
            """
            INSERT INTO game_news (
                source_type, source_name, category_tag, game_tag, is_international,
                title, full_content, published_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "news",
                    "Naver",
                    "Market",
                    "Economy",
                    0,
                    "코스피 장전 전망, 반도체 강세에 외국인 수급 주목",
                    "",
                    "2026-03-18 06:45:00",
                    "2026-03-18 06:45:00",
                ),
                (
                    "news",
                    "GoogleNews",
                    "",
                    "GlobalMacro-US",
                    1,
                    "Stock futures are flat as traders look ahead to Federal Reserve interest rate decision",
                    "",
                    "2026-03-17 23:20:00",
                    "2026-03-17 23:20:00",
                ),
                (
                    "news",
                    "Naver",
                    "Tech/Semicon",
                    "Economy",
                    0,
                    "삼성전자 주주총회 현장 스케치",
                    "",
                    "2026-03-18 06:50:00",
                    "2026-03-18 06:50:00",
                ),
                (
                    "news",
                    "Naver",
                    "General",
                    "Economy",
                    0,
                    "항공 유류할증료 3배 폭등",
                    "",
                    "2026-03-18 06:40:00",
                    "2026-03-18 06:40:00",
                ),
                (
                    "news",
                    "Naver",
                    "Market",
                    "Economy",
                    0,
                    "코스피 장중 오름폭 키워 5,800선 회복",
                    "",
                    "2026-03-18 11:05:00",
                    "2026-03-18 11:05:00",
                ),
            ],
        )
        conn.commit()
        conn.close()

        context = EconomyService.load_market_outlook_news_context(
            db_path=db_path,
            now=datetime(2026, 3, 18, 7, 0, tzinfo=ZoneInfo("Asia/Seoul")),
            limit_per_source=2,
        )

        self.assertIn("[국내 시장전망 뉴스]", context)
        self.assertIn("[해외 시장전망 뉴스]", context)
        self.assertIn("[Naver/Market] 코스피 장전 전망, 반도체 강세에 외국인 수급 주목", context)
        self.assertIn(
            "[Google/Market] Stock futures are flat as traders look ahead to Federal Reserve interest rate decision",
            context,
        )
        self.assertNotIn("삼성전자 주주총회 현장 스케치", context)
        self.assertNotIn("항공 유류할증료 3배 폭등", context)
        self.assertNotIn("코스피 장중 오름폭 키워 5,800선 회복", context)


class NewsTaggingTests(unittest.TestCase):
    def test_determine_news_tags_prefers_article_text_over_query_for_naver_noise(self):
        game_tag, category_tag, is_international = determine_news_tags(
            category="economy",
            query="삼성전자",
            title="강남 아파트 세금 폭탄 현실로",
            description="부동산 세금과 공급 대책을 다루는 기사",
            gl="KR",
        )

        self.assertEqual(game_tag, "Economy")
        self.assertEqual(category_tag, "General")
        self.assertFalse(is_international)

    def test_determine_news_tags_marks_market_article_even_with_semiconductor_keyword(self):
        game_tag, category_tag, is_international = determine_news_tags(
            category="economy",
            query="반도체 업황 HBM DRAM",
            title="코스피 장전 전망, 반도체 강세에 외국인 수급 주목",
            description="오늘 증시 개장 전 체크포인트",
            gl="KR",
        )

        self.assertEqual(game_tag, "Economy")
        self.assertEqual(category_tag, "Market")
        self.assertFalse(is_international)
