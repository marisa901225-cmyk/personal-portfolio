import logging
import os
from datetime import datetime
from simhash import Simhash

# Constants
RSS_FEEDS = {
    "inven_lol": "https://feeds.feedburner.com/inven/lol",
}

STEAMSPY_URL = "https://steamspy.com/api.php"
PANDASCORE_URL = "https://api.pandascore.co"
NAVER_NEWS_URL = "https://openapi.naver.com/v1/search/news.json"

# 네이버 뉴스 검색 키워드 버킷 (2026 시즌 기준)
NAVER_ESPORTS_QUERIES = [
    "T1 티원",
    "Gen.G 젠지",
    "LCK",
    "LCK CUP LCK컵",
    "롤드컵 Worlds 월즈",
    "VCT Pacific 퍼시픽 킥오프 Kickoff",
    "챌린저스 코리아 CK 2군리그",
]

NAVER_ECONOMY_QUERIES = [
    "코스피 코스닥 주식시장",
    "환율 원달러",
    "한국은행 금통위 기준금리",
    "FOMC 연준 CPI PCE",
    "삼성전자",
    "ETF",
    "반도체 HBM DRAM",
]

# 해외 거시경제 키워드 (구글 뉴스 RSS용)
GOOGLE_NEWS_MACRO_QUERIES = {
    "US": [
        "S&P 500 stock market",
        "Nasdaq composite index",
        "FOMC Fed interest rate",
        "US CPI inflation",
        "Treasury yields bonds",
        "ETF market trends",
    ],
    "EU": [
        "ECB interest rate decision",
        "Euro Stoxx 50 index",
        "German DAX stock",
        "UK FTSE 100",
    ],
}

logger = logging.getLogger(__name__)

def calculate_simhash(text: str) -> str:
    return str(Simhash(text).value)

def calculate_importance_score(title: str, source: str, published_at: datetime) -> int:
    """
    뉴스 중요도 점수 계산 (Heuristic)
    """
    score = 0
    
    # 1. 키워드 가중치
    keywords = ["출시", "패치", "대회", "긴급", "연기", "논란", "속보", "오피셜"]
    if any(k in title for k in keywords):
        score += 30
        
    # 2. 출처 가중치 (예시)
    if "MustRead" in source: # 가상의 중요 태그
        score += 20
        
    # 3. 최신성 (최근 4시간 이내)
    delta_hours = (datetime.utcnow() - published_at).total_seconds() / 3600
    if delta_hours < 4:
        score += 20
    elif delta_hours < 12:
        score += 10
        
    return score
