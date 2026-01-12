import logging
import duckdb
from ..duckdb_refine import get_db_path

logger = logging.getLogger(__name__)

def refine_schedules_with_duckdb(query_text: str, limit: int = 15) -> str:
    """
    DuckDB를 사용하여 e스포츠 일정을 검색하고 고밀도 텍스트로 정제한다.
    """
    logger.info(f"Refining Esports schedules using DuckDB for query: {query_text}")
    
    try:
        db_path = get_db_path()
        con = duckdb.connect(":memory:")
        escaped_path = db_path.replace("'", "''")
        con.execute(f"ATTACH '{escaped_path}' AS sqlite_db (TYPE SQLITE, READ_ONLY)")
        
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
        
        if "오늘" in q:
            where_clauses.append("event_time >= CURRENT_DATE AND event_time < CURRENT_DATE + INTERVAL '1 day'")
        elif "이번달" in q or "1월" in q:
            where_clauses.append("event_time >= date_trunc('month', CURRENT_DATE)")
        else:
            where_clauses.append("event_time >= now()")

        where_sql = " AND ".join(where_clauses)
        
        sql = f"""
            SELECT 
                strftime(event_time, '%m/%d %H:%M') as time,
                game_tag,
                title,
                url
            FROM sqlite_db.game_news
            WHERE {where_sql}
            ORDER BY event_time ASC
            LIMIT {limit}
        """
        
        results = con.execute(sql).fetchall()
        
        if not results:
            results = con.execute("""
                SELECT strftime(event_time, '%m/%d %H:%M'), game_tag, title, url 
                FROM sqlite_db.game_news 
                WHERE source_type = 'schedule' AND event_time >= now() 
                ORDER BY event_time ASC LIMIT 5
            """).fetchall()
            if not results: return "검색된 관련 일정이 없습니다."
            
        refined_items = []
        for r in results:
            display_title = r[2].replace("[Esports Schedule] ", "").replace(f"{r[1]} - ", "")
            url = r[3] if r[3] else ""
            if url:
                refined_items.append(f"📅 {r[0]} | [{r[1]}] {display_title}\n   🔗 {url}")
            else:
                refined_items.append(f"📅 {r[0]} | [{r[1]}] {display_title}")
            
        return "\n".join(refined_items)
        
    except Exception as e:
        logger.error(f"DuckDB e-sports refinement failed: {e}")
        return "일정 정제 중 오류가 발생했습니다."
    finally:
        if 'con' in locals():
            con.close()

def refine_news_with_duckdb(category: str = "economy", limit: int = 15) -> str:
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
            where_clauses.append("game_tag IN ('Economy', 'Tech/Semiconductor', 'FX', 'Fed/Macro')")
        elif category == "esports":
            where_clauses.append("game_tag IN ('LoL', 'Valorant', 'LCK-CK', 'Esports')")
        
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
        
        return "\n".join(refined_items)
        
    except Exception as e:
        logger.error(f"Failed to refine news: {e}")
        return "뉴스 정제 중 오류가 발생했습니다."
    finally:
        if 'con' in locals():
            con.close()

def refine_economy_news_with_duckdb(query_text: str, limit: int = 20) -> str:
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
            "(game_tag IN ('Economy', 'Tech/Semiconductor', 'FX', 'Fed/Macro') OR game_tag LIKE 'GlobalMacro%')"
        ]
        
        q = query_text.lower()
        if "미국" in q or "us" in q or "나스닥" in q or "s&p" in q:
            where_clauses.append("game_tag LIKE '%US%' OR title ILIKE '%nasdaq%' OR title ILIKE '%S&P%'")
        if "유럽" in q or "eu" in q or "ecb" in q:
            where_clauses.append("game_tag LIKE '%EU%' OR title ILIKE '%ECB%'")
        if "한국" in q or "코스피" in q or "원화" in q:
            where_clauses.append("source_name = 'Naver'")
        
        where_sql = " AND ".join(where_clauses)
        
        sql = f"""
            SELECT 
                strftime(published_at, '%m/%d %H:%M') as time,
                game_tag,
                title,
                source_name
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
            source = r[3]
            tag = r[1]
            line = f"📰 {r[0]} | {r[2]}"
            
            if source == "Naver" or tag in ('Economy', 'Tech/Semiconductor', 'FX', 'Fed/Macro'):
                domestic.append(line)
            else:
                global_news.append(line)
        
        output_parts = []
        if global_news:
            output_parts.append("🌍 **해외 거시경제**\n" + "\n".join(global_news[:10]))
        if domestic:
            output_parts.append("🇰🇷 **국내 경제**\n" + "\n".join(domestic[:10]))
        
        return "\n\n".join(output_parts) if output_parts else "관련 뉴스가 없습니다."
        
    except Exception as e:
        logger.error(f"Failed to refine economy news: {e}")
        return "경제 뉴스 정제 중 오류가 발생했습니다."
    finally:
        if 'con' in locals():
            con.close()

def refine_game_trends_with_duckdb(query_text: str, limit: int = 15) -> str:
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
            if len(compact) > 160:
                compact = compact[:160] + "…"

            line = f"{icon} {time_str} | {title}"
            if compact:
                line += f"\n   {compact}"
            if url:
                line += f"\n   🔗 {url}"
            refined_items.append(line)

        return "\n".join(refined_items)

    except Exception as e:
        logger.error(f"Failed to refine Steam game trends: {e}")
        return "게임 트렌드 정제 중 오류가 발생했습니다."
    finally:
        if 'con' in locals():
            con.close()
