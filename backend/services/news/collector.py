import logging
from .core import calculate_simhash, calculate_importance_score, RSS_FEEDS, NAVER_ESPORTS_QUERIES, NAVER_ECONOMY_QUERIES, GOOGLE_NEWS_MACRO_QUERIES
from .rss import collect_rss, collect_google_news, collect_all_google_news
from .naver import collect_naver_news, collect_all_naver_news
from .steam import collect_steamspy_rankings, collect_steam_new_trends
from .esports import collect_pandascore_schedules
from .refiner import refine_schedules_with_duckdb, refine_news_with_duckdb, refine_economy_news_with_duckdb, refine_game_trends_with_duckdb

logger = logging.getLogger(__name__)

class NewsCollector:
    """
    게임 뉴스 수집 및 전처리 Facade (Refactored)
    """

    RSS_FEEDS = RSS_FEEDS
    NAVER_ESPORTS_QUERIES = NAVER_ESPORTS_QUERIES
    NAVER_ECONOMY_QUERIES = NAVER_ECONOMY_QUERIES
    GOOGLE_NEWS_MACRO_QUERIES = GOOGLE_NEWS_MACRO_QUERIES

    @staticmethod
    def calculate_simhash(text: str) -> str:
        return calculate_simhash(text)

    @staticmethod
    def calculate_importance_score(title: str, source: str, published_at) -> int:
        return calculate_importance_score(title, source, published_at)

    @staticmethod
    def collect_rss(db, feed_url: str, source_name: str):
        return collect_rss(db, feed_url, source_name)

    @staticmethod
    async def collect_google_news(db, query: str, region: str = "US"):
        return await collect_google_news(db, query, region)

    @staticmethod
    async def collect_all_google_news(db):
        return await collect_all_google_news(db)

    @staticmethod
    async def collect_naver_news(db, query: str, category: str = "esports"):
        return await collect_naver_news(db, query, category)

    @staticmethod
    async def collect_all_naver_news(db):
        return await collect_all_naver_news(db)

    @staticmethod
    async def collect_steamspy_rankings(db):
        return await collect_steamspy_rankings(db)

    @staticmethod
    async def collect_steam_new_trends(db):
        return await collect_steam_new_trends(db)

    @staticmethod
    async def collect_pandascore_schedules(db):
        return await collect_pandascore_schedules(db)

    @staticmethod
    def refine_schedules_with_duckdb(query_text: str, limit: int = 15) -> str:
        return refine_schedules_with_duckdb(query_text, limit)

    @staticmethod
    def refine_news_with_duckdb(category: str = "economy", limit: int = 15) -> str:
        return refine_news_with_duckdb(category, limit)

    @staticmethod
    def refine_economy_news_with_duckdb(query_text: str, limit: int = 20) -> str:
        return refine_economy_news_with_duckdb(query_text, limit)

    @staticmethod
    def refine_game_trends_with_duckdb(query_text: str, limit: int = 15) -> str:
        return refine_game_trends_with_duckdb(query_text, limit)
