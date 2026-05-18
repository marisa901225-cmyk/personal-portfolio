import unittest
import pytest

from fastapi.testclient import TestClient

from backend.main import app
import backend.routers.telegram_webhook as telegram_webhook


@pytest.mark.integration
class TelegramWebhookAuthTests(unittest.TestCase):
    valid_secret = "expected-secret"
    valid_chat_id = "123"

    def setUp(self):
        self.client = TestClient(app)
        self._orig_secret = telegram_webhook.WEBHOOK_SECRET
        self._orig_allowed = telegram_webhook.ALLOWED_CHAT_ID
        self._orig_send = telegram_webhook.send_telegram_message
        self._orig_docker_status = telegram_webhook._get_docker_status
        self._orig_restart = telegram_webhook._restart_jellyfin_container
        self._orig_haruhi = telegram_webhook._control_haruhi_llm

    def tearDown(self):
        telegram_webhook.WEBHOOK_SECRET = self._orig_secret
        telegram_webhook.ALLOWED_CHAT_ID = self._orig_allowed
        telegram_webhook.send_telegram_message = self._orig_send
        telegram_webhook._get_docker_status = self._orig_docker_status
        telegram_webhook._restart_jellyfin_container = self._orig_restart
        telegram_webhook._control_haruhi_llm = self._orig_haruhi

    def _headers(self, secret: str | None = None) -> dict[str, str]:
        return {"X-Telegram-Bot-Api-Secret-Token": secret or self.valid_secret}

    def test_rejects_invalid_secret_token(self):
        telegram_webhook.WEBHOOK_SECRET = self.valid_secret
        telegram_webhook.ALLOWED_CHAT_ID = self.valid_chat_id

        res = self.client.post(
            "/api/telegram/webhook",
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong-secret"},
            json={"message": {"chat": {"id": self.valid_chat_id}, "text": "hi"}},
        )
        self.assertEqual(res.status_code, 403)

    def test_ignores_unauthorized_chat_id(self):
        telegram_webhook.WEBHOOK_SECRET = self.valid_secret
        telegram_webhook.ALLOWED_CHAT_ID = self.valid_chat_id

        called = {"count": 0}

        async def fake_send(_text: str):
            called["count"] += 1
            return True

        telegram_webhook.send_telegram_message = fake_send

        res = self.client.post(
            "/api/telegram/webhook",
            headers=self._headers(),
            json={"message": {"chat": {"id": "999"}, "text": "/help"}},
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"ok": True})
        self.assertEqual(called["count"], 0)

    def test_returns_ok_when_message_missing(self):
        telegram_webhook.WEBHOOK_SECRET = self.valid_secret
        telegram_webhook.ALLOWED_CHAT_ID = self.valid_chat_id

        res = self.client.post("/api/telegram/webhook", headers=self._headers(), json={"update_id": 1})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"ok": True})

    def test_returns_ok_when_text_empty(self):
        telegram_webhook.WEBHOOK_SECRET = self.valid_secret
        telegram_webhook.ALLOWED_CHAT_ID = self.valid_chat_id

        res = self.client.post(
            "/api/telegram/webhook",
            headers=self._headers(),
            json={"message": {"chat": {"id": self.valid_chat_id}, "text": "   "}},
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"ok": True})

    def test_returns_400_on_invalid_json_body(self):
        telegram_webhook.WEBHOOK_SECRET = self.valid_secret
        telegram_webhook.ALLOWED_CHAT_ID = self.valid_chat_id

        res = self.client.post(
            "/api/telegram/webhook",
            data="not-json",
            headers={"Content-Type": "application/json", **self._headers()},
        )
        self.assertEqual(res.status_code, 400)

    def test_jellyfin_restart_command_sends_result(self):
        telegram_webhook.WEBHOOK_SECRET = self.valid_secret
        telegram_webhook.ALLOWED_CHAT_ID = self.valid_chat_id
        sent_messages: list[str] = []

        async def fake_restart():
            return "✅ Jellyfin 재시작 명령을 보냈습니다"

        async def fake_send(text: str):
            sent_messages.append(text)
            return True

        telegram_webhook._restart_jellyfin_container = fake_restart
        telegram_webhook.send_telegram_message = fake_send

        res = self.client.post(
            "/api/telegram/webhook",
            headers=self._headers(),
            json={"message": {"chat": {"id": self.valid_chat_id}, "text": "/jellyfin_restart"}},
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"ok": True})
        self.assertEqual(sent_messages, ["✅ Jellyfin 재시작 명령을 보냈습니다"])

    def test_docker_status_command_sends_result(self):
        telegram_webhook.WEBHOOK_SECRET = self.valid_secret
        telegram_webhook.ALLOWED_CHAT_ID = self.valid_chat_id
        sent_messages: list[str] = []

        async def fake_docker_status():
            return "📦 <b>Docker 상태</b>\n🟢 <code>jaw-agent</code> - Up 1 hour"

        async def fake_send(text: str):
            sent_messages.append(text)
            return True

        telegram_webhook._get_docker_status = fake_docker_status
        telegram_webhook.send_telegram_message = fake_send

        res = self.client.post(
            "/api/telegram/webhook",
            headers=self._headers(),
            json={"message": {"chat": {"id": self.valid_chat_id}, "text": "/docker_status"}},
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"ok": True})
        self.assertEqual(sent_messages, ["📦 <b>Docker 상태</b>\n🟢 <code>jaw-agent</code> - Up 1 hour"])

    def test_docker_status_command_with_bot_mention_sends_result(self):
        telegram_webhook.WEBHOOK_SECRET = self.valid_secret
        telegram_webhook.ALLOWED_CHAT_ID = self.valid_chat_id
        sent_messages: list[str] = []

        async def fake_docker_status():
            return "📦 <b>Docker 상태</b>\n🟢 <code>jaw-agent</code> - Up 1 hour"

        async def fake_send(text: str):
            sent_messages.append(text)
            return True

        telegram_webhook._get_docker_status = fake_docker_status
        telegram_webhook.send_telegram_message = fake_send

        res = self.client.post(
            "/api/telegram/webhook",
            headers=self._headers(),
            json={"message": {"chat": {"id": self.valid_chat_id}, "text": "/docker_status@AlarmRelayBot"}},
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"ok": True})
        self.assertEqual(sent_messages, ["📦 <b>Docker 상태</b>\n🟢 <code>jaw-agent</code> - Up 1 hour"])

    def test_filter_docker_status_containers_includes_all_running_and_only_related_stopped(self):
        containers = [
            {
                "Names": ["/jaw-agent"],
                "State": "running",
                "Labels": {
                    "com.docker.compose.project": "my-home-server",
                    "com.docker.compose.service": "jaw-agent",
                },
            },
            {
                "Names": ["/myasset-backend-api"],
                "State": "running",
                "Labels": {
                    "com.docker.compose.project": "personal-portfolio",
                    "com.docker.compose.service": "backend-api",
                },
            },
            {
                "Names": ["/c8ab37f420fe_jellyfin"],
                "State": "running",
                "Labels": {
                    "com.docker.compose.project": telegram_webhook.JELLYFIN_COMPOSE_PROJECT,
                    "com.docker.compose.service": telegram_webhook.JELLYFIN_COMPOSE_SERVICE,
                },
            },
            {
                "Names": ["/hungry_villani"],
                "State": "exited",
                "Labels": {},
            },
            {
                "Names": ["/myasset-llm-light"],
                "State": "exited",
                "Labels": {
                    "com.docker.compose.project": "personal-portfolio",
                    "com.docker.compose.service": "llama-server-light",
                },
            },
        ]

        filtered = telegram_webhook._filter_docker_status_containers(containers)
        names = [item["Names"][0].lstrip("/") for item in filtered]

        self.assertEqual(names, ["c8ab37f420fe_jellyfin", "jaw-agent", "myasset-backend-api", "myasset-llm-light"])

    def test_help_command_matches_current_commands(self):
        telegram_webhook.WEBHOOK_SECRET = self.valid_secret
        telegram_webhook.ALLOWED_CHAT_ID = self.valid_chat_id
        sent_messages: list[str] = []

        async def fake_send(text: str):
            sent_messages.append(text)
            return True

        telegram_webhook.send_telegram_message = fake_send

        res = self.client.post(
            "/api/telegram/webhook",
            headers=self._headers(),
            json={"message": {"chat": {"id": self.valid_chat_id}, "text": "/help"}},
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"ok": True})
        self.assertEqual(len(sent_messages), 1)
        self.assertIn("/docker_status", sent_messages[0])
        self.assertIn("/jellyfin_restart", sent_messages[0])
        self.assertIn("/haruhi_llm_start", sent_messages[0])
        self.assertIn("/haruhi_llm_stop", sent_messages[0])
        self.assertIn("Docker 컨테이너 실행/정지 상태와 포트 요약", sent_messages[0])
        self.assertIn("하루히 SYCL LLM 컨테이너 정지", sent_messages[0])
        self.assertNotIn("/model", sent_messages[0])
        self.assertNotIn("/reset", sent_messages[0])

    def test_haruhi_llm_stop_command_sends_result(self):
        telegram_webhook.WEBHOOK_SECRET = self.valid_secret
        telegram_webhook.ALLOWED_CHAT_ID = self.valid_chat_id
        sent_messages: list[str] = []

        async def fake_control(action: str):
            self.assertEqual(action, "stop")
            return "✅ 하루히 LLM 정지 명령을 보냈습니다"

        async def fake_send(text: str):
            sent_messages.append(text)
            return True

        telegram_webhook._control_haruhi_llm = fake_control
        telegram_webhook.send_telegram_message = fake_send

        res = self.client.post(
            "/api/telegram/webhook",
            headers=self._headers(),
            json={"message": {"chat": {"id": self.valid_chat_id}, "text": "/haruhi_llm_stop"}},
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"ok": True})
        self.assertEqual(sent_messages, ["✅ 하루히 LLM 정지 명령을 보냈습니다"])
