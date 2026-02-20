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


async def _send_chunk(
    client: httpx.AsyncClient,
    url: str,
    chat_id: str,
    chunk: str,
    *,
    parse_mode: str | None = "HTML",
) -> bool:
    payload = {"chat_id": chat_id, "text": chunk}
    if parse_mode:
        payload["parse_mode"] = parse_mode

    try:
        response = await client.post(url, json=payload, timeout=10.0)
        response.raise_for_status()
        return True
    except httpx.HTTPStatusError as e:
        # Best-effort fallback: if HTML parsing fails, retry as plain text so the message isn't dropped.
        # This may show raw tags, but it's better than losing the notification entirely.
        if parse_mode and e.response is not None and e.response.status_code == 400:
            try:
                response2 = await client.post(
                    url,
                    json={"chat_id": chat_id, "text": chunk},
                    timeout=10.0,
                )
                response2.raise_for_status()
                logger.warning("Telegram chunk sent without parse_mode due to HTML error.")
                return True
            except Exception:
                pass

        logger.error("Telegram chunk failed: %s", e)
        return False
    except Exception as e:
        logger.error("Telegram chunk failed: %s", e)
        return False


async def send_telegram_message(text: str, bot_type: str = "alarm"):
    """
    텔레그램으로 단일 메시지를 전송한다.
    bot_type: 'main' (DB백업용), 'alarm' (알람 서비스용)
    """
    load_dotenv()

    if bot_type == "main":
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
    else:
        bot_token = os.getenv("ALARM_TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("ALARM_TELEGRAM_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        logger.warning("Telegram bot token/chat id not configured")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    chunks = _split_message(text, MAX_TELEGRAM_MESSAGE_LEN)

    try:
        async with httpx.AsyncClient() as client:
            ok_count = 0
            for chunk in chunks:
                if await _send_chunk(client, url, chat_id, chunk, parse_mode="HTML"):
                    ok_count += 1

            if ok_count == len(chunks):
                return True
            if ok_count > 0:
                logger.warning(
                    "Telegram message partially sent: %d/%d chunks succeeded.",
                    ok_count,
                    len(chunks),
                )
                return True
            return False
    except Exception as e:
        logger.error(f"Telegram message failed: {e}")
        return False
