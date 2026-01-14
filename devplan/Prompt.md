# 🤖 AI Agent Improvement Prompts

> ## 🚨 MANDATORY: FILE MODIFICATION REQUIRED
>
> **⛔ DO NOT just respond with text or code blocks.**
> **⛔ DO NOT say "you can modify like this" without actually modifying.**
> **⛔ DO NOT explain what needs to be done without doing it.**
>
> **✅ YOU MUST use file editing tools (`replace_string_in_file`, `create_file`, `multi_replace_string_in_file`) to directly modify files.**
> **✅ After each prompt, confirm "I have modified the file(s)" with the actual changes made.**
>
> ---
>
> **Process ALL prompts below SEQUENTIALLY. Do NOT stop after completing one prompt.**

---

## 📋 Execution Checklist

| # | Prompt ID | Title | Priority | Status |
|:---:|:---|:---|:---:|:---:|
| 1 | PROMPT-001 | Redact Telegram webhook logs (no secrets/user text) | P1 | ⬜ Pending |
| 2 | PROMPT-002 | Align Telegram/LLM env vars (fallbacks + `.env.example`) | P2 | ⬜ Pending |
| 3 | PROMPT-003 | Add unittest regression tests for Telegram webhook auth flow | P2 | ⬜ Pending |

**Total: 3 prompts** | **Completed: 0** | **Remaining: 3**

---

## 🔴 Priority 1 (Critical) - Execute First

### [PROMPT-001] Redact Telegram webhook logs (no secrets/user text)

**⏱️ Execute this prompt now, then proceed to PROMPT-002**

> **🚨 REQUIRED: Use `replace_string_in_file` or `multi_replace_string_in_file` to make changes. Do NOT just show code.**

**Task**: Prevent sensitive data leakage by removing the raw secret token header value and the raw user text from Telegram webhook logs.
**Files to Modify**: `backend/routers/telegram_webhook.py`

#### Instructions:

1. Open `backend/routers/telegram_webhook.py`
2. Apply both replacements below using `multi_replace_string_in_file`

#### Implementation Code:

```text
multi_replace_string_in_file({
  "path": "backend/routers/telegram_webhook.py",
  "replacements": [
    {
      "oldString": "    secret_header = request.headers.get(\"X-Telegram-Bot-Api-Secret-Token\")\n    if WEBHOOK_SECRET and secret_header != WEBHOOK_SECRET:\n        logger.warning(f\"Invalid webhook secret: {secret_header}\")\n        raise HTTPException(status_code=403, detail=\"Invalid secret\")\n",
      "newString": "    secret_header = request.headers.get(\"X-Telegram-Bot-Api-Secret-Token\")\n    if WEBHOOK_SECRET and secret_header != WEBHOOK_SECRET:\n        logger.warning(\n            \"Invalid webhook secret token (len=%s)\",\n            len(secret_header) if secret_header else 0,\n        )\n        raise HTTPException(status_code=403, detail=\"Invalid secret\")\n"
    },
    {
      "oldString": "        # (B) 자연어 처리 Flow\n        logger.info(f\"Natural language query received: {text}\")\n        query_type = classify_query(text)\n",
      "newString": "        # (B) 자연어 처리 Flow\n        logger.info(\"Natural language query received (len=%s)\", len(text))\n        query_type = classify_query(text)\n"
    }
  ]
})
```

#### Verification:
- Run: `npm run test:backend`
- Expected: All backend unit tests pass.

**✅ After completing this prompt, proceed to [PROMPT-002]**

---

## 🟡 Priority 2 (High) - Execute Second

### [PROMPT-002] Align Telegram/LLM env vars (fallbacks + `.env.example`)

**⏱️ Execute this prompt now, then proceed to PROMPT-003**

> **🚨 REQUIRED: Use `replace_string_in_file`, `multi_replace_string_in_file`, or `create_file` to make changes. Do NOT just show code.**

**Task**: Make Telegram env-var configuration consistent and backward-compatible across the webhook router and Telegram sender; update `.env.example` to reflect the actual runtime keys and remote LLM options.
**Files to Modify**: `backend/routers/telegram_webhook.py`, `backend/integrations/telegram.py`, `backend/.env.example`

#### Instructions:

1. Update env-var reading in `backend/routers/telegram_webhook.py` to support fallback keys.
2. Update env-var reading in `backend/integrations/telegram.py` to support fallback keys and fix the misleading warning message.
3. Replace `backend/.env.example` content with the updated example below (no real secrets).

#### Implementation Code:

```text
multi_replace_string_in_file({
  "path": "backend/routers/telegram_webhook.py",
  "replacements": [
    {
      "oldString": "# 환경변수에서 시크릿 토큰과 허용된 채팅 ID 로드\nWEBHOOK_SECRET = os.getenv(\"X_TELEGRAM_BOT_API_SECRET_TOKEN\")\nALLOWED_CHAT_ID = os.getenv(\"ALARM_TELEGRAM_CHAT_ID\")\n",
      "newString": "# 환경변수에서 시크릿 토큰과 허용된 채팅 ID 로드\nWEBHOOK_SECRET = os.getenv(\"X_TELEGRAM_BOT_API_SECRET_TOKEN\") or os.getenv(\"TELEGRAM_WEBHOOK_SECRET_TOKEN\")\nALLOWED_CHAT_ID = os.getenv(\"ALARM_TELEGRAM_CHAT_ID\") or os.getenv(\"TELEGRAM_CHAT_ID\")\n"
    }
  ]
})
```

```python
# Replace the entire file: backend/integrations/telegram.py
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

    bot_token = os.getenv("ALARM_TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("ALARM_TELEGRAM_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        logger.warning("Telegram bot token/chat id not configured")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=10.0)
            response.raise_for_status()
            return True
    except Exception as e:
        logger.error(f"Telegram message failed: {e}")
        return False
```

```dotenv
# Replace the entire file: backend/.env.example
# === Server & Security ===
API_TOKEN=your_secure_api_token
SECRET_KEY=your_secret_key_for_jwt
ALLOWED_HOSTS=*

# === Database ===
# SQLite (Default)
DATABASE_URL=sqlite:///./portfolio.db

# === Telegram Bot ===
# Preferred keys (used by: backend/integrations/telegram.py, backend/routers/telegram_webhook.py)
ALARM_TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
ALARM_TELEGRAM_CHAT_ID=123456789

# Backwards-compatible aliases (optional)
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_CHAT_ID=123456789

# Telegram webhook secret token (recommended)
# Configure this in Telegram via setWebhook's `secret_token` option.
X_TELEGRAM_BOT_API_SECRET_TOKEN=your_webhook_secret_token

# === Local LLM ===
# Path to the GGUF model file
LOCAL_LLM_MODEL_PATH=backend/data/gemma-3-4b-it-q4_k_m.gguf
# Number of CPU threads to use for LLM (default: 4 or 2 for coding safety)
LOCAL_LLM_THREADS=2

# === Remote LLM (OpenAI-compatible llama-server) ===
# If set, the backend will call the remote server instead of loading a local GGUF model.
LLM_BASE_URL=http://llama-server:8080
LLM_TIMEOUT=120
LLM_REMOTE_DEFAULT_MODEL=EXAONE-4.0-1.2B-BF16.gguf
# Optional (if your remote server requires auth)
LLM_API_KEY=

# === Game News APIs (Optional) ===
# PandaScore (Esports Schedule) - https://pandascore.co/
PANDASCORE_API_KEY=your_pandascore_key

# Steam Web API - https://steamcommunity.com/dev/apikey
STEAM_API_KEY=your_steam_api_key

# Naver Search API (News) - https://developers.naver.com/apps/
NAVER_CLIENT_ID=your_naver_client_id
NAVER_CLIENT_SECRET=your_naver_client_secret

# === KIS (Korea Investment & Securities) ===
KIS_APP_KEY=your_kis_app_key
KIS_APP_SECRET=your_kis_app_secret
KIS_CANO=your_account_number_prefix
KIS_ACNT_PRDT_CD=01

# === Discord (Optional) ===
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

#### Verification:
- Run: `npm run test:backend`
- Expected: All backend unit tests pass.

**✅ After completing this prompt, proceed to [PROMPT-003]**

---

### [PROMPT-003] Add unittest regression tests for Telegram webhook auth flow

**⏱️ Execute this prompt now, then proceed to PROMPT-003**

> **🚨 REQUIRED: Use `create_file` to add the test file. Do NOT just show code.**

**Task**: Add unittest-based regression tests for the Telegram webhook endpoint's security/early-return behavior (secret token validation, chat id restriction, invalid JSON, missing message).
**Files to Modify**: `backend/tests/test_telegram_webhook.py`

#### Instructions:

1. Create `backend/tests/test_telegram_webhook.py`
2. Paste the complete test code below

#### Implementation Code:

```python
import unittest

from fastapi.testclient import TestClient

from backend.main import app
import backend.routers.telegram_webhook as telegram_webhook


class TelegramWebhookAuthTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self._orig_secret = telegram_webhook.WEBHOOK_SECRET
        self._orig_allowed = telegram_webhook.ALLOWED_CHAT_ID
        self._orig_send = telegram_webhook.send_telegram_message

    def tearDown(self):
        telegram_webhook.WEBHOOK_SECRET = self._orig_secret
        telegram_webhook.ALLOWED_CHAT_ID = self._orig_allowed
        telegram_webhook.send_telegram_message = self._orig_send

    def test_rejects_invalid_secret_token(self):
        telegram_webhook.WEBHOOK_SECRET = "expected-secret"
        telegram_webhook.ALLOWED_CHAT_ID = None

        res = self.client.post(
            "/api/telegram/webhook",
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong-secret"},
            json={"message": {"chat": {"id": "123"}, "text": "hi"}},
        )
        self.assertEqual(res.status_code, 403)

    def test_ignores_unauthorized_chat_id(self):
        telegram_webhook.WEBHOOK_SECRET = None
        telegram_webhook.ALLOWED_CHAT_ID = "123"

        called = {"count": 0}

        async def fake_send(_text: str):
            called["count"] += 1
            return True

        telegram_webhook.send_telegram_message = fake_send

        res = self.client.post(
            "/api/telegram/webhook",
            json={"message": {"chat": {"id": "999"}, "text": "/help"}},
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"ok": True})
        self.assertEqual(called["count"], 0)

    def test_returns_ok_when_message_missing(self):
        telegram_webhook.WEBHOOK_SECRET = None
        telegram_webhook.ALLOWED_CHAT_ID = None

        res = self.client.post("/api/telegram/webhook", json={"update_id": 1})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"ok": True})

    def test_returns_ok_when_text_empty(self):
        telegram_webhook.WEBHOOK_SECRET = None
        telegram_webhook.ALLOWED_CHAT_ID = None

        res = self.client.post(
            "/api/telegram/webhook",
            json={"message": {"chat": {"id": "123"}, "text": "   "}},
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"ok": True})

    def test_returns_400_on_invalid_json_body(self):
        telegram_webhook.WEBHOOK_SECRET = None
        telegram_webhook.ALLOWED_CHAT_ID = None

        res = self.client.post(
            "/api/telegram/webhook",
            data="not-json",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(res.status_code, 400)
```

#### Verification:
- Run: `npm run test:backend`
- Expected: `backend/tests/test_telegram_webhook.py` passes and the overall test suite is green.

**🎉 ALL PROMPTS COMPLETED! Run final verification.**
