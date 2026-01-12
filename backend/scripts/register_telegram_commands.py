import os
import httpx
import asyncio
from dotenv import load_dotenv

async def register_commands():
    # .env 파일 위치 명시적 로드
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    load_dotenv(env_path)
    
    token = os.getenv("ALARM_TELEGRAM_BOT_TOKEN")
    if not token:
        print("❌ ALARM_TELEGRAM_BOT_TOKEN not found in .env")
        return

    commands = [
        {"command": "report", "description": "리포트 생성 (예: /report 이번달, /report 스팀)"},
        {"command": "list", "description": "스팸 필터 규칙 목록 보기"},
        {"command": "add", "description": "스팸 필터 키워드 추가 (예: /add 키워드)"},
        {"command": "del", "description": "스팸 필터 규칙 삭제 (예: /del ID)"},
        {"command": "help", "description": "도움말 보기"}
    ]

    url = f"https://api.telegram.org/bot{token}/setMyCommands"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json={"commands": commands})
            result = resp.json()
            if result.get("ok"):
                print("✅ Telegram commands registered successfully!")
            else:
                print(f"❌ Failed to register commands: {result}")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(register_commands())
