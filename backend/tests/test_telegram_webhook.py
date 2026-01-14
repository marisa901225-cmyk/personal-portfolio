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
