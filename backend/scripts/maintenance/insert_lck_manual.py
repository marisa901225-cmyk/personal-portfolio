from datetime import datetime, timedelta, timezone
from backend.core.db import SessionLocal
from backend.core.models import GameNews
from backend.services.news.core import calculate_simhash

def insert_manual_lck_schedules():
    # 2026 LCK Cup Week 1 Schedule (KST)
    schedules = [
        # Friday, Jan 16
        {"title": "[Esports Schedule] LoL - DNS vs DK", "time": "2026-01-16 17:00:00", "league": "LCK Cup"},
        {"title": "[Esports Schedule] LoL - HLE vs T1", "time": "2026-01-16 20:00:00", "league": "LCK Cup"},
        # Saturday, Jan 17
        {"title": "[Esports Schedule] LoL - BRO vs BFX", "time": "2026-01-17 15:00:00", "league": "LCK Cup"},
        {"title": "[Esports Schedule] LoL - GEN vs KT", "time": "2026-01-17 18:00:00", "league": "LCK Cup"},
        # Sunday, Jan 18
        {"title": "[Esports Schedule] LoL - DNS vs HLE", "time": "2026-01-18 15:00:00", "league": "LCK Cup"},
        {"title": "[Esports Schedule] LoL - DRX vs T1", "time": "2026-01-18 18:00:00", "league": "LCK Cup"},
    ]

    db = SessionLocal()
    count = 0
    try:
        for sch in schedules:
            event_time = datetime.strptime(sch["time"], "%Y-%m-%d %H:%M:%S")
            content = f"Match: {sch['title'].split(' - ')[-1]}\nLeague: {sch['league']}\nTournament: Group Stage\nStart Time: {sch['time']}\nNote: Manually inserted due to API delay."
            
            content_hash = calculate_simhash(sch["title"] + content)
            
            # 중복 확인
            existing = db.query(GameNews).filter(GameNews.content_hash == content_hash).first()
            if not existing:
                news = GameNews(
                    content_hash=content_hash,
                    game_tag="LoL",
                    league_tag="LCK",
                    is_international=False,
                    source_name="Manual",
                    source_type="schedule",
                    event_time=event_time,
                    title=sch["title"],
                    full_content=content,
                    published_at=datetime.now(timezone.utc).replace(tzinfo=None)
                )
                db.add(news)
                count += 1
        
        db.commit()
        print(f"Successfully inserted {count} manual LCK schedules.")
    except Exception as e:
        print(f"Error inserting schedules: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    insert_manual_lck_schedules()
