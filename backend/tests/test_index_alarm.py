"""
지수 과매도 알람 서비스 테스트

SPY/QQQ 지수 모니터링 로직과 Zone/State Machine을 검증합니다.
"""

import pytest
import pandas as pd
from datetime import datetime
from backend.services.index_alarm_service import (
    IndexState,
    OversoldZone,
    calculate_indicators,
    detect_zone,
    determine_state,
)


class TestIndicatorCalculation:
    """지표 계산 로직 테스트"""

    def test_calculate_indicators_basic(self):
        """기본 지표 계산 테스트"""
        # 샘플 데이터 생성 (50일치)
        dates = pd.date_range(start="2024-01-01", periods=220, freq="D")
        df = pd.DataFrame({
            "date": dates,
            "open": [100 + i * 0.5 for i in range(220)],
            "high": [102 + i * 0.5 for i in range(220)],
            "low": [98 + i * 0.5 for i in range(220)],
            "close": [100 + i * 0.5 for i in range(220)],
            "volume": [1000000] * 220,
        })

        result = calculate_indicators(df)

        # RSI, MA, BB 컬럼이 추가되었는지 확인
        assert "rsi" in result.columns
        assert "ma_120" in result.columns
        assert "ma_200" in result.columns
        assert "bb_upper" in result.columns
        assert "bb_lower" in result.columns

        # RSI 값이 0-100 범위 내인지 확인
        rsi_values = result["rsi"].dropna()
        assert (rsi_values >= 0).all() and (rsi_values <= 100).all()


class TestZoneDetection:
    """과매도 구간 감지 로직 테스트"""

    def test_zone_1_rsi_trigger(self):
        """Zone 1: RSI <= 35 조건"""
        row = pd.Series({
            "close": 100,
            "rsi": 34,
            "ma_120": 105,
            "ma_200": 110,
            "bb_lower": 95,
        })
        zone = detect_zone(row)
        assert zone == OversoldZone.ZONE_1

    def test_zone_1_bb_trigger(self):
        """Zone 1: BB 하단 터치 조건"""
        row = pd.Series({
            "close": 94,
            "rsi": 40,
            "ma_120": 105,
            "ma_200": 110,
            "bb_lower": 95,
        })
        zone = detect_zone(row)
        assert zone == OversoldZone.ZONE_1

    def test_zone_2_trigger(self):
        """Zone 2: RSI <= 30 AND 종가 < MA120"""
        row = pd.Series({
            "close": 100,
            "rsi": 29,
            "ma_120": 105,
            "ma_200": 110,
            "bb_lower": 95,
        })
        zone = detect_zone(row)
        assert zone == OversoldZone.ZONE_2

    def test_zone_3_trigger(self):
        """Zone 3: RSI <= 25 AND MA200 이격도 >= 5%"""
        row = pd.Series({
            "close": 93,  # 110에서 -15.45% = 5% 이상 이격
            "rsi": 24,
            "ma_120": 105,
            "ma_200": 110,
            "bb_lower": 90,
        })
        zone = detect_zone(row)
        assert zone == OversoldZone.ZONE_3

    def test_no_zone(self):
        """정상 범위 (구간 없음)"""
        row = pd.Series({
            "close": 106,
            "rsi": 50,
            "ma_120": 105,
            "ma_200": 110,
            "bb_lower": 95,
        })
        zone = detect_zone(row)
        assert zone == OversoldZone.NONE


class TestStateMachine:
    """State Machine 로직 테스트"""

    def test_normal_to_entry_watch(self):
        """NORMAL -> ENTRY_WATCH 전환 (Zone 1 진입)"""
        new_state = determine_state(
            current_zone=OversoldZone.ZONE_1,
            previous_state=IndexState.NORMAL,
            previous_rsi=40,
            current_rsi=34,
        )
        assert new_state == IndexState.ENTRY_WATCH

    def test_entry_watch_to_oversold(self):
        """ENTRY_WATCH -> OVERSOLD 전환 (Zone 2 진입)"""
        new_state = determine_state(
            current_zone=OversoldZone.ZONE_2,
            previous_state=IndexState.ENTRY_WATCH,
            previous_rsi=34,
            current_rsi=29,
        )
        assert new_state == IndexState.OVERSOLD

    def test_oversold_to_buy_signal(self):
        """OVERSOLD -> BUY_SIGNAL 전환 (RSI 30 상향 돌파)"""
        new_state = determine_state(
            current_zone=OversoldZone.NONE,
            previous_state=IndexState.OVERSOLD,
            previous_rsi=29,
            current_rsi=31,
        )
        assert new_state == IndexState.BUY_SIGNAL

    def test_buy_signal_to_normal(self):
        """BUY_SIGNAL -> NORMAL 복귀"""
        new_state = determine_state(
            current_zone=OversoldZone.NONE,
            previous_state=IndexState.BUY_SIGNAL,
            previous_rsi=31,
            current_rsi=35,
        )
        assert new_state == IndexState.NORMAL

    def test_oversold_maintenance(self):
        """OVERSOLD 상태 유지"""
        new_state = determine_state(
            current_zone=OversoldZone.ZONE_2,
            previous_state=IndexState.OVERSOLD,
            previous_rsi=28,
            current_rsi=27,
        )
        assert new_state == IndexState.OVERSOLD


@pytest.mark.asyncio
class TestEndToEnd:
    """E2E 시나리오 테스트 (모의 데이터 사용)"""

    async def test_check_index_oversold_mock(self):
        """과매도 체크 로직 통합 테스트 (실제 API 호출 없이 모의)"""
        # TODO: fetch_index_ohlcv를 모의하여 실제 KIS API 없이 테스트
        pass
