import asyncio
import unittest

from fastapi import HTTPException

from backend import auth


class AuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self._prev_token = auth.API_TOKEN

    def tearDown(self) -> None:
        auth.API_TOKEN = self._prev_token

    def test_verify_api_token_allows_when_unset(self) -> None:
        auth.API_TOKEN = ""
        asyncio.run(auth.verify_api_token(None))

    def test_verify_api_token_rejects_invalid(self) -> None:
        auth.API_TOKEN = "secret"
        with self.assertRaises(HTTPException) as context:
            asyncio.run(auth.verify_api_token("invalid"))
        self.assertEqual(context.exception.status_code, 401)
