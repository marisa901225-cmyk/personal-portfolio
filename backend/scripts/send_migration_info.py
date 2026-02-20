import asyncio
import os
import sys
from pathlib import Path

# backend 디렉토리를 path에 추가
current_dir = Path(__file__).resolve().parent
backend_dir = current_dir.parent
sys.path.append(str(backend_dir))

from integrations.telegram import send_telegram_message

async def main():
    walkthrough_path = Path("/home/dlckdgn/.gemini/antigravity/brain/809058eb-7d53-411d-a4a3-85c4230d8460/walkthrough.md")
    
    if not walkthrough_path.exists():
        print(f"Error: {walkthrough_path} not found")
        return

    with open(walkthrough_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 텔레그램 메시지 포맷팅 (HTML)
    msg = f"🚀 <b>서버 이전 및 커널 업그레이드 가이드</b>\n\n{content}"
    
    # 'main' 봇 타입으로 전송 (사용자가 말한 db봇)
    success = await send_telegram_message(msg, bot_type="main")
    
    if success:
        print("Telegram message sent successfully!")
    else:
        print("Failed to send telegram message.")

if __name__ == "__main__":
    asyncio.run(main())
