import logging
import httpx
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from backend.core.config import settings

logger = logging.getLogger(__name__)

class EcosClient:
    BASE_URL = "https://ecos.bok.or.kr/api"

    def __init__(self):
        self.api_key = (settings.bok_ecos_api_key or "").strip()
        if not self.api_key:
            logger.warning("BOK_ECOS_API_KEY가 설정되지 않았습니다. 한국 경제 지표 수집이 불가능합니다.")

    def _build_stat_search_url(
        self,
        stat_code: str,
        cycle: str,
        start_time: str,
        end_time: str,
        item_codes: List[str],
        start_no: int = 1,
        end_no: int = 1,
    ) -> str:
        base = self.BASE_URL.rstrip("/")
        parts = [
            base, "StatisticSearch", self.api_key, "json", "kr",
            str(start_no), str(end_no),
            stat_code, cycle, start_time, end_time
        ]
        # ⚠️ 여기서 "?" 같은 플레이스홀더 금지: 있는 코드만 붙인다
        parts.extend([c for c in item_codes if c])
        return "/".join(parts) + "/"

    async def get_statistic_search(
        self,
        stat_code: str,
        cycle: str,
        start_time: str,
        end_time: str,
        item_code1: str,
        item_code2: str = "",
        item_code3: str = "",
        start_no: int = 1,
        end_no: int = 1,
    ) -> Optional[Dict[str, Any]]:
        if not self.api_key:
            return None

        if not item_code1:
            # 이 케이스가 네 ERROR-100 주범이다
            logger.warning(f"ECOS StatisticSearch requires item_code1 (stat_code={stat_code})")
            return None

        url = self._build_stat_search_url(
            stat_code=stat_code,
            cycle=cycle,
            start_time=start_time,
            end_time=end_time,
            item_codes=[item_code1, item_code2, item_code3],
            start_no=start_no,
            end_no=end_no,
        )

        try:
            async with httpx.AsyncClient() as client:
                logger.info(f"ECOS REQUEST: {url.replace(self.api_key, 'HIDDEN_KEY')}")
                r = await client.get(url, timeout=10.0)
                data = r.json()

                rows = data.get("StatisticSearch", {}).get("row")
                if rows:
                    return rows[-1]

                logger.warning(f"ECOS API error or no data ({stat_code}): {data}")
                return None
        except Exception as e:
            logger.error(f"Failed to fetch data from ECOS API: {e}")
            return None

    async def get_statistic_item_list(self, stat_code: str) -> List[Dict[str, Any]]:
        if not self.api_key:
            return []
        url = f"{self.BASE_URL.rstrip('/')}/StatisticItemList/{self.api_key}/json/kr/1/2000/{stat_code}/"
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(url, timeout=10.0)
                data = r.json()
                return data.get("StatisticItemList", {}).get("row", [])
        except Exception as e:
            logger.error(f"Failed to fetch item list for {stat_code}: {e}")
            return []

    async def fetch_auto_row(self, stat_code: str, name_keywords: List[str]) -> Optional[Dict[str, Any]]:
        items = await self.get_statistic_item_list(stat_code)

        target = None
        for it in items:
            name = it.get("ITEM_NAME", "")
            if all(k in name for k in name_keywords):
                target = it
                break
        if not target:
            logger.warning(f"Could not find item in {stat_code} with keywords {name_keywords}")
            return None

        item_code1 = target.get("ITEM_CODE", "")
        cycle = target.get("CYCLE", "")
        end_time = target.get("END_TIME", "")

        if not (item_code1 and cycle and end_time):
            logger.warning(f"Missing meta for {stat_code}: ITEM_CODE/CYCLE/END_TIME not found")
            return None

        # ✅ 제일 안전: 최신 공표 시점(END_TIME) "1건만" 찍는다
        return await self.get_statistic_search(
            stat_code=stat_code,
            cycle=cycle,
            start_time=end_time,
            end_time=end_time,
            item_code1=item_code1,
            start_no=1,
            end_no=1,
        )

    async def fetch_auto(self, stat_code: str, name_keywords: List[str]) -> Optional[float]:
        row = await self.fetch_auto_row(stat_code, name_keywords)
        if row and "DATA_VALUE" in row:
            return float(row["DATA_VALUE"])
        return None

    async def get_base_rate(self) -> Optional[float]:
        """한국은행 기준금리"""
        return await self.fetch_auto("722Y001", ["한국은행 기준금리"])

    async def get_base_rate_row(self) -> Optional[Dict[str, Any]]:
        """한국은행 기준금리 (원문 row)"""
        return await self.fetch_auto_row("722Y001", ["한국은행 기준금리"])

    async def get_cpi(self) -> Optional[float]:
        """소비자물가지수 (총지수)"""
        return await self.fetch_auto("901Y009", ["총지수"])

    async def get_m2(self) -> Optional[float]:
        """M2(광의통화) 평잔, 계절조정"""
        return await self.fetch_auto("101Y003", ["M2", "계절조정"])

    async def get_exchange_rate(self, currency: str = "미달러") -> Optional[float]:
        """환율 (원/달러 등)"""
        return await self.fetch_auto("731Y001", [currency, "매매기준율"])

    async def get_market_interest_rate(self, name: str = "국고채(3년)") -> Optional[float]:
        """시장금리 (일별)"""
        return await self.fetch_auto("060Y001", [name])

    async def get_stock_index(self, name: str = "코스피") -> Optional[float]:
        """주식지수 (일별)"""
        return await self.fetch_auto("802Y001", [name])

ecos_client = EcosClient()
