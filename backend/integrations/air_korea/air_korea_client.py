import logging
import httpx
from datetime import datetime
from typing import Optional, Dict, Any, List
from backend.core.config import settings

logger = logging.getLogger(__name__)

class AirKoreaClient:
    """에어코리아(한국환경공단) 미세먼지 경보 정보 조회 API 클라이언트"""
    
    BASE_URL = "http://apis.data.go.kr/B552584/UlfptcaAlarmInqireSvc"
    
    def __init__(self):
        pass

    async def get_latest_active_alarm(self, district_name: str = "서울") -> Optional[Dict[str, Any]]:
        """
        최신 미세먼지/초미세먼지 경보 현황을 조회합니다.
        해제되지 않은(clearDate가 없는) 가장 최신 경보를 반환합니다.
        """
        service_key = settings.kma_service_key
        if not service_key:
            return None

        current_year = datetime.now().year
        
        params = {
            "serviceKey": service_key,
            "returnType": "json",
            "numOfRows": 100,
            "pageNo": 1,
            "year": current_year,
            "itemCode": "" # 빈값으로 두면 PM10, PM25 모두 조회
        }

        try:
            async with httpx.AsyncClient() as client:
                # 엔드포인트: /getUlfptcaAlarmInfo
                response = await client.get(f"{self.BASE_URL}/getUlfptcaAlarmInfo", params=params, timeout=10.0)
                
                if response.status_code == 200:
                    data = response.json()
                    
                    # response > body > items
                    items = data.get("response", {}).get("body", {}).get("items", [])
                    if not items:
                        return None
                    
                    # 해당 지역(districtName)의 경보 중 해제되지 않은 것 우선
                    # items는 보통 최신순으로 정렬되어 있음
                    for item in items:
                        if item.get("districtName") == district_name:
                            # clearDate가 없거나 현재 시각보다 미래면 아직 발령 중으로 간주
                            if not item.get("clearDate"):
                                return item
                    
                    # 발령 중인 게 없으면 해당 지역의 가장 최신 데이터 반환
                    for item in items:
                        if item.get("districtName") == district_name:
                            return item
                            
                else:
                    logger.error(f"AirKorea API HTTP error: {response.status_code}")
                    logger.error(f"Response: {response.text}")
        except Exception as e:
            logger.error(f"Failed to fetch dust alarm from AirKorea: {e}")
        
        return None

air_korea_client = AirKoreaClient()
