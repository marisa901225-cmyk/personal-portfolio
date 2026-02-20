import logging
import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
from zoneinfo import ZoneInfo
from backend.integrations.fred.fred_client import fred_client
from .ecos_client import ecos_client
from backend.core.config import settings

logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
SNAPSHOT_CACHE_PATH = Path(__file__).resolve().parents[2] / "storage" / "economy_snapshot" / "morning_0620.json"

class EconomyService:
    """
    글로벌 및 국내 경제 지표를 통합 관리하는 서비스.
    FRED(미국), ECOS(한국은행) 등의 데이터를 수집합니다.
    """
    
    @staticmethod
    def _save_morning_snapshot_cache(snapshot: Dict[str, Any]) -> None:
        """06:20 수집 스냅샷을 파일 캐시에 저장한다."""
        try:
            SNAPSHOT_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "collected_at": datetime.now(KST).isoformat(),
                "snapshot": snapshot,
            }
            with open(SNAPSHOT_CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            logger.info("Morning economy snapshot cache saved: %s", SNAPSHOT_CACHE_PATH.name)
        except Exception as e:
            logger.error("Failed to save morning snapshot cache: %s", e, exc_info=True)

    @staticmethod
    def load_morning_snapshot_cache() -> Optional[Dict[str, Any]]:
        """오늘 06:20 이후 수집된 경제 스냅샷 캐시를 읽어온다."""
        try:
            if not SNAPSHOT_CACHE_PATH.exists():
                return None

            with open(SNAPSHOT_CACHE_PATH, "r", encoding="utf-8") as f:
                payload = json.load(f)

            collected_at_raw = payload.get("collected_at")
            snapshot = payload.get("snapshot")
            if not collected_at_raw or not isinstance(snapshot, dict):
                return None

            collected_at = datetime.fromisoformat(str(collected_at_raw))
            if collected_at.tzinfo is None:
                collected_at = collected_at.replace(tzinfo=KST)
            else:
                collected_at = collected_at.astimezone(KST)

            now = datetime.now(KST)
            if collected_at.date() != now.date():
                return None
            if (collected_at.hour, collected_at.minute) < (6, 20):
                return None

            return snapshot
        except Exception as e:
            logger.error("Failed to load morning snapshot cache: %s", e, exc_info=True)
            return None

    @staticmethod
    async def prefetch_morning_snapshot_cache() -> None:
        """06:20 실행용: 경제 스냅샷을 미리 수집해 캐시에 저장한다."""
        snapshot = await EconomyService.get_morning_snapshot()
        EconomyService._save_morning_snapshot_cache(snapshot)

    @staticmethod
    async def get_morning_snapshot() -> Dict[str, Any]:
        """
        모닝 브리핑용 핵심 경제 지표 스냅샷을 생성합니다.
        """
        snapshot = {
            "us": {},
            "kr": {},
            "timestamp": datetime.now().isoformat()
        }
        
        # 비동기 병렬 수집
        tasks = [
            EconomyService._fetch_us_snapshot(),
            EconomyService._fetch_kr_snapshot()
        ]
        results = await asyncio.gather(*tasks)
        
        snapshot["us"] = results[0]
        snapshot["kr"] = results[1]
        
        return snapshot

    @staticmethod
    async def _fetch_us_snapshot() -> Dict[str, Any]:
        """미국 경제 실시간 지표 수집 (VIX만)"""
        us_data = {}
        try:
            if settings.fred_api_key:
                # VIX 지수만 수집 (매일 변동)
                vix = fred_client.get_vix()
                if vix is not None:
                    us_data["vix"] = vix
        except Exception as e:
            logger.error(f"Failed to fetch US economic snapshot: {e}")
        return us_data

    @staticmethod
    async def _fetch_kr_snapshot() -> Dict[str, Any]:
        """한국 시장 실시간 지표 수집 (환율, 코스피/코스닥 지수)"""
        kr_data = {}
        try:
            # KIS API: 실시간 시장 데이터
            from ...integrations.kis.kis_client import fetch_usdkrw_rate
            from ...integrations.kis.kis_index import (
                fetch_kospi_index,
                fetch_kosdaq_index,
                fetch_index_daily_prices,
            )
            
            # 환율 수집
            usd_krw = fetch_usdkrw_rate()
            if usd_krw:
                kr_data["usd_krw"] = usd_krw
            
            # 코스피/코스닥 지수 수집
            kospi = fetch_kospi_index()
            if kospi:
                kr_data["kospi"] = kospi
            
            kosdaq = fetch_kosdaq_index()
            if kosdaq:
                kr_data["kosdaq"] = kosdaq

            # 코스피/코스닥 일자별 지수 (최근 1일 기준)
            today = datetime.now().strftime("%Y%m%d")
            kospi_daily = fetch_index_daily_prices("0001", today, period="D")
            if kospi_daily:
                kr_data["kospi_daily"] = kospi_daily
            kosdaq_daily = fetch_index_daily_prices("1001", today, period="D")
            if kosdaq_daily:
                kr_data["kosdaq_daily"] = kosdaq_daily
                
        except Exception as e:
            logger.error(f"Failed to fetch KR market snapshot: {e}")
        return kr_data

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(str(value).replace(",", ""))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _extract_latest_daily(daily_payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        output2 = daily_payload.get("output2") or []
        if not isinstance(output2, list) or not output2:
            return None
        latest = None
        latest_date = ""
        for row in output2:
            if not isinstance(row, dict):
                continue
            date = str(row.get("stck_bsop_date") or "")
            if date > latest_date:
                latest_date = date
                latest = row
        return latest

    @staticmethod
    def _apply_sign(sign_code: Any, value: Optional[float]) -> Optional[float]:
        if value is None:
            return None
        sign = str(sign_code or "").strip()
        if sign in {"4", "5"}:
            return -abs(value)
        if sign in {"1", "2"}:
            return abs(value)
        return value

    @staticmethod
    def format_snapshot_for_llm(snapshot: Dict[str, Any]) -> str:
        """
        스냅샷 데이터를 LLM 프롬프트용 텍스트로 변환합니다.
        """
        lines = []
        
        # 1. 미국 지표 (VIX만)
        us_data = snapshot.get("us", {})
        if us_data.get("vix") is not None:
            lines.append("[미국 시장]")
            lines.append(f"- VIX(공포지수): <b>{us_data['vix']:.2f}</b>")
        
        # 2. 한국 시장 (실시간 지표만)
        kr_data = snapshot.get("kr", {})
        if any(v is not None for v in kr_data.values()):
            lines.append("[한국 시장]")
            if kr_data.get("usd_krw") is not None: 
                lines.append(f"- 원/달러 환율: <b>{kr_data['usd_krw']:.2f}원</b>")
            if kr_data.get("kospi") is not None: 
                lines.append(f"- 코스피: <b>{kr_data['kospi']:.2f}</b>")
            if kr_data.get("kosdaq") is not None: 
                lines.append(f"- 코스닥: <b>{kr_data['kosdaq']:.2f}</b>")

            kospi_daily = kr_data.get("kospi_daily")
            if isinstance(kospi_daily, dict):
                latest = EconomyService._extract_latest_daily(kospi_daily)
                if latest:
                    date = latest.get("stck_bsop_date")
                    close = EconomyService._safe_float(latest.get("bstp_nmix_prpr"))
                    delta = EconomyService._safe_float(latest.get("bstp_nmix_prdy_vrss"))
                    pct = EconomyService._safe_float(latest.get("bstp_nmix_prdy_ctrt"))
                    sign = latest.get("prdy_vrss_sign")
                    delta = EconomyService._apply_sign(sign, delta)
                    pct = EconomyService._apply_sign(sign, pct)
                    if close is not None:
                        detail = []
                        if delta is not None:
                            detail.append(f"전일대비 {delta:+.2f}")
                        if pct is not None:
                            detail.append(f"{pct:+.2f}%")
                        detail_str = f" ({', '.join(detail)})" if detail else ""
                        date_str = f"{date} " if date else ""
                        lines.append(f"- 코스피(일자별 {date_str}): <b>{close:.2f}</b>{detail_str}")

            kosdaq_daily = kr_data.get("kosdaq_daily")
            if isinstance(kosdaq_daily, dict):
                latest = EconomyService._extract_latest_daily(kosdaq_daily)
                if latest:
                    date = latest.get("stck_bsop_date")
                    close = EconomyService._safe_float(latest.get("bstp_nmix_prpr"))
                    delta = EconomyService._safe_float(latest.get("bstp_nmix_prdy_vrss"))
                    pct = EconomyService._safe_float(latest.get("bstp_nmix_prdy_ctrt"))
                    sign = latest.get("prdy_vrss_sign")
                    delta = EconomyService._apply_sign(sign, delta)
                    pct = EconomyService._apply_sign(sign, pct)
                    if close is not None:
                        detail = []
                        if delta is not None:
                            detail.append(f"전일대비 {delta:+.2f}")
                        if pct is not None:
                            detail.append(f"{pct:+.2f}%")
                        detail_str = f" ({', '.join(detail)})" if detail else ""
                        date_str = f"{date} " if date else ""
                        lines.append(f"- 코스닥(일자별 {date_str}): <b>{close:.2f}</b>{detail_str}")
        
        return "\n".join(lines).strip()
