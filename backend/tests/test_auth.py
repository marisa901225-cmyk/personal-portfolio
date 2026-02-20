import asyncio
import unittest

from fastapi import HTTPException

from backend.core import auth


class AuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self._prev_token = auth.API_TOKEN

    def tearDown(self) -> None:
        auth.API_TOKEN = self._prev_token

    def test_verify_api_token_fails_when_unset_and_not_debug(self) -> None:
        auth.API_TOKEN = ""
        # ALLOW_NO_AUTH가 False이고 debug가 False일 때, 토큰이 없으면 503 에러 발생
        with self.assertRaises(HTTPException) as context:
            asyncio.run(auth.verify_api_token(None))
        self.assertEqual(context.exception.status_code, 503)

    def test_verify_api_token_rejects_invalid(self) -> None:
        auth.API_TOKEN = "secret"
        with self.assertRaises(HTTPException) as context:
            asyncio.run(auth.verify_api_token("invalid"))
        self.assertEqual(context.exception.status_code, 401)
