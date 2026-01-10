import logging
import httpx
import asyncio
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from ...core.models import GameNews
from ..llm_service import LLMService
from .core import calculate_simhash, STEAMSPY_URL

logger = logging.getLogger(__name__)

async def collect_steamspy_rankings(db: Session):
    """
    SteamSpy API를 사용하여 최근 2주간 인기 게임 순위를 수집한다.
    """
    logger.info("Collecting SteamSpy popular games (top 100 in 2 weeks)...")
    params = {"request": "top100in2weeks"}
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(STEAMSPY_URL, params=params, timeout=20.0)
            response.raise_for_status()
            data = response.json()

        count = 0
        for appid, info in data.items():
            name = info.get("name", "Unknown Game")
            owners = info.get("total_owners", info.get("owners", "Unknown Owners"))
            price = info.get("price", "0")
            if price == "0" or price == 0:
                price_str = "Free"
            else:
                price_str = f"${float(price)/100:.2f}"

            title = f"[Steam Ranking] {name}"
            content = f"Game: {name}\nAppID: {appid}\nDeveloper: {info.get('developer')}\nPublisher: {info.get('publisher')}\nPrice: {price_str}\nOwners: {owners}\nPositive/Negative: {info.get('positive')}/{info.get('negative')}"
            
            content_hash = calculate_simhash(title + content)
            existing = db.query(GameNews).filter(GameNews.content_hash == content_hash).first()
            if existing:
                continue

            news = GameNews(
                content_hash=content_hash,
                game_tag="Steam",
                source_name="SteamSpy",
                source_type="news",
                title=title,
                url=f"https://store.steampowered.com/app/{appid}",
                full_content=content,
                published_at=datetime.now(timezone.utc)
            )
            db.add(news)
            count += 1
            
        db.commit()
        logger.info(f"Collected {count} SteamSpy ranking entries.")
    except Exception as e:
        logger.error(f"Failed to collect SteamSpy rankings: {e}")

async def collect_steam_new_trends(db: Session):
    """
    Steam Store의 신규 출시작 및 인기작을 수집하여 DB에 저장한다.
    """
    logger.info("Collecting Steam New Trends to DB...")
    url = "https://store.steampowered.com/api/featuredcategories/"
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=20.0)
            response.raise_for_status()
            data = response.json()

        # 'new_releases'와 'top_sellers'에서 아이템 추출
        appids = []
        
        # 1. 신작 우선 추출
        new_releases = data.get("new_releases", {}).get("items", [])
        for item in new_releases[:5]: # 상위 5개
            appids.append(item.get("id"))
            
        # 2. 인기작 보충 (중복 제외)
        top_sellers = data.get("top_sellers", {}).get("items", [])
        for item in top_sellers:
            if len(appids) >= 10: break
            aid = item.get("id")
            if aid not in appids:
                appids.append(aid)

        if not appids:
            logger.warning("No trending AppIDs found on Steam Store.")
            return

        async with httpx.AsyncClient() as client:
            for aid in appids:
                # 상세 정보 조회 (한글 우선)
                detail_url = "https://store.steampowered.com/api/appdetails"
                res = await client.get(detail_url, params={"appids": aid, "l": "korean"}, timeout=10.0)
                if res.status_code == 200:
                    detail_data = res.json().get(str(aid), {})
                    if detail_data.get("success"):
                        info = detail_data.get("data", {})
                        name = info.get("name")
                        desc = info.get("short_description", "")[:300]
                        genres = ", ".join([g.get("description") for g in info.get("genres", [])])
                        
                        # DB 저장 (중복 방지)
                        content = f"[장르: {genres}] {desc}"
                        content_hash = calculate_simhash(content)
                        
                        existing = db.query(GameNews).filter(GameNews.content_hash == str(content_hash)).first()
                        if not existing:
                            news = GameNews(
                                game_tag="Steam",
                                source_name="SteamStore",
                                source_type="trend",
                                title=f"[TREND] {name}",
                                url=f"https://store.steampowered.com/app/{aid}",
                                full_content=content,
                                content_hash=str(content_hash),
                                published_at=datetime.now(timezone.utc)
                            )
                            db.add(news)
                            db.commit()
                            logger.info(f"Saved Steam trend: {name}")
                
                await asyncio.sleep(0.5) # Rate limit 방지

        logger.info("Steam New Trends collection completed.")
        
    except Exception as e:
        logger.error(f"Failed to collect Steam trends: {e}")


