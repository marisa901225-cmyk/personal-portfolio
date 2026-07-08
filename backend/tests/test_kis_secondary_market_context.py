import unittest
from contextlib import nullcontext
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from backend.integrations.kis.secondary_market_context import (
    SecondaryMarketContext,
    SecondaryMarketCredentials,
)


class SecondaryMarketContextTests(unittest.TestCase):
    def _build_context(self) -> SecondaryMarketContext:
        ctx = SecondaryMarketContext(
            SecondaryMarketCredentials(
                app_key="app1",
                app_secret="sec1",
                product="01",
                base_url="https://example.test",
                user_agent="MyAsset",
            ),
            config_dir="/tmp/slot1_market",
            min_gap_by_path={},
        )
        ctx._session = Mock()
        return ctx

    def test_ensure_auth_reuses_db_cached_token(self) -> None:
        ctx = self._build_context()

        with patch(
            "backend.integrations.kis.secondary_market_context.read_kis_token_record",
            return_value=("cached-token", None),
        ) as read_mock:
            token = ctx.ensure_auth()

        self.assertEqual(token, "cached-token")
        read_mock.assert_called_once_with(slot=1)
        ctx._session.post.assert_not_called()

    def test_ensure_auth_persists_new_token_to_slot1(self) -> None:
        ctx = self._build_context()
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "access_token": "fresh-token",
            "access_token_token_expired": "2026-04-18 10:00:00",
        }
        ctx._session.post.return_value = response

        with patch(
            "backend.integrations.kis.secondary_market_context.read_kis_token_record",
            return_value=(None, None),
        ), patch(
            "backend.integrations.kis.secondary_market_context.save_kis_token",
        ) as save_mock, patch(
            "backend.integrations.kis.secondary_market_context.throttle_rest_requests",
        ), patch(
            "backend.integrations.kis.secondary_market_context.kis_token_issue_lock",
            return_value=nullcontext(),
        ):
            token = ctx.ensure_auth()

        self.assertEqual(token, "fresh-token")
        save_mock.assert_called_once()
        _, kwargs = save_mock.call_args
        self.assertEqual(kwargs["slot"], 1)

    def test_ensure_auth_rechecks_db_inside_issue_lock(self) -> None:
        ctx = self._build_context()
        expires_at = datetime.now() + timedelta(hours=1)

        with patch(
            "backend.integrations.kis.secondary_market_context.read_kis_token_record",
            side_effect=[(None, None), ("cached-token", expires_at)],
        ) as read_mock, patch(
            "backend.integrations.kis.secondary_market_context.kis_token_issue_lock",
            return_value=nullcontext(),
        ), patch(
            "backend.integrations.kis.secondary_market_context.throttle_rest_requests",
        ) as throttle_mock:
            token = ctx.ensure_auth()

        self.assertEqual(token, "cached-token")
        self.assertEqual(read_mock.call_count, 2)
        ctx._session.post.assert_not_called()
        throttle_mock.assert_not_called()

    def test_ensure_auth_failure_logs_slot1_failure(self) -> None:
        ctx = self._build_context()
        response = Mock()
        response.status_code = 403
        response.text = "rate limited"
        response.json.return_value = {
            "msg_cd": "EGW00133",
            "msg1": "접근토큰 발급 잠시 후 다시 시도하세요(1분당 1회)",
        }
        response.raise_for_status.side_effect = RuntimeError("403")
        ctx._session.post.return_value = response

        with patch(
            "backend.integrations.kis.secondary_market_context.read_kis_token_record",
            return_value=(None, None),
        ), patch(
            "backend.integrations.kis.secondary_market_context.log_kis_token_issue_failure",
        ) as log_mock, patch(
            "backend.integrations.kis.secondary_market_context.throttle_rest_requests",
        ), patch(
            "backend.integrations.kis.secondary_market_context.kis_token_issue_lock",
            return_value=nullcontext(),
        ):
            with self.assertRaises(RuntimeError):
                ctx.ensure_auth()

        log_mock.assert_called_once()
        _, kwargs = log_mock.call_args
        self.assertEqual(kwargs["slot"], 1)
        self.assertEqual(kwargs["status_code"], 403)
        self.assertEqual(kwargs["error_code"], "EGW00133")


if __name__ == "__main__":
    unittest.main()
