import logging
import duckdb
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from ..duckdb_refine import get_db_path
import time as time_module

logger = logging.getLogger(__name__)

# KST 시간대 상수
KST = ZoneInfo("Asia/Seoul")


def refine_schedules_with_duckdb(query_text: str, limit: int = 10) -> str:
    """
    DuckDB를 사용하여 e스포츠 일정을 검색하고 고밀도 텍스트로 정제한다.
    - KST 기준으로 "오늘" 범위 계산
    - 쿼리 타이밍 로그 출력
    - 폴백은 최대 1단계로 제한
    """
    start_time = time_module.perf_counter()
    logger.info(f"[Esports] 쿼리 시작: {query_text}")
    
    try:
        db_path = get_db_path()
        con = duckdb.connect(":memory:")
        escaped_path = db_path.replace("'", "''")
        con.execute(f"ATTACH '{escaped_path}' AS sqlite_db (TYPE SQLITE, READ_ONLY)")
        
        # KST 기준으로 오늘 범위 계산
        now_kst = datetime.now(KST)
        today_start = now_kst.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        
        where_clauses = ["source_type = 'schedule'"]
        
        q = query_text.lower()
        # 게임 필터 (단순 LIKE로 최적화)
        if "롤" in q or "lol" in q:
            where_clauses.append("game_tag = 'LoL'")
        if "발로란트" in q or "valorant" in q:
            where_clauses.append("game_tag = 'Valorant'")
        # 팀/리그 필터 (league_tag/is_international 사용)
        if "lck" in q:
            where_clauses.append("league_tag IN ('LCK', 'LCK-CL')")
        if "국제대회" in q or "국제" in q or "worlds" in q or "msi" in q:
            where_clauses.append("is_international = 1")
        if "t1" in q:
            where_clauses.append("title LIKE '%T1%'")
        if "젠지" in q or "geng" in q:
            where_clauses.append("(title LIKE '%Gen%' OR title LIKE '%젠지%')")
        
        # 시간 범위 필터 (KST 기준으로 파이썬에서 계산)
        if "오늘" in q:
            where_clauses.append(f"event_time >= '{today_start.isoformat()}' AND event_time < '{today_end.isoformat()}'")
        elif "이번달" in q or "1월" in q:
            month_start = today_start.replace(day=1)
            where_clauses.append(f"event_time >= '{month_start.isoformat()}'")
        else:
            # 기본: 지금부터 미래 일정
            where_clauses.append(f"event_time >= '{now_kst.isoformat()}'")

        where_sql = " AND ".join(where_clauses)
        
        # 주요 리그 우선 정렬 - LIMIT 고정
        sql = f"""
            SELECT 
                strftime(event_time, '%m/%d %H:%M') as time,
                game_tag,
                title,
                url,
                CASE 
                    WHEN league_tag = 'LCK' OR is_international = 1 THEN 0
                    WHEN league_tag = 'LCK-CL' THEN 1
                    ELSE 2
                END as priority
            FROM sqlite_db.game_news
            WHERE {where_sql}
            ORDER BY priority ASC, event_time ASC
            LIMIT 15
        """
        
        query_start = time_module.perf_counter()
        results = con.execute(sql).fetchall()
        query_time = (time_module.perf_counter() - query_start) * 1000
        logger.info(f"[Esports] 메인 쿼리 완료: {len(results)}건, {query_time:.1f}ms")
        
        # 폴백: 결과 없으면 "오늘/이번달" 제약을 풀고 "해당 필터(LCK 등)" 내에서 가장 가까운 일정 5개 검색
        if not results:
            # 시간 제약만 제외한 나머지 필터 유지
            fallback_where = [c for c in where_clauses if "event_time" not in c]
            fallback_where.append(f"event_time >= '{now_kst.isoformat()}'")
            fallback_where_sql = " AND ".join(fallback_where)
            
            fallback_sql = f"""
                SELECT strftime(event_time, '%m/%d %H:%M'), game_tag, title, url, 2 as priority
                FROM sqlite_db.game_news 
                WHERE {fallback_where_sql}
                ORDER BY event_time ASC 
                LIMIT 5
            """
            query_start = time_module.perf_counter()
            results = con.execute(fallback_sql).fetchall()
            query_time = (time_module.perf_counter() - query_start) * 1000
            logger.info(f"[Esports] 폴백 쿼리 완료: {len(results)}건, {query_time:.1f}ms")
            
            if not results:
                total_time = (time_module.perf_counter() - start_time) * 1000
                logger.info(f"[Esports] 결과 없음, 총 소요시간: {total_time:.1f}ms")
                return "검색된 관련 일정이 없습니다."
            
        # 결과 포맷팅 (최대 12개)
        refined_items = []
        for r in results[:12]:
            display_title = r[2].replace("[Esports Schedule] ", "").replace(f"{r[1]} - ", "")
            display_title = display_title.replace(" vs ", " ⚔️ ")
            item = f"📅 {r[0]} | {display_title}"
            if r[3]:
                item += " (🔗)"
            refined_items.append(item)
            
        total_time = (time_module.perf_counter() - start_time) * 1000
        context_str = "\n".join(refined_items)
        logger.info(f"[Esports] 완료: {len(refined_items)}건 반환, 컨텐츠 길이: {len(context_str)}자, 총 소요시간: {total_time:.1f}ms")
        return context_str
        
    except Exception as e:
        total_time = (time_module.perf_counter() - start_time) * 1000
        logger.error(f"[Esports] 오류 발생: {e}, 소요시간: {total_time:.1f}ms")
        return "일정 정제 중 오류가 발생했습니다."
    finally:
        if 'con' in locals():
            con.close()


def refine_news_with_duckdb(category: str = "economy", limit: int = 10) -> str:
    """
    DuckDB를 사용하여 일반 뉴스(경제, 기술 등)를 검색하고 고밀도 텍스트로 정제한다.
    """
    logger.info(f"Refining news using DuckDB for category: {category}")
    try:
        db_path = get_db_path()
        con = duckdb.connect(":memory:")
        escaped_path = db_path.replace("'", "''")
        con.execute(f"ATTACH '{escaped_path}' AS sqlite_db (TYPE SQLITE, READ_ONLY)")
        
        where_clauses = ["source_type = 'news'"]
        if category == "economy":
            where_clauses.append("category_tag IN ('Macro', 'Tech/Semicon', 'FX/Rates', 'Market', 'Crypto', 'EV/Auto', 'Economy')")
        elif category == "esports":
            where_clauses.append("category_tag IN ('LCK', 'LCK-CL', 'VCT', 'General')")
        
        where_sql = " AND ".join(where_clauses)
        
        sql = f"""
            SELECT 
                strftime(published_at, '%m/%d %H:%M') as time,
                game_tag,
                title,
                url
            FROM sqlite_db.game_news
            WHERE {where_sql}
            ORDER BY published_at DESC
            LIMIT {limit}
        """
        
        results = con.execute(sql).fetchall()
        if not results: return f"수집된 {category} 관련 뉴스가 없습니다."
        
        refined_items = []
        for r in results:
            url = r[3] if r[3] else ""
            if url:
                refined_items.append(f"📰 {r[0]} | [{r[1]}] {r[2]}\n   🔗 {url}")
            else:
                refined_items.append(f"📰 {r[0]} | [{r[1]}] {r[2]}")
        
        context_str = "\n".join(refined_items)
        logger.info(f"[News] {category} 완료: {len(refined_items)}건 반환, 컨텐츠 길이: {len(context_str)}자")
        return context_str
        
    except Exception as e:
        logger.error(f"Failed to refine news: {e}")
        return "뉴스 정제 중 오류가 발생했습니다."
    finally:
        if 'con' in locals():
            con.close()

def refine_economy_news_with_duckdb(query_text: str, limit: int = 12) -> str:
    """
    DuckDB를 사용하여 경제 뉴스(국내+해외)를 검색하고 고밀도 텍스트로 정제한다.
    국내(Naver) + 해외(GoogleNews) 통합 조회
    """
    logger.info(f"Refining economy news using DuckDB for query: {query_text}")
    try:
        db_path = get_db_path()
        con = duckdb.connect(":memory:")
        escaped_path = db_path.replace("'", "''")
        con.execute(f"ATTACH '{escaped_path}' AS sqlite_db (TYPE SQLITE, READ_ONLY)")
        
        where_clauses = [
            "source_type = 'news'",
            "category_tag IN ('Macro', 'Tech/Semicon', 'FX/Rates', 'Market', 'Crypto', 'EV/Auto', 'Economy', 'General')"
        ]
        
        q = query_text.lower()
        if "미국" in q or "us" in q or "국제" in q or "해외" in q:
            where_clauses.append("is_international = 1")
        elif "한국" in q or "국내" in q:
            where_clauses.append("is_international = 0 AND source_name = 'Naver'")
        
        if "나스닥" in q or "nasdaq" in q or "s&p" in q:
            where_clauses.append("category_tag = 'Market'")
        if "금리" in q or "환율" in q:
            where_clauses.append("category_tag = 'FX/Rates'")
        
        where_sql = " AND ".join(where_clauses)
        
        sql = f"""
            SELECT 
                strftime(published_at, '%m/%d %H:%M') as time,
                category_tag,
                title,
                source_name,
                is_international
            FROM sqlite_db.game_news
            WHERE {where_sql}
            ORDER BY published_at DESC
            LIMIT {limit}
        """
        
        results = con.execute(sql).fetchall()
        if not results: 
            return "수집된 경제 뉴스가 없습니다. 스케줄러가 실행되면 뉴스가 수집됩니다."
        
        domestic = []
        global_news = []
        
        for r in results:
            tag = r[1]
            title = r[2]
            source = r[3]
            is_intl = r[4]
            
            line = f"📰 {r[0]} | [{tag}] {title}"
            
            if is_intl:
                global_news.append(line)
            else:
                domestic.append(line)
        
        output_parts = []
        if global_news:
            output_parts.append("🌍 **해외 거시경제**\n" + "\n".join(global_news[:10]))
        if domestic:
            output_parts.append("🇰🇷 **국내 경제**\n" + "\n".join(domestic[:10]))
        
        context_str = "\n\n".join(output_parts) if output_parts else "관련 뉴스가 없습니다."
        logger.info(f"[Economy] 완료: {len(output_parts)}개 섹션 반환, 컨텐츠 길이: {len(context_str)}자")
        return context_str
        
    except Exception as e:
        logger.error(f"Failed to refine economy news: {e}")
        return "경제 뉴스 정제 중 오류가 발생했습니다."
    finally:
        if 'con' in locals():
            con.close()

def refine_game_trends_with_duckdb(query_text: str, limit: int = 10) -> str:
    """
    DuckDB를 사용하여 Steam 트렌드/랭킹 데이터를 검색하고 고밀도 텍스트로 정제한다.
    - SteamStore: source_type='trend'
    - SteamSpy: source_name='SteamSpy' (source_type='news')
    """
    logger.info(f"Refining Steam game trends using DuckDB for query: {query_text}")
    try:
        db_path = get_db_path()
        con = duckdb.connect(":memory:")
        escaped_path = db_path.replace("'", "''")
        con.execute(f"ATTACH '{escaped_path}' AS sqlite_db (TYPE SQLITE, READ_ONLY)")

        q = (query_text or "").lower()
        where_clauses = [
            "(source_name IN ('SteamStore', 'SteamSpy') OR game_tag = 'Steam')"
        ]

        # 간단한 의도 분기: 신작/트렌드는 trend 위주, 랭킹/인기는 SteamSpy 위주
        if any(k in q for k in ["신작", "new", "출시", "release"]):
            where_clauses.append("source_type = 'trend'")
        elif any(k in q for k in ["랭킹", "순위", "top", "인기", "popular", "best"]):
            where_clauses.append("source_name = 'SteamSpy'")

        where_sql = " AND ".join(where_clauses)

        sql = f"""
            SELECT
                strftime(published_at, '%m/%d %H:%M') as time,
                source_name,
                source_type,
                title,
                url,
                full_content
            FROM sqlite_db.game_news
            WHERE {where_sql}
            ORDER BY published_at DESC
            LIMIT {limit}
        """

        results = con.execute(sql).fetchall()
        if not results:
            return "수집된 Steam 트렌드/랭킹 데이터가 없습니다. 스케줄러가 실행되면 데이터가 쌓입니다."

        refined_items = []
        for r in results:
            time_str, _source_name, source_type, title, url, content = r
            icon = "🔥" if source_type == "trend" else "🏆"
            compact = (content or "").replace("\n", " ").strip()
            # LLM 컨텍스트 최적화를 위해 스니펫 길이를 줄임 (160 -> 100)
            if len(compact) > 100:
                compact = compact[:100] + "…"

            line = f"{icon} {time_str} | {title}"
            if compact:
                line += f"\n   {compact}"
            if url:
                line += f"\n   🔗 {url}"
            refined_items.append(line)

        context_str = "\n".join(refined_items)
        logger.info(f"[GameTrend] 완료: {len(refined_items)}건 반환, 컨텐츠 길이: {len(context_str)}자")
        return context_str

    except Exception as e:
        logger.error(f"Failed to refine Steam game trends: {e}")
        return "게임 트렌드 정제 중 오류가 발생했습니다."
    finally:
        if 'con' in locals():
            con.close()
