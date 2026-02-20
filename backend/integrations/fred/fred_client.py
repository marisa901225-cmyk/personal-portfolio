import logging
from typing import Optional
import pandas as pd
from fredapi import Fred
from backend.core.config import settings

logger = logging.getLogger(__name__)

class FredClient:
    """
    미국 연방준비은행(FRED) API 클라이언트
    싱글톤 패턴으로 구현하여 API 연결을 관리합니다.
    """
    _instance: Optional['FredClient'] = None
    _fred: Optional[Fred] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(FredClient, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        # 중복 초기화 방지
        if self._fred is not None:
            return

        api_key = settings.fred_api_key
        if not api_key:
            logger.warning("FRED_API_KEY가 설정되지 않았습니다. FRED 관련 기능을 사용할 수 없습니다.")
            return

        try:
            self._fred = Fred(api_key=api_key)
            logger.info("FRED API 클라이언트가 성공적으로 초기화되었습니다.")
        except Exception as e:
            logger.error(f"FRED API 클라이언트 초기화 실패: {e}")

    @property
    def is_available(self) -> bool:
        return self._fred is not None

    def get_series(self, series_id: str, observation_start: Optional[str] = None, observation_end: Optional[str] = None) -> Optional[pd.Series]:
        """
        특정 데이터 시리즈를 조회합니다.
        
        Args:
            series_id (str): FRED 시리즈 ID (예: 'FEDFUNDS' - 기준금리, 'T10Y2Y' - 장단기 금리차)
            observation_start (str): 시작일 (YYYY-MM-DD)
            observation_end (str): 종료일 (YYYY-MM-DD)
        """
        if not self.is_available:
            logger.error("FRED 클라이언트를 사용할 수 없습니다. API 키를 확인하세요.")
            return None

        try:
            return self._fred.get_series(series_id, observation_start, observation_end)
        except Exception as e:
            logger.error(f"FRED 데이터({series_id}) 조회 실패: {e}")
            return None

    def get_fed_funds_rate(self) -> Optional[float]:
        """미국 연방 기금 금리(기준금리) 최신값을 가져옵니다."""
        series = self.get_series('FEDFUNDS')
        if series is not None and not series.empty:
            return float(series.iloc[-1])
        return None

    def get_10y_2y_spread(self) -> Optional[float]:
        """미국 10년물 - 2년물 국채 금리차 최신값을 가져옵니다."""
        series = self.get_series('T10Y2Y')
        if series is not None and not series.empty:
            return float(series.iloc[-1])
        return None

    def get_m2_money_stock(self) -> Optional[float]:
        """미국 통화량 M2 (WM2NS) 최신값을 가져옵니다."""
        series = self.get_series('WM2NS')
        if series is not None and not series.empty:
            return float(series.iloc[-1])
        return None

    def get_cpi(self) -> Optional[float]:
        """미국 소비자물가지수 (CPIAUCSL) 최신값을 가져옵니다."""
        series = self.get_series('CPIAUCSL')
        if series is not None and not series.empty:
            return float(series.iloc[-1])
        return None

    def get_unemployment_rate(self) -> Optional[float]:
        """미국 실업률 (UNRATE) 최신값을 가져옵니다."""
        series = self.get_series('UNRATE')
        if series is not None and not series.empty:
            return float(series.iloc[-1])
        return None

    def get_high_yield_spread(self) -> Optional[float]:
        """하이일드 채권 스프레드 (BAMLH0A0HYM2) 최신값을 가져옵니다."""
        series = self.get_series('BAMLH0A0HYM2')
        if series is not None and not series.empty:
            return float(series.iloc[-1])
        return None

    def get_vix(self) -> Optional[float]:
        """VIX 지수 (VIXCLS) 최신값을 가져옵니다."""
        series = self.get_series('VIXCLS')
        if series is not None and not series.empty:
            # VIX는 주말에 NaN이 포함될 수 있으므로 유효한 마지막 값 찾기
            valid_series = series.dropna()
            if not valid_series.empty:
                return float(valid_series.iloc[-1])
        return None

    def get_economic_snapshot(self) -> dict:
        """모든 핵심 경제 지표를 한 번에 조회하여 스냅샷으로 반환합니다."""
        return {
            "fed_funds_rate": self.get_fed_funds_rate(),
            "m2_money_stock": self.get_m2_money_stock(),
            "spread_10y_2y": self.get_10y_2y_spread(),
            "cpi": self.get_cpi(),
            "unemployment_rate": self.get_unemployment_rate(),
            "high_yield_spread": self.get_high_yield_spread(),
            "vix": self.get_vix()
        }

# 싱글톤 인스턴스 노출
fred_client = FredClient()
