import unittest
from unittest.mock import Mock, patch

import requests

from backend.integrations.kis.trading_adapter import KISTradingAPI


class KISTradingAdapterTests(unittest.TestCase):
    def test_volume_rank_returns_empty_on_transport_error(self) -> None:
        api = object.__new__(KISTradingAPI)

        def _boom(*args, **kwargs):
            raise requests.exceptions.ConnectionError("network down")

        api._get = _boom  # type: ignore[method-assign]

        result = api.volume_rank("volume", top_n=10, asof="20260317")

        self.assertEqual(result, [])

    def test_market_cap_rank_returns_empty_on_transport_error(self) -> None:
        api = object.__new__(KISTradingAPI)

        def _boom(*args, **kwargs):
            raise requests.exceptions.Timeout("timed out")

        api._get = _boom  # type: ignore[method-assign]

        result = api.market_cap_rank(top_k=20, asof="20260317")

        self.assertEqual(result, [])

    def test_get_uses_shared_rest_throttle_before_request(self) -> None:
        api = object.__new__(KISTradingAPI)
        api._core = Mock()
        api._base_url = Mock(return_value="https://example.test")
        api._headers = Mock(return_value={"Authorization": "Bearer token"})
        api._rest_throttle = Mock()

        response = Mock()
        response.json.return_value = {"rt_cd": "0", "output": []}
        response.raise_for_status.return_value = None

        api._session = Mock()
        api._session.get.return_value = response

        api._get("/path", "TRID", {"a": "b"})

        api._rest_throttle.assert_called_once_with()
        api._session.get.assert_called_once()

    def test_get_retries_once_on_connection_abort_then_succeeds(self) -> None:
        api = object.__new__(KISTradingAPI)
        api._core = Mock()
        api._base_url = Mock(return_value="https://example.test")
        api._headers = Mock(return_value={"Authorization": "Bearer token"})
        api._rest_throttle = Mock()

        ok_response = Mock()
        ok_response.raise_for_status.return_value = None
        ok_response.json.return_value = {"rt_cd": "0", "output": []}

        api._session = Mock()
        api._session.get.side_effect = [
            requests.exceptions.ConnectionError("connection aborted"),
            ok_response,
        ]

        with patch("backend.integrations.kis.trading_adapter.time.sleep") as sleep_mock:
            result = api._get("/path", "TRID", {"a": "b"})

        self.assertEqual(result, {"rt_cd": "0", "output": []})
        self.assertEqual(api._session.get.call_count, 2)
        self.assertEqual(api._rest_throttle.call_count, 2)
        sleep_mock.assert_called_once()

    def test_get_does_not_retry_non_retryable_http_error(self) -> None:
        api = object.__new__(KISTradingAPI)
        api._core = Mock()
        api._base_url = Mock(return_value="https://example.test")
        api._headers = Mock(return_value={"Authorization": "Bearer token"})
        api._rest_throttle = Mock()

        bad_response = Mock()
        bad_response.status_code = 400
        http_error = requests.exceptions.HTTPError("bad request")
        http_error.response = bad_response

        fail_response = Mock()
        fail_response.raise_for_status.side_effect = http_error

        api._session = Mock()
        api._session.get.return_value = fail_response

        with patch("backend.integrations.kis.trading_adapter.time.sleep") as sleep_mock:
            with self.assertRaises(requests.exceptions.HTTPError):
                api._get("/path", "TRID", {"a": "b"})

        self.assertEqual(api._session.get.call_count, 1)
        sleep_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
