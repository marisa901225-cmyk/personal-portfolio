import logging
import asyncio
import json
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any
from zoneinfo import ZoneInfo
from backend.integrations.fred.fred_client import fred_client
from .ecos_client import ecos_client
from backend.core.config import settings
from ..duckdb_refine_config import get_db_path
from ..news.core import determine_news_tags, is_blocked_google_source

logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
SNAPSHOT_CACHE_PATH = Path(__file__).resolve().parents[2] / "storage" / "economy_snapshot" / "morning_0620.json"
_PREMARKET_PRIMARY_KEYWORDS = (
    "증시",
    "코스피",
    "코스닥",
    "주식시장",
    "환율",
    "원달러",
    "원/달러",
    "원·달러",
    "금리",
    "국채",
    "채권",
    "연준",
    "fomc",
    "fed",
    "cpi",
    "pce",
    "inflation",
    "인플레이션",
    "물가",
    "유가",
    "oil",
    "treasury",
    "yield",
    "외국인",
    "수급",
    "s&p",
    "nasdaq",
    "dow",
    "stock futures",
    "interest rate",
    "federal reserve",
    "futures",
    "ftse",
    "dax",
    "stoxx",
)
_PREMARKET_CONTEXT_KEYWORDS = (
    "전망",
    "장전",
    "개장전",
    "개장 전",
    "전략",
    "시황",
    "관전",
    "관전 포인트",
    "체크포인트",
    "브리핑",
    "outlook",
    "ahead of",
    "before",
    "opening bell",
    "market watch",
    "market wrap",
)
_PREMARKET_EXCLUDE_KEYWORDS = (
    "주주총회",
    "주총",
    "아파트",
    "분양",
    "세금",
    "할증료",
    "채권투자",
    "브랜드평판",
    "맛집",
    "쿠폰",
)
_PREMARKET_CRYPTO_KEYWORDS = (
    "crypto",
    "bitcoin",
    "ethereum",
    "xrp",
    "비트코인",
    "이더리움",
    "가상자산",
    "코인",
)

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
    def _extract_recent_daily_rows(
        daily_payload: Dict[str, Any],
        limit: int = 2,
    ) -> list[Dict[str, Any]]:
        output2 = daily_payload.get("output2") or []
        if not isinstance(output2, list) or limit <= 0:
            return []

        rows = [row for row in output2 if isinstance(row, dict)]
        rows.sort(key=lambda row: str(row.get("stck_bsop_date") or ""), reverse=True)
        return rows[:limit]

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
    def _format_daily_index_lines(label: str, daily_payload: Dict[str, Any]) -> list[str]:
        rows = EconomyService._extract_recent_daily_rows(daily_payload, limit=2)
        if not rows:
            return []

        lines: list[str] = []
        for row in rows:
            date = row.get("stck_bsop_date")
            close = EconomyService._safe_float(row.get("bstp_nmix_prpr"))
            delta = EconomyService._safe_float(row.get("bstp_nmix_prdy_vrss"))
            pct = EconomyService._safe_float(row.get("bstp_nmix_prdy_ctrt"))
            sign = row.get("prdy_vrss_sign")
            delta = EconomyService._apply_sign(sign, delta)
            pct = EconomyService._apply_sign(sign, pct)

            if close is None:
                continue

            detail = []
            if delta is not None:
                detail.append(f"전일대비 {delta:+.2f}")
            if pct is not None:
                detail.append(f"{pct:+.2f}%")
            detail_str = f" ({', '.join(detail)})" if detail else ""
            date_label = str(date).strip() if date else "날짜미상"
            lines.append(f"- {label}({date_label}): <b>{close:.2f}</b>{detail_str}")

        return lines

    @staticmethod
    def _format_market_outlook_rows(
        rows: list[tuple[str, str, str, str | None]],
        section_title: str,
    ) -> list[str]:
        if not rows:
            return []

        lines = [section_title]
        for source_name, category_tag, title, published_at in rows:
            source = str(source_name or "").strip()
            if source == "GoogleNews" or source.startswith("Google/"):
                source = "Google"
            elif not source:
                source = "Unknown"

            label = str(category_tag or "").strip() or "General"
            time_label = ""
            published_str = str(published_at or "").strip()
            if published_str:
                time_label = published_str[:16].replace("T", " ")
            prefix = f"- {time_label} | " if time_label else "- "
            lines.append(f"{prefix}[{source}/{label}] {title}")
        return lines

    @staticmethod
    def _normalize_topic_text(*parts: Any) -> str:
        text = " ".join(str(part or "") for part in parts).lower()
        text = text.replace("&", " and ")
        text = text.replace("·", "").replace("/", "")
        text = re.sub(r"[-_]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    @staticmethod
    def _parse_db_datetime(value: Any) -> datetime:
        if isinstance(value, datetime):
            return value
        raw = str(value or "").strip()
        if not raw:
            return datetime.min
        normalized = raw.replace("T", " ")
        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            try:
                return datetime.strptime(normalized[:19], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return datetime.min

    @staticmethod
    def _market_outlook_score(
        source_name: str,
        category_tag: str,
        title: str,
        content: str | None = None,
    ) -> int:
        if not title:
            return -99

        if source_name.startswith("Google/") and is_blocked_google_source(source_name.removeprefix("Google/")):
            return -99

        text = EconomyService._normalize_topic_text(title, content or "")
        if any(keyword in text for keyword in _PREMARKET_CRYPTO_KEYWORDS):
            return -99

        score = 0
        if category_tag in {"Market", "Macro", "FX/Rates"}:
            score += 3
        elif category_tag in {"Tech/Semicon", "EV/Auto"}:
            score += 1
        elif category_tag == "General":
            score -= 1

        primary_hits = sum(1 for keyword in _PREMARKET_PRIMARY_KEYWORDS if keyword in text)
        context_hits = sum(1 for keyword in _PREMARKET_CONTEXT_KEYWORDS if keyword in text)
        exclude_hits = sum(1 for keyword in _PREMARKET_EXCLUDE_KEYWORDS if keyword in text)

        score += primary_hits * 2
        score += context_hits
        score -= exclude_hits * 4

        if category_tag in {"Tech/Semicon", "EV/Auto", "General"} and primary_hits < 2 and context_hits <= 0:
            score -= 2

        return score

    @staticmethod
    def _select_market_outlook_rows(
        rows: list[tuple[str, str, str, str | None, str | None]],
        *,
        limit: int,
    ) -> list[tuple[str, str, str, str | None]]:
        scored: list[tuple[int, datetime, tuple[str, str, str, str | None]]] = []
        seen_titles: set[str] = set()

        for source_name, category_tag, title, published_at, full_content in rows:
            normalized_title = EconomyService._normalize_topic_text(title)
            if not normalized_title or normalized_title in seen_titles:
                continue

            _game_tag, normalized_category, _is_international = determine_news_tags(
                category="economy",
                query="",
                title=str(title or ""),
                description=str(full_content or ""),
                gl="KR" if str(source_name or "") == "Naver" else "US",
            )

            score = EconomyService._market_outlook_score(
                str(source_name or ""),
                normalized_category,
                str(title or ""),
                full_content,
            )
            if score < 3:
                continue

            seen_titles.add(normalized_title)
            scored.append(
                (
                    score,
                    EconomyService._parse_db_datetime(published_at),
                    (source_name, normalized_category, title, published_at),
                )
            )

        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [row for _score, _published_at, row in scored[:limit]]

    @staticmethod
    def load_market_outlook_news_context(
        *,
        db_path: Optional[str] = None,
        now: Optional[datetime] = None,
        lookback_hours: int = 12,
        limit_per_source: int = 3,
    ) -> str:
        """장전 브리핑용 시장전망 뉴스를 DB에서 읽어온다."""
        now_kst = (now or datetime.now(KST))
        if now_kst.tzinfo is None:
            now_kst = now_kst.replace(tzinfo=KST)
        else:
            now_kst = now_kst.astimezone(KST)

        db_file = db_path or get_db_path()
        if not db_file or not Path(db_file).exists():
            return "데이터 없음"

        since = now_kst.replace(tzinfo=None) - timedelta(hours=max(1, lookback_hours))
        until = now_kst.replace(tzinfo=None)
        since_str = since.strftime("%Y-%m-%d %H:%M:%S")
        until_str = until.strftime("%Y-%m-%d %H:%M:%S")
        limit = max(1, int(limit_per_source))
        fetch_limit = max(limit * 8, 40)

        domestic_sql = """
            SELECT
                COALESCE(source_name, '') AS source_name,
                COALESCE(category_tag, '') AS category_tag,
                title,
                COALESCE(published_at, created_at) AS published_at,
                COALESCE(full_content, '') AS full_content
            FROM game_news
            WHERE source_type = 'news'
              AND COALESCE(source_name, '') = 'Naver'
              AND datetime(COALESCE(published_at, created_at)) >= datetime(?)
              AND datetime(COALESCE(published_at, created_at)) <= datetime(?)
            ORDER BY datetime(COALESCE(published_at, created_at)) DESC
            LIMIT ?
        """
        global_sql = """
            SELECT
                COALESCE(source_name, '') AS source_name,
                COALESCE(category_tag, '') AS category_tag,
                title,
                COALESCE(published_at, created_at) AS published_at,
                COALESCE(full_content, '') AS full_content
            FROM game_news
            WHERE source_type = 'news'
              AND datetime(COALESCE(published_at, created_at)) >= datetime(?)
              AND datetime(COALESCE(published_at, created_at)) <= datetime(?)
              AND (
                    COALESCE(source_name, '') = 'GoogleNews' OR
                    COALESCE(source_name, '') LIKE 'Google/%' OR
                    COALESCE(game_tag, '') LIKE 'GlobalMacro-%' OR
                    COALESCE(is_international, 0) = 1
              )
            ORDER BY datetime(COALESCE(published_at, created_at)) DESC
            LIMIT ?
        """

        try:
            with sqlite3.connect(db_file) as conn:
                cur = conn.cursor()
                domestic_rows = list(cur.execute(domestic_sql, (since_str, until_str, fetch_limit)))
                global_rows = list(cur.execute(global_sql, (since_str, until_str, fetch_limit)))
        except Exception as exc:
            logger.error("Failed to load market outlook news context: %s", exc, exc_info=True)
            return "데이터 없음"

        domestic_rows = EconomyService._select_market_outlook_rows(domestic_rows, limit=limit)
        global_rows = EconomyService._select_market_outlook_rows(global_rows, limit=limit)

        lines: list[str] = []
        lines.extend(EconomyService._format_market_outlook_rows(domestic_rows, "[국내 시장전망 뉴스]"))
        lines.extend(EconomyService._format_market_outlook_rows(global_rows, "[해외 시장전망 뉴스]"))
        return "\n".join(lines).strip() or "데이터 없음"

    @staticmethod
    def format_snapshot_for_llm(
        snapshot: Dict[str, Any],
        *,
        include_intraday_kr_indices: bool = True,
    ) -> str:
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
            if include_intraday_kr_indices and kr_data.get("kospi") is not None:
                lines.append(f"- 코스피: <b>{kr_data['kospi']:.2f}</b>")
            if include_intraday_kr_indices and kr_data.get("kosdaq") is not None:
                lines.append(f"- 코스닥: <b>{kr_data['kosdaq']:.2f}</b>")

            kospi_daily = kr_data.get("kospi_daily")
            if isinstance(kospi_daily, dict):
                lines.extend(EconomyService._format_daily_index_lines("코스피", kospi_daily))

            kosdaq_daily = kr_data.get("kosdaq_daily")
            if isinstance(kosdaq_daily, dict):
                lines.extend(EconomyService._format_daily_index_lines("코스닥", kosdaq_daily))
        
        return "\n".join(lines).strip()
