from __future__ import annotations

from datetime import date

from backend.scripts.rebalance_kis_pension_account import _assets_from_env, _quarterly_return


def test_assets_from_env_deduplicates_bond_and_parking_code() -> None:
    assets = _assets_from_env(
        {
            "PENSION_REBALANCE_SP500_CODE": "360200",
            "PENSION_REBALANCE_KOSPI_CODE": "237350",
            "PENSION_REBALANCE_NASDAQ_CODE": "426030",
            "PENSION_REBALANCE_US_BOND_CODE": "0048J0",
            "PENSION_REBALANCE_PARKING_CODE": "0048J0",
        }
    )

    codes = [asset.code for asset in assets]
    assert codes.count("0048J0") == 1
    assert [asset.bucket for asset in assets if asset.code == "0048J0"] == ["bond"]


def test_quarterly_return_uses_quote_when_only_one_daily_price() -> None:
    class Client:
        def daily_prices(self, code: str, *, start_date: str, end_date: str) -> list[tuple[str, int]]:
            return [("20260501", 100)]

        def quote(self, code: str) -> dict[str, int]:
            return {"price": 112}

    assert round(_quarterly_return(Client(), "360200", today=date(2026, 5, 11)), 2) == 12.0


def test_quarterly_return_returns_zero_without_prices() -> None:
    class Client:
        def daily_prices(self, code: str, *, start_date: str, end_date: str) -> list[tuple[str, int]]:
            return []

        def quote(self, code: str) -> dict[str, int]:
            raise AssertionError("quote should not be called without an anchor price")

    assert _quarterly_return(Client(), "360200", today=date(2026, 5, 11)) == 0.0
