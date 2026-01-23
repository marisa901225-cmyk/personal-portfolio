
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
        from backend.integrations.telegram import send_telegram_message
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
    def sync_all_prices(db: Session, mock: bool = False) -> int:
        """
        포트폴리오의 모든 자산 시세를 KIS를 통해 동기화합니다.
        (기존 sync_prices.sh의 로직을 파이썬으로 이식)
        """
        # 1. 활성 티커 목록 추출
        assets = db.query(Asset).filter(Asset.ticker.isnot(None)).all()
        
        if not assets:
            logger.info("No assets found to sync.")
            return 0
            
        if mock:
            import random
            logger.info(f"Mock syncing prices for {len(assets)} assets...")
            for asset in assets:
                # 0.95 ~ 1.05 사이의 랜덤 변동폭 적용
                current = asset.current_price or 10000.0
                asset.current_price = round(current * random.uniform(0.95, 1.05), 2)
                asset.updated_at = datetime.now()
            db.commit()
            return len(assets)

        tickers = sorted({a.ticker for a in assets if a.ticker})
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
    def sync_all_prices_safe(db: Session, mock: bool = False) -> Dict[str, Any]:
        """
        Graceful Degradation 적용된 시세 동기화.
        """
        try:
            updated_count = MarketDataService.sync_all_prices(db, mock=mock)
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
        from backend.services.users import get_or_create_single_user
        try:
            user = get_or_create_single_user(db)
            PortfolioService.create_snapshot(db, user.id)
            logger.info(f"Portfolio snapshot captured for user_id={user.id}")
        except Exception as e:
            logger.error(f"Failed to take snapshot: {e}")
            raise e
    @staticmethod
    async def generate_creative_msg(ticker_count: int, mock: bool = False) -> str:
        """
        LLM을 사용하여 창의적인 업데이트 메시지 생성
        """
        from backend.services.llm_service import LLMService
        from backend.services.prompt_loader import load_prompt
        import os
        from pytz import timezone

        KST = timezone("Asia/Seoul")
        prefix = "[MOCK] " if mock else ""
        
        try:
            llm = LLMService.get_instance()
            if not llm.is_loaded():
                return f"{prefix}💰 시세 업데이트 완료!\n- 총 {ticker_count}개 종목\n- {datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')} 기준"

            # 외부 프롬프트 파일에서 로드 (핫 리로드 지원)
            prompt_content = load_prompt("sync_prices", ticker_count=ticker_count)
            if not prompt_content:
                # 폴백: 파일이 없으면 기본 메시지
                return f"{prefix}💰 {ticker_count}개 종목 시세 업데이트 완료!"
            
            messages = [
                {
                    "role": "system",
                    "content": "너는 자산 관리 비서야. 사용자의 주식/자산 시세 동기화가 완료되었음을 알리는 친근하고 활기찬 메시지를 작성해줘."
                },
                {
                    "role": "user",
                    "content": prompt_content
                }
            ]
            creative_text = llm.generate_chat(messages, max_tokens=256, temperature=0.9)
            
            # 클린업: "성공!" 같은 단순 응답 방지 및 종목 수 확인
            if len(creative_text.strip()) < 5 or str(ticker_count) not in creative_text:
                # LLM이 너무 짧게 답하거나 숫자를 빼먹은 경우 강제로 정보 보강
                info_text = f"💰 {ticker_count}개 종목 업데이트 완료!"
                if creative_text.strip():
                    creative_text = f"{creative_text.strip()}\n\n{info_text}"
                else:
                    creative_text = info_text
            
            sync_time = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
            return f"{prefix}{creative_text.strip()}\n\n🕒 {sync_time} 기준"
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            return f"{prefix}💰 시세 업데이트 완료!\n- 총 {ticker_count}개 종목\n- {datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')} 기준"

    @staticmethod
    async def notify_sync_completion(ticker_count: int, mock: bool = False):
        """
        시세 동기화 완료 알림 전송
        """
        from backend.integrations.telegram import send_telegram_message
        
        try:
            msg = await MarketDataService.generate_creative_msg(ticker_count, mock=mock)
            # 봇 타입을 'main'으로 명시하여 DB 백업 봇으로 발송
            await send_telegram_message(msg, bot_type="main")
            logger.info("Price sync notification sent.")
        except Exception as e:
            logger.error(f"Failed to send sync notification: {e}")
