import os
import logging
import httpx

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

async def send_telegram_message(text: str):
    """
    텔레그램으로 단일 메시지를 전송한다.
    """
    load_dotenv()
    bot_token = os.getenv("ALARM_TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("ALARM_TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        logger.warning("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not configured")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=10.0)
            response.raise_for_status()
            return True
    except Exception as e:
        logger.error(f"Telegram message failed: {e}")
        return False
