import logging
import os
import json
import random
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from ...core.models import GameNews
from ...integrations.telegram import send_telegram_message

logger = logging.getLogger(__name__)

async def check_upcoming_matches(db: Session, catchphrases_file: str, window_minutes: int = 5) -> bool:
    now = datetime.now()
    five_min_later = now + timedelta(minutes=window_minutes)
    lower_bound = now - timedelta(minutes=window_minutes) if window_minutes > 5 else now
    
    upcoming = db.query(GameNews).filter(
        GameNews.source_type == "schedule",
        GameNews.source_name == "PandaScore",
        GameNews.event_time >= lower_bound,
        GameNews.event_time <= five_min_later,
        GameNews.league_tag.in_(["LCK", "LCK-CL", "LPL", "VCT", "Worlds", "MSI", "Worlds/MSI", "Asian Games", "EWC"])
    ).all()
    
    matches_to_notify = [m for m in upcoming if not (m.category_tag and "notified" in m.category_tag)]
    if not matches_to_notify: return False

    # 우선순위 정의 (숫자가 낮을수록 높음)
    priority_map = {
        "Worlds": 1, "MSI": 1, "Worlds/MSI": 1, "Asian Games": 1, "EWC": 1,
        "LCK": 2,
        "LCK-CL": 3,
        "LPL": 4, "VCT": 4
    }
    # 우선순위에 따라 정렬 (정의되지 않은 태그는 99로 처리)
    matches_to_notify.sort(key=lambda x: priority_map.get(x.league_tag, 99))
    
    catchphrases = ["야, 놓치지 마! 🔥", "지금 바로 입장! 🏃‍♂️", "치킨 준비됐나? 🍗", "이번 세트 대박! 🎮"]
    if os.path.exists(catchphrases_file):
        try:
            with open(catchphrases_file, 'r', encoding='utf-8') as f:
                saved = json.load(f)
                if saved and isinstance(saved, list): catchphrases = saved
        except Exception as e:
            logger.warning(f"Failed to load catchphrases: {e}")
    
    selected_phrase = random.choice(catchphrases)
    lines = [f"🎮 <b>[경기 시작 알림]</b>\n{selected_phrase}\n"]
    for match in matches_to_notify:
        title = match.title.replace("[Esports Schedule] ", "")
        _, match_name = title.split(" - ", 1) if " - " in title else ("", title)
        event_time_str = match.event_time.strftime("%H:%M") if match.event_time else "시간 미정"
        lines.append(f"🏆 <b>{match.league_tag}</b> | {event_time_str}\n   {match_name}\n")
        match.category_tag = f"{match.category_tag or ''},notified".strip(",")
    
    db.commit()
    await send_telegram_message("\n".join(lines))
    logger.info(f"Sent match notification for {len(matches_to_notify)} matches")
    return True
