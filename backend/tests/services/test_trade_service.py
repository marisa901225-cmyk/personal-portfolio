"""
Trade Service Tests

거래 서비스의 예외 상황 및 정상 동작을 테스트.
"""
import pytest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException

from backend.services.trade_service import (
    create_trade_with_sync,
    _apply_trade_to_asset,
    ZERO_TOLERANCE,
)
from backend.core.schemas import TradeCreate


class MockAsset:
    """테스트용 Asset 모의 객체"""
    def __init__(
        self,
        id=1,
        user_id=1,
        amount=100.0,
        purchase_price=50.0,
        current_price=50.0,
        realized_profit=0.0,
        deleted_at=None,
        tags="present",
    ):
        self.id = id
        self.user_id = user_id
        self.amount = amount
        self.purchase_price = purchase_price
        self.current_price = current_price
        self.realized_profit = realized_profit
        self.deleted_at = deleted_at
        self.tags = tags
        self.updated_at = None


class TestTradeValidation:
    """거래 생성 시 유효성 검사 테스트"""

    def test_negative_quantity_raises_error(self):
        """수량이 0 이하면 에러"""
        db = MagicMock()
        payload = TradeCreate(
            asset_id=1,
            type="BUY",
            quantity=-10,
            price=100,
        )
        with pytest.raises(HTTPException) as exc:
            create_trade_with_sync(db, user_id=1, item=payload)
        assert exc.value.status_code == 400
        assert "positive" in exc.value.detail.lower()

    def test_zero_price_raises_error(self):
        """가격이 0 이하면 에러"""
        db = MagicMock()
        payload = TradeCreate(
            asset_id=1,
            type="BUY",
            quantity=10,
            price=0,
        )
        with pytest.raises(HTTPException) as exc:
            create_trade_with_sync(db, user_id=1, item=payload)
        assert exc.value.status_code == 400

    def test_invalid_trade_type_raises_error(self):
        """유효하지 않은 거래 타입이면 Pydantic ValidationError"""
        from pydantic import ValidationError
        
        with pytest.raises(ValidationError):
            payload = TradeCreate(
                asset_id=1,
                type="INVALID",
                quantity=10,
                price=100,
            )



class TestSellValidation:
    """매도 시 수량 초과 검증 테스트"""

    def test_sell_more_than_owned_raises_error(self):
        """보유량보다 많이 매도 시 에러"""
        asset = MockAsset(amount=10)
        
        with pytest.raises(HTTPException) as exc:
            _apply_trade_to_asset(
                asset,
                trade_type="SELL",
                quantity=15,  # 10개 보유 중 15개 매도 시도
                price=100,
                now=MagicMock(),
            )
        assert exc.value.status_code == 400
        assert "more than current" in exc.value.detail.lower()

    def test_sell_exact_amount_succeeds(self):
        """보유량과 정확히 동일한 양 매도 시 성공 (전량 매도)"""
        asset = MockAsset(amount=10, purchase_price=100, realized_profit=0)
        now = MagicMock()
        
        # 10개 보유 중 정확히 10개 매도 - 성공해야 함
        result = _apply_trade_to_asset(asset, "SELL", 10, 120, now)
        
        assert result == (120 - 100) * 10  # 200원 이익
        assert asset.amount < ZERO_TOLERANCE or asset.amount == 0
        assert asset.tags == "past"

    def test_sell_with_insufficient_balance_small_fraction(self):
        """소수점 잔액보다 미세하게 더 많이 매도 시 에러"""
        asset = MockAsset(amount=5.5)
        
        with pytest.raises(HTTPException) as exc:
            _apply_trade_to_asset(
                asset,
                trade_type="SELL",
                quantity=6,  # 5.5개 보유 중 6개 매도 시도
                price=100,
                now=MagicMock(),
            )
        assert exc.value.status_code == 400
        assert "more than current" in exc.value.detail.lower()


class TestBuyLogic:
    """매수 로직 테스트"""

    def test_buy_updates_amount_and_avg_price(self):
        """매수 시 수량/평균 단가 갱신"""
        asset = MockAsset(amount=100, purchase_price=50)
        now = MagicMock()

        # 추가 매수: 50주 @ 60원
        result = _apply_trade_to_asset(asset, "BUY", 50, 60, now)

        assert result is None  # 매수 시 실현손익 없음
        assert asset.amount == 150  # 100 + 50
        # 새 평균: (100*50 + 50*60) / 150 = 8000 / 150 ≈ 53.33
        expected_avg = (100 * 50 + 50 * 60) / 150
        assert abs(asset.purchase_price - expected_avg) < 0.01
        assert asset.current_price == 60
        assert asset.tags == "present"


class TestSellLogic:
    """매도 로직 테스트"""

    def test_sell_calculates_realized_profit(self):
        """매도 시 실현손익 계산"""
        asset = MockAsset(amount=100, purchase_price=50, realized_profit=0)
        now = MagicMock()

        # 매도: 20주 @ 80원 (평단가 50원에서 80원에 매도 → 이익)
        result = _apply_trade_to_asset(asset, "SELL", 20, 80, now)

        expected_profit = (80 - 50) * 20  # 600원 이익
        assert result == expected_profit
        assert asset.amount == 80
        assert asset.realized_profit == expected_profit
        assert asset.tags == "present"

    def test_sell_all_marks_asset_as_past(self):
        """전체 매도 시 태그가 past로 변경"""
        asset = MockAsset(amount=10, purchase_price=100, realized_profit=0)
        now = MagicMock()

        result = _apply_trade_to_asset(asset, "SELL", 10, 150, now)

        assert asset.amount < ZERO_TOLERANCE or asset.amount == 0
        assert asset.tags == "past"
        assert result == (150 - 100) * 10  # 500원 이익


class TestAssetNotFound:
    """자산을 찾을 수 없는 경우 테스트"""

    def test_asset_not_found_raises_404(self):
        """존재하지 않는 자산에 거래 시도 시 404"""
        db = MagicMock()
        # query chain이 None을 반환하도록 설정
        db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = None

        payload = TradeCreate(
            asset_id=999,
            type="BUY",
            quantity=10,
            price=100,
        )
        with pytest.raises(HTTPException) as exc:
            create_trade_with_sync(db, user_id=1, item=payload)
        assert exc.value.status_code == 404
        assert "not found" in exc.value.detail.lower()
