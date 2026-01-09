import logging
import feedparser
import httpx
import os
import json
import asyncio
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy.orm import Session
from ..core.models import GameNews
from .llm_service import LLMService
from simhash import Simhash
import re

logger = logging.getLogger(__name__)

class NewsCollector:
    """
    게임 뉴스 수집 및 전처리 (RSS, API)
    """
    
    # 주요 게임 뉴스 RSS 피드 (예시)
    RSS_FEEDS = {
        "inven_lol": "https://feeds.feedburner.com/inven/lol",
    }

    STEAMSPY_URL = "https://steamspy.com/api.php"
    PANDASCORE_URL = "https://api.pandascore.co"

    @staticmethod
    def calculate_simhash(text: str) -> str:
        return str(Simhash(text).value)

    @staticmethod
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

    @classmethod
    def collect_rss(cls, db: Session, feed_url: str, source_name: str):
        """
        RSS 피드에서 뉴스 수집 및 저장
        """
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries:
                title = entry.title
                link = entry.link
                description = getattr(entry, 'description', '')
                
                # HTML 태그 제거
                clean_desc = re.sub('<[^<]+?>', '', description)
                
                # 중복 체크 (SimHash)
                content_hash = cls.calculate_simhash(title + clean_desc)
                existing = db.query(GameNews).filter(GameNews.content_hash == content_hash).first()
                if existing:
                    continue
                
                # 메타데이터 추출 (간단한 예시)
                game_tag = "General"
                if "롤" in title or "LoL" in title:
                    game_tag = "LoL"
                elif "발로란트" in title:
                    game_tag = "Valorant"
                
                # DB 저장
                news = GameNews(
                    content_hash=content_hash,
                    game_tag=game_tag,
                    source_name=source_name,
                    title=title,
                    url=link,
                    full_content=clean_desc,
                    published_at=datetime.utcnow() # 실제로는 entry.published_parsed 파싱 필요
                )
                db.add(news)
                db.commit() # ID 생성을 위해 즉시 커밋
                db.refresh(news)
                
                logger.info(f"Collected news: {title} (ID: {news.id})")
                
                # Vector Store 등록
                try:
                    from .vector_store import VectorStore
                    vs = VectorStore.get_instance()
                    # 제목 + 본문을 임베딩
                    vs.add_texts([f"[{game_tag}] {title}\n{clean_desc}"], [news.id])
                except Exception as e:
                    logger.error(f"Failed to add to vector store: {e}")
                
        except Exception as e:
            logger.error(f"Failed to collect RSS from {source_name}: {e}")

    @classmethod
    async def collect_steamspy_rankings(cls, db: Session):
        """
        SteamSpy API를 사용하여 최근 2주간 인기 게임 순위를 수집한다.
        """
        logger.info("Collecting SteamSpy popular games (top 100 in 2 weeks)...")
        params = {"request": "top100in2weeks"}
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(cls.STEAMSPY_URL, params=params, timeout=20.0)
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
                
                content_hash = cls.calculate_simhash(title + content)
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
                
                # Vector Store 등록 (비동기 처리 권장되나 여기서는 순차)
                # ... 기존 로직과 동일 ...

            db.commit()
            logger.info(f"Collected {count} SteamSpy ranking entries.")
        except Exception as e:
            logger.error(f"Failed to collect SteamSpy rankings: {e}")

    @classmethod
    async def collect_pandascore_schedules(cls, db: Session):
        """
        PandaScore API를 사용하여 향후 e스포츠 경기 일정을 수집한다.
        """
        api_key = os.getenv("PANDASCORE_API_KEY")
        if not api_key:
            logger.warning("PANDASCORE_API_KEY not set. Skipping PandaScore collection.")
            return

        logger.info("Collecting PandaScore upcoming esports matches...")
        url = f"{cls.PANDASCORE_URL}/matches/upcoming"
        headers = {"Authorization": f"Bearer {api_key}"}
        
        try:
            async with httpx.AsyncClient() as client:
                # 더 많은 일정을 수집하기 위해 per_page=100으로 상향
                response = await client.get(url, headers=headers, params={"per_page": 100}, timeout=20.0)
                response.raise_for_status()
                matches = response.json()

            count = 0
            for match in matches:
                name = match.get("name")
                game = match.get("videogame", {}).get("name", "Unknown Game")
                league = match.get("league", {}).get("name", "Unknown League")
                begin_at_str = match.get("begin_at")
                if not begin_at_str: continue
                
                begin_at = datetime.fromisoformat(begin_at_str.replace("Z", "+00:00"))
                
                title = f"[Esports Schedule] {game} - {name}"
                content = f"Match: {name}\nLeague: {league}\nTournament: {match.get('tournament', {}).get('name')}\nStart Time: {begin_at_str}\nLink: {match.get('official_stream_url', '')}"

                content_hash = cls.calculate_simhash(title + content)
                existing = db.query(GameNews).filter(GameNews.content_hash == content_hash).first()
                if existing:
                    continue

                news = GameNews(
                    content_hash=content_hash,
                    game_tag=game,
                    source_name="PandaScore",
                    source_type="schedule",
                    event_time=begin_at,
                    title=title,
                    full_content=content,
                    published_at=datetime.now(timezone.utc)
                )
                db.add(news)
                count += 1

            db.commit()
            logger.info(f"Collected {count} PandaScore match schedules.")
        except Exception as e:
            logger.error(f"Failed to collect PandaScore schedules: {e}")

    @classmethod
    async def collect_steam_new_trends(cls, db: Session):
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
                            content_hash = Simhash(content).value
                            
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

    @classmethod
    async def generate_steam_trend_summary(cls, db: Session):
        """
        DuckDB를 이용해 DB에 저장된 최신 Steam 트렌드를 정제하고 AI 요약 리포트를 발송한다.
        """
        logger.info("Generating Steam Trend AI Summary using DuckDB...")
        
        try:
            import duckdb
            from .duckdb_refine import get_db_path
            
            db_path = get_db_path()
            con = duckdb.connect(":memory:")
            escaped_path = db_path.replace("'", "''")
            con.execute(f"ATTACH '{escaped_path}' AS sqlite_db (TYPE SQLITE, READ_ONLY)")
            
            # 1. DuckDB로 최신 스팀 트렌드 10개 추출 및 정제
            # 요약에 필요한 텍스트 위주로 고밀도화
            trends = con.execute("""
                SELECT title, full_content
                FROM sqlite_db.game_news
                WHERE game_tag = 'Steam' AND source_type = 'trend'
                ORDER BY published_at DESC
                LIMIT 10
            """).fetchall()
            
            if not trends:
                logger.warning("No Steam trends found in DB for summary.")
                return

            games_str = "\n".join([f"- {t[0].replace('[TREND] ', '')}: {t[1]}" for t in trends])
            
            # 2. LLM 요약 생성 (원격 LLM 사용)
            llm = LLMService.get_instance()
            if not llm.is_remote_ready():
                logger.warning("Remote LLM not configured. Skipping AI summary.")
                return

            prompt = f"""<start_of_turn>user
당신은 게임 트렌드에 해박한 고성능 AI 리서치 어시스턴트입니다.
DuckDB로 정제된 최신 스팀(Steam) 신작 및 인기 데이터 {len(trends)}건을 바탕으로 요약 리포트를 작성해 주세요.

[정제된 데이터 리스트]
{games_str}

[규칙]
1. 각 게임의 핵심을 콕 집어 아주 짧고 위트 있게 한 줄 요약해 주세요.
2. 텔레그램으로 보낼 것이므로 가독성이 좋아야 하며 이모지를 적절히 사용하세요.
3. 시작은 반드시 "본 리포트는 DuckDB로 정제된 최신 스팀 트렌드입니다. 🎮"로 해주세요.

요약 결과:<end_of_turn>
<start_of_turn>model
"""
            summary = llm.generate_remote(prompt, max_tokens=1024, temperature=0.7)
            if not summary:
                logger.warning("Remote LLM returned empty summary.")
                return
            
            # 3. 텔레그램 전송
            from ..scripts.run_sync_prices_scheduler import send_telegram_sync
            final_msg = f"🚀 <b>Steam AI Trend Analysis (Powered by DuckDB)</b>\n\n{summary}"
            send_telegram_sync(final_msg)
            
            logger.info("Daily Steam Trend AI Summary sent via Telegram.")
            
        except Exception as e:
            logger.error(f"Failed to generate Steam trend summary: {e}")
        finally:
            if 'con' in locals():
                con.close()

    @classmethod
    def refine_schedules_with_duckdb(cls, query_text: str, limit: int = 15) -> str:
        """
        DuckDB를 사용하여 e스포츠 일정을 검색하고 고밀도 텍스트로 정제한다.
        """
        logger.info(f"Refining Esports schedules using DuckDB for query: {query_text}")
        
        try:
            import duckdb
            from .duckdb_refine import get_db_path
            
            db_path = get_db_path()
            con = duckdb.connect(":memory:")
            escaped_path = db_path.replace("'", "''")
            con.execute(f"ATTACH '{escaped_path}' AS sqlite_db (TYPE SQLITE, READ_ONLY)")
            
            # 검색 키워드 기반 필터링 (간단 명료하게)
            where_clauses = ["source_type = 'schedule'"]
            
            q = query_text.lower()
            if "롤" in q or "lol" in q:
                where_clauses.append("(game_tag ILIKE '%LoL%' OR title ILIKE '%LoL%')")
            if "발로란트" in q or "valorant" in q:
                where_clauses.append("(game_tag ILIKE '%Valorant%' OR title ILIKE '%Valorant%')")
            if "t1" in q:
                where_clauses.append("title ILIKE '%T1%'")
            if "젠지" in q or "geng" in q:
                where_clauses.append("(title ILIKE '%GenG%' OR title ILIKE '%젠지%')")
            
            # 시간 필터 (오늘/이번달 키워드 대응)
            if "오늘" in q:
                where_clauses.append("event_time >= CURRENT_DATE AND event_time < CURRENT_DATE + INTERVAL '1 day'")
            elif "이번달" in q or "1월" in q:
                where_clauses.append("event_time >= date_trunc('month', CURRENT_DATE)")
            else:
                # 기본값: 현재 시각 이후
                where_clauses.append("event_time >= now()")

            where_sql = " AND ".join(where_clauses)
            
            sql = f"""
                SELECT 
                    strftime(event_time, '%m/%d %H:%M') as time,
                    game_tag,
                    title
                FROM sqlite_db.game_news
                WHERE {where_sql}
                ORDER BY event_time ASC
                LIMIT {limit}
            """
            
            results = con.execute(sql).fetchall()
            
            if not results:
                # 필터 없이 가장 가까운 일정 5개라도 반환 (Fallback)
                results = con.execute("""
                    SELECT strftime(event_time, '%m/%d %H:%M'), game_tag, title 
                    FROM sqlite_db.game_news 
                    WHERE source_type = 'schedule' AND event_time >= now() 
                    ORDER BY event_time ASC LIMIT 5
                """).fetchall()
                if not results: return "검색된 관련 일정이 없습니다."
                
            # 고밀도 텍스트 생성
            refined_items = []
            for r in results:
                # [Esports Schedule] LoL - EKO vs GMB -> EKO vs GMB 로 축약
                display_title = r[2].replace("[Esports Schedule] ", "").replace(f"{r[1]} - ", "")
                refined_items.append(f"📅 {r[0]} | [{r[1]}] {display_title}")
                
            return "\n".join(refined_items)
            
        except Exception as e:
            logger.error(f"DuckDB e-sports refinement failed: {e}")
            return "일정 정제 중 오류가 발생했습니다."
        finally:
            if 'con' in locals():
                con.close()
