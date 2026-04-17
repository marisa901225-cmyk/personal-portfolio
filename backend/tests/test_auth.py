import asyncio
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

from backend.core import auth


class AuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self._prev_token = auth.API_TOKEN

    def tearDown(self) -> None:
        auth.API_TOKEN = self._prev_token

    @staticmethod
    def _request(host: str) -> Request:
        return Request(
            {
                "type": "http",
                "http_version": "1.1",
                "method": "GET",
                "scheme": "https",
                "path": "/api/health",
                "raw_path": b"/api/health",
                "query_string": b"",
                "headers": [(b"host", host.encode("utf-8"))],
                "client": ("1.2.3.4", 12345),
                "server": ("testserver", 443),
            }
        )

    def test_verify_api_token_fails_when_unset_and_not_debug(self) -> None:
        auth.API_TOKEN = ""
        # ALLOW_NO_AUTH가 False이고 debug가 False일 때, 토큰이 없으면 503 에러 발생
        with self.assertRaises(HTTPException) as context:
            asyncio.run(auth.verify_api_token(self._request("localhost"), None))
        self.assertEqual(context.exception.status_code, 503)

    def test_verify_api_token_rejects_invalid(self) -> None:
        auth.API_TOKEN = "secret"
        with self.assertRaises(HTTPException) as context:
            asyncio.run(auth.verify_api_token(self._request("localhost"), "invalid"))
        self.assertEqual(context.exception.status_code, 401)

    def test_tailnet_request_accepts_api_key_only(self) -> None:
        auth.API_TOKEN = "secret"

        asyncio.run(auth.verify_api_token(self._request("marisa-server.tail5c2348.ts.net"), "secret"))

    def test_tailnet_request_accepts_jwt_only(self) -> None:
        auth.API_TOKEN = "secret"

        with patch("backend.core.auth.jwt.decode", return_value={"sub": "user-1"}):
            asyncio.run(
                auth.verify_api_token(
                    self._request("marisa-server.tail5c2348.ts.net"),
                    None,
                    authorization="Bearer jwt-token",
                )
            )

    def test_non_tailnet_request_rejects_api_key_only(self) -> None:
        auth.API_TOKEN = "secret"

        with self.assertRaises(HTTPException) as context:
            asyncio.run(auth.verify_api_token(self._request("public.example.com"), "secret"))

        self.assertEqual(context.exception.status_code, 401)
        self.assertIn("JWT and API Key required", str(context.exception.detail))

    def test_non_tailnet_request_rejects_jwt_only(self) -> None:
        auth.API_TOKEN = "secret"

        with patch("backend.core.auth.jwt.decode", return_value={"sub": "user-1"}):
            with self.assertRaises(HTTPException) as context:
                asyncio.run(
                    auth.verify_api_token(
                        self._request("public.example.com"),
                        None,
                        authorization="Bearer jwt-token",
                    )
                )

        self.assertEqual(context.exception.status_code, 401)
        self.assertIn("JWT and API Key required", str(context.exception.detail))

    def test_non_tailnet_request_requires_both_jwt_and_api_key(self) -> None:
        auth.API_TOKEN = "secret"

        with patch("backend.core.auth.jwt.decode", return_value={"sub": "user-1"}):
            asyncio.run(
                auth.verify_api_token(
                    self._request("public.example.com"),
                    "secret",
                    authorization="Bearer jwt-token",
                )
            )
