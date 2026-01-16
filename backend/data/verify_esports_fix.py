import asyncio
import os
import json
from datetime import datetime
from unittest.mock import MagicMock, patch
from backend.services.alarm_service import AlarmService
from backend.services.alarm.match_notifier import check_upcoming_matches

async def test_generation():
    print("Testing Catchphrase Generation...")
    # 프롬프트 캐시 강제 초기화
    from backend.services.prompt_loader import _prompt_cache
    _prompt_cache.clear()
    
    # generate_daily_catchphrases 호출
    success = await AlarmService.generate_daily_catchphrases()
    print(f"Generation Success: {success}")
    
    save_path = "backend/data/esports_catchphrases_v2.json"
    if os.path.exists(save_path):
        with open(save_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            print("Generated Data Structure:")
            print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print("Error: V2 file not found!")

async def test_notification_logic():
    print("\nTesting Notification Logic (Mocking DB)...")
    db = MagicMock()
    
    # LoL 경기 모사
    lol_match = MagicMock()
    lol_match.game_tag = "LoL"
    lol_match.league_tag = "LCK"
    lol_match.title = "T1 vs Gen.G"
    lol_match.event_time = datetime.now()
    lol_match.category_tag = ""
    
    # Valorant 경기 모사
    val_match = MagicMock()
    val_match.game_tag = "Valorant"
    val_match.league_tag = "VCT"
    val_match.title = "DRX vs PRX"
    val_match.event_time = datetime.now()
    val_match.category_tag = ""
    
    with patch("backend.integrations.telegram.send_telegram_message") as mock_send:
        # 1. LoL만 있는 경우
        db.query().filter().all.return_value = [lol_match]
        await check_upcoming_matches(db, "backend/data/esports_catchphrases.json")
        sent_msg = mock_send.call_args[0][0]
        print(f"LoL Only Notification Snippet:\n{sent_msg[:100]}...")
        
        # 2. 발로란트만 있는 경우
        mock_send.reset_mock()
        db.query().filter().all.return_value = [val_match]
        await check_upcoming_matches(db, "backend/data/esports_catchphrases.json")
        sent_msg = mock_send.call_args[0][0]
        print(f"Valorant Only Notification Snippet:\n{sent_msg[:100]}...")

if __name__ == "__main__":
    asyncio.run(test_generation())
    asyncio.run(test_notification_logic())
