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
| 1 | PROMPT-001 | Telegram Webhook Refactor & Query Classification Fix | P2 | ⬜ Pending |
| 2 | PROMPT-002 | Telegram Webhook Regression Tests | P2 | ⬜ Pending |

**Total: 2 prompts** | **Completed: 0** | **Remaining: 2**

---

## 🔴 Priority 1 (Critical) - Execute First

*(None)*

---

## 🟡 Priority 2 (High) - Execute Second

### [PROMPT-001] Telegram Webhook Refactor & Query Classification Fix

**⏱️ Execute this prompt now, then proceed to PROMPT-002**

> **🚨 REQUIRED: Use `replace_string_in_file` or `create_file` to make changes. Do NOT just show code.**

**Task**: Clean up unreachable/duplicated branches in `telegram_webhook`, avoid logging secret values, and fix `classify_query()` duplication/doc mismatch.

**Files to Modify**:
- `/home/dlckdgn/personal-portfolio/backend/routers/telegram_webhook.py`

#### Instructions:

1. Open `/home/dlckdgn/personal-portfolio/backend/routers/telegram_webhook.py`
2. Replace the entire `telegram_webhook` function with the implementation below.
3. Replace the entire `classify_query` function with the implementation below.

#### Implementation Code:

```python
# /home/dlckdgn/personal-portfolio/backend/routers/telegram_webhook.py
# Replace the ENTIRE `telegram_webhook` function with the following.

@router.post("/webhook")
async def telegram_webhook(request: Request):
    """텔레그램 업데이트 수신 웹훅"""

    # 1. Secret Token 검증 (시크릿 값은 로그에 남기지 않는다)
    secret_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if WEBHOOK_SECRET and secret_header != WEBHOOK_SECRET:
        logger.warning(
            "Invalid webhook secret (present=%s).",
            bool(secret_header),
        )
        raise HTTPException(status_code=403, detail="Invalid secret")

    # 2. 업데이트 파싱
    try:
        update = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    message = update.get("message")
    if not message:
        return {"ok": True}  # 메시지가 아닌 업데이트는 무시

    # 3. Chat ID 검증 (본인만 허용)
    chat_id = str(message.get("chat", {}).get("id", ""))
    if ALLOWED_CHAT_ID and chat_id != ALLOWED_CHAT_ID:
        logger.warning("Unauthorized chat_id: %s", chat_id)
        return {"ok": True}  # 조용히 무시

    # 4. 텍스트 파싱 및 명령어 추출
    text = (message.get("text") or "").strip()

    # 명령어 처리 (/)
    if text.startswith("/"):
        parts = text[1:].split(maxsplit=1)
        cmd = parts[0] if len(parts) > 0 else ""
        arg = parts[1] if len(parts) > 1 else ""

        if cmd == "report":
            from ..services.reporting.template import build_telegram_steam_trend_message
            response_text = build_telegram_steam_trend_message(arg)
            await send_telegram_message(response_text)
            return {"ok": True}

        # /spam 접두사 지원 (하이브리드)
        if cmd == "spam":
            parts = arg.split(maxsplit=1)
            cmd = parts[0] if len(parts) > 0 else ""
            arg = parts[1] if len(parts) > 1 else ""

        SUPPORTED_CMDS = ["report", "add", "del", "list", "on", "off", "help"]
        if cmd not in SUPPORTED_CMDS:
            return {"ok": True}

        db = SessionLocal()
        try:
            response_text = await handle_spam_command(cmd, arg, db)

            # 규칙 변경(add, del, on, off)이 있으면 AI 모델 재학습 트리거
            if cmd in ["add", "del", "on", "off"] and (
                "✅" in response_text
                or "🗑️" in response_text
                or "⏸️" in response_text
                or "▶️" in response_text
            ):
                from ..services.spam_trainer import train_spam_model
                if train_spam_model():
                    response_text += "\n🔄 <i>AI 모델이 최신 규칙으로 재학습되었습니다.</i>"

            await send_telegram_message(response_text)
        finally:
            db.close()
        return {"ok": True}

    # 일반 텍스트: 질문 유형 분류 후 처리
    if not text:
        return {"ok": True}

    # 본문은 민감할 수 있으니 길이만 로깅
    logger.info("Natural language query received (len=%d).", len(text))
    query_type = classify_query(text)
    logger.info("Query classified as: %s", query_type)

    # 게임 트렌드는 템플릿 기반 리포트로 처리 (LLM 원격 호출 불필요)
    if query_type == "game_trend":
        from ..services.reporting.template import build_telegram_steam_trend_message
        response_text = build_telegram_steam_trend_message(text)
        await send_telegram_message(response_text)
        return {"ok": True}

    from ..services.llm_service import LLMService
    llm = LLMService.get_instance()

    if not llm.is_remote_ready():
        await send_telegram_message("LLM 원격 서버가 설정되지 않아 답변을 생성할 수 없습니다.")
        return {"ok": True}

    try:
        if query_type == "esports_schedule":
            from ..services.news_collector import NewsCollector
            context_text = NewsCollector.refine_schedules_with_duckdb(text)

            prompt = f"""<start_of_turn>user
당신은 e스포츠 전문가이자 사용자의 개인 비서입니다.
사용자의 질문과 아래 제공된 경기 일정 데이터를 바탕으로 친절하고 명확하게 답변해 주세요.

[제공된 경기 일정 데이터]
{context_text}

[사용자의 질문]
{text}

[답변 규칙]
- 한국어로 답변하세요.
- 데이터에 있는 내용을 기반으로 정확하게 안내하세요. 만약 데이터에 없는 내용이라면 모른다고 정직하게 말하세요.
- 친절하고 위트 있는 말투를 사용하세요.
- 일시 정보를 포함하여 경기 정보를 깔끔하게 정리해 주세요.

답변:<end_of_turn>
<start_of_turn>model
"""
        elif query_type == "economy_news":
            from ..services.news_collector import NewsCollector
            context_text = NewsCollector.refine_economy_news_with_duckdb(text)

            prompt = f"""<start_of_turn>user
당신은 글로별 거시경제 전문가이자 사용자의 개인 비서입니다.
아래 제공된 경제 뉴스 데이터를 바탕으로 사용자의 질문에 친절하고 명확하게 답변해 주세요.

[제공된 경제 뉴스 데이터]
{context_text}

[사용자의 질문]
{text}

[답변 규칙]
- 한국어로 답변하세요.
- 영문 뉴스 제목이라면 핵심만 번역하여 설명하세요.
- 데이터에 있는 내용을 기반으로 정확하게 안내하세요. 데이터에 없는 내용은 모른다고 말하세요.
- 친절하고 위트 있는 말투를 사용하세요.

답변:<end_of_turn>
<start_of_turn>model
"""
        else:
            prompt = f"""<start_of_turn>user
당신은 친절하고 유머러스한 개인 비서입니다.
사용자의 메시지에 자연스럽고 위트 있게 답변해 주세요.

[사용자 메시지]
{text}

답변:<end_of_turn>
<start_of_turn>model
"""

        response_text = llm.generate_remote(prompt, max_tokens=1024)
        if not response_text:
            response_text = "죄송합니다. 답변을 생성하는 중에 문제가 발생했습니다."
        await send_telegram_message(response_text)
    except Exception as e:
        logger.error("Query processing failed: %s", e)
        await send_telegram_message("답변 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.")

    return {"ok": True}


# Replace the ENTIRE `classify_query` function with the following.

def classify_query(text: str) -> str:
    """
    사용자 질문 유형 분류
    - 'esports_schedule': E스포츠 경기 일정 관련
    - 'game_trend': 게임 신작/트렌드 관련
    - 'economy_news': 국내/해외 경제 뉴스 관련
    - 'general_chat': 일반 대화
    """
    text_lower = text.lower()

    esports_keywords = [
        "t1", "skt", "티원", "젠지", "geng", "gen.g", "lol", "롤",
        "lck", "발로란트", "valorant", "vct", "경기", "일정",
        "월즈", "worlds", "챌린저스", "퍼시픽",
    ]
    if any(kw in text_lower for kw in esports_keywords):
        return "esports_schedule"

    game_keywords = [
        "게임", "스팀", "steam", "신작", "트렌드", "인기", "출시",
        "추천", "플스", "ps5", "playstation", "닌텐도", "switch",
    ]
    if any(kw in text_lower for kw in game_keywords):
        return "game_trend"

    economy_keywords = [
        "미국", "유럽", "환율", "fomc", "ecb", "s&p", "나스닥", "금리",
        "cpi", "etf", "달러", "유로", "채권", "국채", "treasury", "코스피",
        "코스닥", "주식", "경제", "인플레", "경기", "불황", "호황",
    ]
    if any(kw in text_lower for kw in economy_keywords):
        return "economy_news"

    return "general_chat"
```

#### Verification:

- Run: `python3 -m unittest discover backend/tests`
- Expected: All tests pass

**✅ After completing this prompt, proceed to [PROMPT-002]**

---

### [PROMPT-002] Telegram Webhook Regression Tests

**⏱️ Execute this prompt now, then proceed to PROMPT-002**

> **🚨 REQUIRED: Use `replace_string_in_file` or `create_file` to make changes. Do NOT just show code.**

**Task**: Add unit tests to prevent regressions in `classify_query()` behavior and webhook secret handling.

**Files to Modify / Create**:
- `/home/dlckdgn/personal-portfolio/backend/tests/test_telegram_webhook.py` (new)

#### Instructions:

1. Create `/home/dlckdgn/personal-portfolio/backend/tests/test_telegram_webhook.py` with the content below.
2. Ensure tests pass.

#### Implementation Code:

```python
# /home/dlckdgn/personal-portfolio/backend/tests/test_telegram_webhook.py

import unittest

from fastapi.testclient import TestClient

from backend.main import app
from backend.routers import telegram_webhook as webhook_module


class TestTelegramWebhook(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_classify_query_game_trend(self) -> None:
        self.assertEqual(webhook_module.classify_query("스팀 신작 추천해줘"), "game_trend")
        self.assertEqual(webhook_module.classify_query("steam trending games?"), "game_trend")

    def test_classify_query_esports(self) -> None:
        self.assertEqual(webhook_module.classify_query("LCK 경기 일정 알려줘"), "esports_schedule")

    def test_classify_query_economy(self) -> None:
        self.assertEqual(webhook_module.classify_query("미국 금리 전망"), "economy_news")

    def test_webhook_rejects_invalid_secret(self) -> None:
        original_secret = webhook_module.WEBHOOK_SECRET
        original_allowed_chat_id = webhook_module.ALLOWED_CHAT_ID
        original_sender = webhook_module.send_telegram_message

        async def _noop_send(_text: str) -> None:
            return None

        try:
            webhook_module.WEBHOOK_SECRET = "expected"
            webhook_module.ALLOWED_CHAT_ID = "123"
            webhook_module.send_telegram_message = _noop_send

            payload = {
                "message": {
                    "chat": {"id": 123},
                    "text": "hello",
                }
            }
            res = self.client.post(
                "/api/telegram/webhook",
                json=payload,
                headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
            )
            self.assertEqual(res.status_code, 403)
            self.assertEqual(res.json().get("detail"), "Invalid secret")
        finally:
            webhook_module.WEBHOOK_SECRET = original_secret
            webhook_module.ALLOWED_CHAT_ID = original_allowed_chat_id
            webhook_module.send_telegram_message = original_sender


if __name__ == "__main__":
    unittest.main()
```

#### Verification:

- Run: `python3 -m unittest discover backend/tests`
- Expected: All tests pass

**🎉 ALL PROMPTS COMPLETED!**
