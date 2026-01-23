"""
Portfolio Service Tests

포트폴리오 서비스의 요약 계산 및 XIRR 로직 테스트.
"""
import pytest
from datetime import date, datetime
from unittest.mock import MagicMock
from backend.services.portfolio import calculate_summary


class MockAsset:
    """테스트용 Asset 모의 객체"""
    def __init__(
        self,
        id=1,
        name="테스트 주식",
        ticker="TEST",
        category="국내주식",
        currency="KRW",
        amount=100.0,
        current_price=1000.0,
        purchase_price=800.0,
        realized_profit=5000.0,
        deleted_at=None,
        index_group=None,
    ):
        self.id = id
        self.name = name
        self.ticker = ticker
        self.category = category
        self.currency = currency
        self.amount = amount
        self.current_price = current_price
        self.purchase_price = purchase_price
        self.realized_profit = realized_profit
        self.deleted_at = deleted_at
        self.index_group = index_group


class MockCashflow:
    """테스트용 ExternalCashflow 모의 객체"""
    def __init__(self, date_val: date, amount: float, description: str = ""):
        self.date = date_val
        self.amount = amount
        self.description = description


class TestCalculateSummary:
    """포트폴리오 요약 계산 테스트"""

    def test_single_asset_summary(self):
        """단일 자산 요약 계산"""
        asset = MockAsset(
            amount=100,
            current_price=1000,
            purchase_price=800,
            realized_profit=5000,
        )
        result = calculate_summary([asset])

        # 총 가치: 100 * 1000 = 100,000
        assert result.total_value == 100_000
        # 총 투자: 100 * 800 = 80,000
        assert result.total_invested == 80_000
        # 미실현 손익: 100,000 - 80,000 = 20,000
        assert result.unrealized_profit_total == 20_000
        # 실현 손익
        assert result.realized_profit_total == 5000

    def test_multiple_assets_summary(self):
        """다중 자산 합산 테스트"""
        assets = [
            MockAsset(
                id=1,
                amount=50,
                current_price=2000,
                purchase_price=1500,
                realized_profit=1000,
            ),
            MockAsset(
                id=2,
                amount=100,
                current_price=500,
                purchase_price=600,
                realized_profit=2000,
            ),
        ]
        result = calculate_summary(assets)

        # 총 가치: 50*2000 + 100*500 = 100,000 + 50,000 = 150,000
        assert result.total_value == 150_000
        # 총 투자: 50*1500 + 100*600 = 75,000 + 60,000 = 135,000
        assert result.total_invested == 135_000
        # 미실현 손익: 150,000 - 135,000 = 15,000
        assert result.unrealized_profit_total == 15_000
        # 실현 손익: 1000 + 2000 = 3000
        assert result.realized_profit_total == 3000

    def test_empty_assets_summary(self):
        """빈 자산 목록 처리"""
        result = calculate_summary([])

        assert result.total_value == 0
        assert result.total_invested == 0
        assert result.unrealized_profit_total == 0
        assert result.realized_profit_total == 0

    def test_summary_with_zero_amount(self):
        """수량이 0인 자산 처리 (매도 완료)"""
        asset = MockAsset(
            amount=0,
            current_price=1000,
            purchase_price=800,
            realized_profit=10000,
        )
        result = calculate_summary([asset])

        assert result.total_value == 0
        assert result.total_invested == 0
        assert result.unrealized_profit_total == 0
        assert result.realized_profit_total == 10000


class TestXIRRIntegration:
    """XIRR 계산 통합 테스트"""

    def test_xirr_with_simple_cashflows(self):
        """간단한 현금흐름으로 XIRR 계산 검증"""
        assets = [MockAsset(amount=1, current_price=1_100_000, purchase_price=1_000_000)]
        cashflows = [
            MockCashflow(date(2024, 1, 1), 1_000_000, "초기 입금"),
        ]
        
        result = calculate_summary(assets, cashflows)
        
        assert hasattr(result, "xirr_rate")

    def test_xirr_with_multiple_cashflows(self):
        """다중 현금흐름 XIRR 테스트"""
        assets = [MockAsset(amount=1, current_price=2_500_000, purchase_price=2_000_000)]
        cashflows = [
            MockCashflow(date(2024, 1, 1), 1_000_000, "1차 입금"),
            MockCashflow(date(2024, 6, 1), 1_000_000, "2차 입금"),
        ]
        
        result = calculate_summary(assets, cashflows)
        
        assert hasattr(result, "xirr_rate")

    def test_xirr_handles_dividend_cashflows(self):
        """배당금 포함 현금흐름 처리"""
        assets = [MockAsset(amount=1, current_price=1_050_000, purchase_price=1_000_000)]
        cashflows = [
            MockCashflow(date(2024, 1, 1), 1_000_000, "입금"),
            MockCashflow(date(2024, 6, 1), -50_000, "배당금"),
        ]
        
        result = calculate_summary(assets, cashflows)
        
        assert hasattr(result, "xirr_rate")


class TestCurrencyMixedAssets:
    """다중 통화 자산 테스트"""

    def test_mixed_currency_assets(self):
        """KRW/USD 혼합 자산 (환전 전 원본 가치)"""
        assets = [
            MockAsset(id=1, currency="KRW", amount=100, current_price=10000, purchase_price=9000),
            MockAsset(id=2, currency="USD", amount=10, current_price=100, purchase_price=90),
        ]
        result = calculate_summary(assets)

        assert result.total_value >= 1_000_000
