
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from backend.core.db import SessionLocal
from backend.core.models import Asset, PortfolioSnapshot
from backend.integrations.kis.kis_client import fetch_kis_prices_krw, fetch_usdkrw_rate
from backend.services.portfolio import PortfolioService

logger = logging.getLogger(__name__)


async def send_kis_alert(message: str, level: str = "WARNING") -> None:
    """KIS 관련 알림을 텔레그램으로 전송"""
    try:
        from backend.services.telegram import send_telegram_message
        prefix = "🟡" if level == "WARNING" else "🔴" if level == "ERROR" else "ℹ️"
        await send_telegram_message(f"{prefix} [KIS Alert] {message}")
        logger.info("[KIS Alert] 텔레그램 알림 전송: %s", message)
    except Exception as e:
        logger.error("[KIS Alert] 텔레그램 알림 전송 실패: %s", e)


def send_kis_alert_sync(message: str, level: str = "WARNING") -> None:
    """동기 버전의 KIS 알림 전송"""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(send_kis_alert(message, level))
        else:
            asyncio.run(send_kis_alert(message, level))
    except RuntimeError:
        asyncio.run(send_kis_alert(message, level))


class MarketDataService:
    @staticmethod
    def sync_all_prices(db: Session) -> int:
        """
        포트폴리오의 모든 자산 시세를 KIS를 통해 동기화합니다.
        (기존 sync_prices.sh의 로직을 파이썬으로 이식)
        """
        # 1. 활성 티커 목록 추출
        assets = db.query(Asset).filter(Asset.ticker.isnot(None)).all()
        tickers = sorted({a.ticker for a in assets if a.ticker})
        
        if not tickers:
            logger.info("No tickers found to sync.")
            return 0
            
        logger.info(f"Syncing prices for {len(tickers)} tickers...")
        
        # 2. KIS 시세 조회
        try:
            # KRW 기반 시세와 환율 조회
            prices = fetch_kis_prices_krw(tickers)
            rate = fetch_usdkrw_rate()
            
            # 3. DB 업데이트
            updated_count = 0
            for asset in assets:
                if asset.ticker in prices:
                    new_price = prices[asset.ticker]
                    # 해외 주식인 경우 환율 적용 고려가 필요할 수 있으나, 
                    # fetch_kis_prices_krw 내부 로직에 따라 처리됨을 가정
                    # (기존 /api/kis/prices 엔드포인트 로직과 동일하게 작동하도록 보완 필요)
                    asset.current_price = new_price
                    asset.updated_at = datetime.now()
                    updated_count += 1
            
            db.commit()
            logger.info(f"Successfully updated {updated_count} assets.")
            return updated_count
            
        except Exception as e:
            logger.error(f"Failed to sync prices: {e}")
            db.rollback()
            raise e

    @staticmethod
    def sync_all_prices_safe(db: Session) -> Dict[str, Any]:
        """
        Graceful Degradation 적용된 시세 동기화.
        
        실패 시 마지막 스냅샷 데이터를 반환하며 서비스 중단을 방지합니다.
        
        Returns:
            {
                "updated_count": int,
                "stale": bool,
                "last_updated_at": datetime | None,
                "error": str | None
            }
        """
        try:
            updated_count = MarketDataService.sync_all_prices(db)
            return {
                "updated_count": updated_count,
                "stale": False,
                "last_updated_at": datetime.now(),
                "error": None,
            }
        except Exception as e:
            error_msg = str(e)
            logger.error(f"[Graceful Degradation] 시세 동기화 실패, 스냅샷 폴백: {error_msg}")
            
            # 텔레그램 알림 전송
            send_kis_alert_sync(f"시세 동기화 실패: {error_msg}", level="ERROR")
            
            # 마지막 스냅샷 조회
            last_snapshot = (
                db.query(PortfolioSnapshot)
                .order_by(PortfolioSnapshot.created_at.desc())
                .first()
            )
            
            last_updated_at = last_snapshot.created_at if last_snapshot else None
            
            return {
                "updated_count": 0,
                "stale": True,
                "last_updated_at": last_updated_at,
                "error": error_msg,
            }

    @staticmethod
    def take_portfolio_snapshot(db: Session):
        """
        현재 포트폴리오 상태의 스냅샷을 저장합니다.
        """
        from backend.services.portfolio import PortfolioService
        try:
            # PortfolioService.take_snapshot 구현체 호출
            # (기존 /api/portfolio/snapshots 엔드포인트 로직 호출)
            PortfolioService.create_snapshot(db)
            logger.info("Portfolio snapshot captured.")
        except Exception as e:
            logger.error(f"Failed to take snapshot: {e}")
            raise e
