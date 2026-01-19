"""
Market Data Service

KIS(한국투자증권) 연동 비즈니스 로직을 담당하는 서비스 레이어.

- 시세 조회 및 자산 가격 동기화
- 티커 검색
- 환율 조회

라우터는 이 서비스를 호출하고 HTTP 예외 매핑만 담당한다.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Optional
from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep_log, retry_if_not_exception_type

from sqlalchemy.orm import Session

from ..integrations.kis import kis_client
from ..core.models import Asset
from ..core.time_utils import utcnow
from ..services.users import get_or_create_single_user

logger = logging.getLogger(__name__)


class MarketDataError(Exception):
    """Market Data 서비스의 기본 예외"""
    pass


class KisConfigurationError(MarketDataError):
    """KIS 설정/인증 문제 (RuntimeError → 500)"""
    pass


class KisApiError(MarketDataError):
    """KIS API 호출 실패 (기타 예외 → 502)"""
    pass


class EmptyResultError(MarketDataError):
    """조회 결과가 비어있음 (→ 502)"""
    pass


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_not_exception_type((KisConfigurationError, RuntimeError)),
    before_sleep=before_sleep_log(logger, logging.WARNING)
)
async def get_kis_prices_krw(
    tickers: List[str],
    db: Session,
    *,
    sync_to_assets: bool = True,
) -> Dict[str, float]:
    """
    KIS API를 통해 시세를 조회하고, 선택적으로 자산 테이블에 반영한다.

    Args:
        tickers: 조회할 티커 목록 (공백 제거됨)
        db: 데이터베이스 세션
        sync_to_assets: True면 조회된 가격을 Asset에 반영

    Returns:
        ticker → 가격(KRW) 매핑

    Raises:
        KisConfigurationError: KIS 인증/환경 설정 문제
        KisApiError: KIS API 호출 실패
        EmptyResultError: 조회 결과가 없음
    """
    # 공백 제거 및 필터링
    raw_tickers = [t.strip() for t in tickers if t and t.strip()]
    if not raw_tickers:
        raise ValueError("tickers list is empty")

    try:
        prices = await asyncio.to_thread(kis_client.fetch_kis_prices_krw, raw_tickers)
    except RuntimeError as exc:
        raise KisConfigurationError(str(exc)) from exc
    except Exception as exc:
        raise KisApiError(f"KIS price fetch failed: {exc}") from exc

    if not prices:
        raise EmptyResultError("no prices found for given tickers via KIS")

    # 자산 테이블에 가격 반영
    if sync_to_assets:
        _sync_prices_to_assets(db, prices)

    return prices


def _sync_prices_to_assets(db: Session, prices: Dict[str, float]) -> None:
    """
    조회된 가격을 포트폴리오 자산에 반영한다.

    실패해도 예외를 발생시키지 않고 로그만 남긴다 (기존 동작 유지).
    """
    try:
        user = get_or_create_single_user(db)
        tickers = list(prices.keys())
        if not tickers:
            return

        assets = (
            db.query(Asset)
            .filter(
                Asset.user_id == user.id,
                Asset.deleted_at.is_(None),
                Asset.ticker.in_(tickers),
            )
            .all()
        )

        now = utcnow()
        for asset in assets:
            if asset.ticker and asset.ticker in prices:
                asset.current_price = prices[asset.ticker]
                asset.updated_at = now

        if assets:
            db.commit()
    except Exception as exc:
        logger.warning("failed to persist synced prices: %s", exc)


async def search_tickers_by_name(query: str, limit: int = 5) -> List[Dict[str, Optional[str]]]:
    """
    종목명으로 KIS 티커를 검색한다.

    Args:
        query: 검색어
        limit: 최대 결과 수

    Returns:
        검색 결과 목록 [{symbol, name, exchange, currency, type}, ...]

    Raises:
        KisConfigurationError: KIS 마스터 파일 문제 등
        KisApiError: 검색 실패
    """
    try:
        return await asyncio.to_thread(kis_client.search_tickers_by_name, query, limit)
    except RuntimeError as exc:
        raise KisConfigurationError(str(exc)) from exc
    except Exception as exc:
        raise KisApiError(f"KIS ticker search failed: {exc}") from exc


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_not_exception_type((KisConfigurationError, RuntimeError)),
    before_sleep=before_sleep_log(logger, logging.WARNING)
)
async def get_usdkrw_rate() -> float:
    """
    KIS API를 통해 USD/KRW 환율을 조회한다.

    Returns:
        USD/KRW 환율

    Raises:
        KisConfigurationError: KIS 인증/환경 설정 문제
        KisApiError: KIS API 호출 실패
        EmptyResultError: 환율 조회 결과가 없음
    """
    try:
        rate = await asyncio.to_thread(kis_client.fetch_usdkrw_rate)
    except RuntimeError as exc:
        raise KisConfigurationError(str(exc)) from exc
    except Exception as exc:
        raise KisApiError(f"KIS FX fetch failed: {exc}") from exc

    if rate is None:
        raise EmptyResultError("no FX rate found from KIS")

    return rate
