import unittest
from unittest.mock import Mock, patch

import requests

from backend.integrations.kis.trading_adapter import KISTradingAPI


class KISTradingAdapterTests(unittest.TestCase):
    def test_market_get_uses_secondary_context_when_available(self) -> None:
        api = object.__new__(KISTradingAPI)
        api._secondary_market_ctx = Mock()
        api._secondary_market_ctx.get.return_value = {"rt_cd": "0", "output": []}
        api._get = Mock(return_value={"rt_cd": "0", "output": ["primary"]})

        result = api._market_get("/path", "TRID", {"a": "b"})

        self.assertEqual(result, {"rt_cd": "0", "output": []})
        api._secondary_market_ctx.get.assert_called_once_with("/path", "TRID", {"a": "b"}, "")
        api._get.assert_not_called()

    def test_market_get_falls_back_to_primary_when_secondary_fails(self) -> None:
        api = object.__new__(KISTradingAPI)
        api._secondary_market_ctx = Mock()
        api._secondary_market_ctx.get.side_effect = requests.exceptions.Timeout("secondary timeout")
        api._get = Mock(return_value={"rt_cd": "0", "output": ["primary"]})

        result = api._market_get("/path", "TRID", {"a": "b"})

        self.assertEqual(result, {"rt_cd": "0", "output": ["primary"]})
        api._secondary_market_ctx.get.assert_called_once_with("/path", "TRID", {"a": "b"}, "")
        api._get.assert_called_once_with("/path", "TRID", {"a": "b"}, "")

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

    def test_get_applies_extra_min_gap_only_for_daily_chart_paths(self) -> None:
        api = object.__new__(KISTradingAPI)
        api._core = Mock()
        api._base_url = Mock(return_value="https://example.test")
        api._headers = Mock(return_value={"Authorization": "Bearer token"})
        api._rest_throttle = Mock()
        api._throttle_path_min_gap = Mock()

        response = Mock()
        response.json.return_value = {"rt_cd": "0", "output": []}
        response.raise_for_status.return_value = None

        api._session = Mock()
        api._session.get.return_value = response

        api._get("/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice", "TRID", {"a": "b"})
        api._throttle_path_min_gap.assert_called_once_with(
            "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
        )

    def test_throttle_path_min_gap_skips_non_target_paths(self) -> None:
        api = object.__new__(KISTradingAPI)

        with patch("backend.integrations.kis.trading_adapter.throttle_rest_min_gap") as gap_mock:
            api._throttle_path_min_gap("/uapi/domestic-stock/v1/trading/inquire-balance")

        gap_mock.assert_not_called()

    def test_throttle_path_min_gap_applies_to_quote_path(self) -> None:
        api = object.__new__(KISTradingAPI)

        with patch("backend.integrations.kis.trading_adapter.throttle_rest_min_gap") as gap_mock:
            api._throttle_path_min_gap("/uapi/domestic-stock/v1/quotations/inquire-price")

        gap_mock.assert_called_once()

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

    def test_get_force_reauths_once_on_expired_token_response(self) -> None:
        api = object.__new__(KISTradingAPI)
        api._core = Mock()
        api._base_url = Mock(return_value="https://example.test")
        api._headers = Mock(return_value={"Authorization": "Bearer token"})
        api._rest_throttle = Mock()
        api._ka = Mock()
        api._ka.is_expired_token_response.side_effect = [True, False]

        expired_response = Mock()
        expired_response.json.return_value = {"msg_cd": "EGW00123", "msg1": "기간이 만료된 token 입니다."}
        expired_response.raise_for_status.side_effect = requests.exceptions.HTTPError("expired")

        ok_response = Mock()
        ok_response.raise_for_status.return_value = None
        ok_response.json.return_value = {"rt_cd": "0", "output": []}

        api._session = Mock()
        api._session.get.side_effect = [expired_response, ok_response]

        result = api._get("/path", "TRID", {"a": "b"})

        self.assertEqual(result, {"rt_cd": "0", "output": []})
        self.assertEqual(api._session.get.call_count, 2)
        self.assertEqual(api._rest_throttle.call_count, 2)
        api._ka.force_reauth_current_env.assert_called_once_with()

    def test_post_force_reauths_once_on_expired_token_response(self) -> None:
        api = object.__new__(KISTradingAPI)
        api._core = Mock()
        api._base_url = Mock(return_value="https://example.test")
        api._headers = Mock(return_value={"Authorization": "Bearer token"})
        api._rest_throttle = Mock()
        api._ka = Mock()
        api._ka.is_expired_token_response.side_effect = [True, False]

        expired_response = Mock()
        expired_response.json.return_value = {"msg_cd": "EGW00123", "msg1": "기간이 만료된 token 입니다."}
        expired_response.raise_for_status.side_effect = requests.exceptions.HTTPError("expired")

        ok_response = Mock()
        ok_response.raise_for_status.return_value = None
        ok_response.json.return_value = {"rt_cd": "0", "output": {"odno": "1"}}

        api._session = Mock()
        api._session.post.side_effect = [expired_response, ok_response]

        result = api._post("/path", "TRID", {"a": "b"})

        self.assertEqual(result, {"rt_cd": "0", "output": {"odno": "1"}})
        self.assertEqual(api._session.post.call_count, 2)
        self.assertEqual(api._rest_throttle.call_count, 2)
        self.assertEqual(api._ka.set_order_hash_key.call_count, 2)
        api._ka.force_reauth_current_env.assert_called_once_with()

    def test_quote_scales_market_cap_from_eok_to_won(self) -> None:
        api = object.__new__(KISTradingAPI)
        api._market_get = Mock(
            return_value={
                "output": {
                    "stck_prpr": "12345",
                    "stck_oprc": "12000",
                    "stck_hgpr": "12500",
                    "stck_lwpr": "11900",
                    "acml_vol": "456789",
                    "prdy_ctrt": "2.34",
                    "hts_avls": "8827",
                    "mrkt_warn_cls_code": "00",
                    "mang_issu_cls_code": "N",
                }
            }
        )

        quote = api.quote("005880")

        self.assertEqual(quote["market_cap"], 8827 * 100_000_000)
        self.assertEqual(quote["market_warning_code"], "00")
        self.assertEqual(quote["management_issue_code"], "N")
        api._market_get.assert_called_once()

    def test_quote_uses_ttl_cache_for_same_code(self) -> None:
        api = object.__new__(KISTradingAPI)
        api._quote_cache = {}
        api._market_get = Mock(
            return_value={
                "output": {
                    "stck_prpr": "12345",
                    "stck_oprc": "12000",
                    "stck_hgpr": "12500",
                    "stck_lwpr": "11900",
                    "acml_vol": "456789",
                    "prdy_ctrt": "2.34",
                    "hts_avls": "8827",
                    "mrkt_warn_cls_code": "00",
                    "mang_issu_cls_code": "N",
                }
            }
        )

        first = api.quote("005880")
        second = api.quote("005880")

        self.assertEqual(api._market_get.call_count, 1)
        self.assertEqual(first, second)
        self.assertIsNot(first, second)

    def test_daily_index_bars_parses_industry_daily_chart_rows(self) -> None:
        api = object.__new__(KISTradingAPI)
        api._daily_index_bars_cache = {}
        api._market_get = Mock(
            return_value={
                "output2": [
                    {
                        "stck_bsop_date": "20260318",
                        "bstp_nmix_oprc": "1000.1",
                        "bstp_nmix_hgpr": "1011.2",
                        "bstp_nmix_lwpr": "998.5",
                        "bstp_nmix_prpr": "1009.7",
                        "acml_vol": "12345",
                        "acml_tr_pbmn": "67890",
                    },
                    {
                        "stck_bsop_date": "20260317",
                        "bstp_nmix_oprc": "990.0",
                        "bstp_nmix_hgpr": "1001.0",
                        "bstp_nmix_lwpr": "988.0",
                        "bstp_nmix_prpr": "1000.0",
                        "acml_vol": "11111",
                        "acml_tr_pbmn": "22222",
                    },
                ]
            }
        )

        df = api.daily_index_bars("2250", end="20260318", lookback=10)

        self.assertEqual(df["date"].tolist(), ["20260317", "20260318"])
        self.assertAlmostEqual(float(df.iloc[-1]["close"]), 1009.7)
        self.assertEqual(int(df.iloc[-1]["volume"]), 12345)

    def test_daily_bars_uses_ttl_cache_for_same_request(self) -> None:
        api = object.__new__(KISTradingAPI)
        api._daily_bars_cache = {}
        api._market_get = Mock(
            return_value={
                "output2": [
                    {
                        "stck_bsop_date": "20260318",
                        "stck_oprc": "1000",
                        "stck_hgpr": "1100",
                        "stck_lwpr": "990",
                        "stck_clpr": "1080",
                        "acml_vol": "12345",
                        "acml_tr_pbmn": "67890",
                    },
                    {
                        "stck_bsop_date": "20260317",
                        "stck_oprc": "950",
                        "stck_hgpr": "1000",
                        "stck_lwpr": "940",
                        "stck_clpr": "980",
                        "acml_vol": "11111",
                        "acml_tr_pbmn": "22222",
                    },
                ]
            }
        )

        first = api.daily_bars("005930", end="20260318", lookback=2)
        second = api.daily_bars("005930", end="20260318", lookback=2)

        self.assertEqual(api._market_get.call_count, 1)
        self.assertEqual(first["date"].tolist(), ["20260317", "20260318"])
        self.assertEqual(second["date"].tolist(), ["20260317", "20260318"])
        self.assertIsNot(first, second)


if __name__ == "__main__":
    unittest.main()
