import os
import logging
import httpx

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

MAX_TELEGRAM_MESSAGE_LEN = int(os.getenv("TELEGRAM_MAX_MESSAGE_LEN", "3800"))


def _split_message(text: str, limit: int) -> list[str]:
    """
    Split a (Telegram HTML) message into chunks that stay under Telegram length limits.
    Best-effort: prefers paragraph/newline boundaries to reduce the chance of breaking HTML tags.
    """
    normalized = (text or "").strip()
    if not normalized:
        return [""]
    if len(normalized) <= limit:
        return [normalized]

    parts: list[str] = []
    remaining = normalized

    while len(remaining) > limit:
        window = remaining[:limit]
        cut = max(window.rfind("\n\n"), window.rfind("\n"), window.rfind(" "))
        if cut <= 0:
            cut = limit
        chunk = remaining[:cut].rstrip()
        if chunk:
            parts.append(chunk)
        remaining = remaining[cut:].lstrip()

    if remaining:
        parts.append(remaining)
    return parts


async def send_telegram_message(text: str):
    """
    텔레그램으로 단일 메시지를 전송한다.
    """
    load_dotenv()

    bot_token = os.getenv("ALARM_TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("ALARM_TELEGRAM_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        logger.warning("Telegram bot token/chat id not configured")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    chunks = _split_message(text, MAX_TELEGRAM_MESSAGE_LEN)

    try:
        async with httpx.AsyncClient() as client:
            for chunk in chunks:
                payload = {
                    "chat_id": chat_id,
                    "text": chunk,
                    "parse_mode": "HTML",
                }
                response = await client.post(url, json=payload, timeout=10.0)
                response.raise_for_status()
            return True
    except Exception as e:
        logger.error(f"Telegram message failed: {e}")
        return False
