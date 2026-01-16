# backend/services/alarm/processor.py
# 420줄 alarm_service.py에서 추출한 알람 처리 로직
import logging
import os
import html
import joblib
from datetime import datetime
from typing import List, Set
from sqlalchemy.orm import Session

from ...core.models import IncomingAlarm, Expense, SpamAlarm
from ...integrations.telegram import send_telegram_message
from .filters import (
    mask_sensitive_info,
    is_spam,
    is_promo_spam,
    is_whitelisted,
    should_ignore,
    is_spam_llm,
    is_review_spam,
)
from .parsers import parse_card_approval
from .sanitizer import escape_html_preserve_urls
from .llm_logic import summarize_with_llm, summarize_expenses_with_llm
from .match_notifier import check_upcoming_matches

logger = logging.getLogger(__name__)

# NB 모델 경로
MODEL_PATH = os.path.join(os.path.dirname(__file__), "../../data/expense_model.joblib")

# NB 모델 싱글톤 캐싱
_nb_pipeline = None


def _get_nb_pipeline():
    """지출 분류 NB 모델을 싱글톤으로 로드한다."""
    global _nb_pipeline
    if _nb_pipeline is None and os.path.exists(MODEL_PATH):
        try:
            _nb_pipeline = joblib.load(MODEL_PATH)
            logger.info("NB expense classifier loaded")
        except Exception as e:
            logger.warning(f"Failed to load NB model: {e}")
    return _nb_pipeline


async def process_pending_alarms(db: Session):
    """
    수신된 알림들을 5분 배차로 처리한다.
    알람이 없을 때는 LLM이 랜덤으로 재미있는 말을 한다.
    안정성: 배치 처리 (200개 제한) + 선점(processing 상태)
    """
    # 안정성: 배치 단위로 끊고, 순서 보장, 처리 전 선점
    pending = (
        db.query(IncomingAlarm)
        .filter(IncomingAlarm.status == "pending")
        .order_by(IncomingAlarm.id.asc())
        .limit(200)
        .all()
    )
    
    # 선점: 중복 실행 방지 (processing으로 먼저 마킹)
    for alarm in pending:
        alarm.status = "processing"
    if pending:
        db.commit()
    
    # 경기 시작 알림 체크 (별도 try/except로 감싸서 실패해도 메인 처리 계속)
    try:
        # 보안: v2 우선, v1 폴백
        data_dir = os.path.join(os.path.dirname(__file__), "../../data")
        catchphrases_candidates = [
            os.path.join(data_dir, "esports_catchphrases_v2.json"),
            os.path.join(data_dir, "esports_catchphrases.json"),
        ]
        catchphrases_file = next((p for p in catchphrases_candidates if os.path.exists(p)), catchphrases_candidates[0])
        await check_upcoming_matches(db, catchphrases_file)
    except Exception as e:
        logger.warning(f"Match notification check failed: {e}")
    
    # 알람이 없을 때도 처리 (LLM 랜덤 메시지용)
    # if not pending:
    #     return

    summaries: List[str] = []
    to_summarize_alarms: List[dict] = []
    to_analyze_expenses: List[dict] = []
    senders: Set[str] = set()
    has_expenses = False
    
    # 필터링 통계 추적
    filtered_count = 0
    filtered_reasons = {"광고/프로모션": 0, "OTP/보안": 0, "플레이스홀더": 0}
    
    # NB 모델 로드 (싱글톤 캐싱)
    nb_pipeline = _get_nb_pipeline()

    # 기본 사용자 정보 가져오기
    from ...services.users import get_or_create_single_user
    user = get_or_create_single_user(db)

    for alarm in pending:
        # 1. 원문(unmasked)과 마스킹된 텍스트 확보
        # DB에 masked_text가 있으면 사용, 없으면 온더플라이 마스킹
        original_text = alarm.raw_text
        masked_text = (alarm.masked_text if hasattr(alarm, "masked_text") and alarm.masked_text 
                       else mask_sensitive_info(original_text))
        
        # 마스킹 및 스팸 필터링 (보안 및 1단계)
        
        # 태스크어 변수가 아직 치환되지 않은 경우 필터링 (원문 기준 체크)
        if "%antext" in original_text or "%evtprm" in original_text:
            alarm.status = "discarded"
            alarm.classification = "placeholder"
            # SpamAlarm에 저장
            db.add(SpamAlarm(
                raw_text=alarm.raw_text, masked_text=masked_text, sender=alarm.sender,
                app_name=alarm.app_name, package=alarm.package, app_title=alarm.app_title,
                conversation=alarm.conversation, classification="placeholder",
                discard_reason="Tasker placeholder",
                rule_version=1
            ))
            filtered_count += 1
            filtered_reasons["플레이스홀더"] += 1
            continue

        # 1.3 무시할 알림인지 확인 (인증번호 등 - 원문 기준 체크)
        if should_ignore(original_text):
            alarm.status = "discarded"
            alarm.classification = "ignored"
            # SpamAlarm에 저장
            db.add(SpamAlarm(
                raw_text=alarm.raw_text, masked_text=masked_text, sender=alarm.sender,
                app_name=alarm.app_name, package=alarm.package, app_title=alarm.app_title,
                conversation=alarm.conversation, classification="ignored",
                discard_reason="OTP/Security filter",
                rule_version=1
            ))
            filtered_count += 1
            filtered_reasons["OTP/보안"] += 1
            logger.info(f"Alarm ignored (OTP/Security): {masked_text[:30]}...")
            continue

        # 1.5 화이트리스트 및 스팸 체크 (본문 + 발신자 + 제목 합쳐서 검사)
        # 발신자나 제목에만 (광고)가 적혀 있는 경우를 잡기 위함
        # 보안: 룰/AI 텝터는 원문, LLM 필터는 masked
        full_check_text = f"[{alarm.sender or ''}] {alarm.app_title or ''} {original_text}"
        full_check_text_llm = f"[{mask_sensitive_info(alarm.sender or '')}] {mask_sensitive_info(alarm.app_title or '')} {masked_text}"
        
        if not is_whitelisted(full_check_text):
            # 리뷰 요청 / 게임 이벤트 필터링 추가
            if is_review_spam(full_check_text):
                alarm.status = "discarded"
                alarm.classification = "review_spam"
                db.add(SpamAlarm(
                    raw_text=alarm.raw_text, masked_text=masked_text, sender=alarm.sender,
                    app_name=alarm.app_name, package=alarm.package, app_title=alarm.app_title,
                    conversation=alarm.conversation, classification="review_spam",
                    discard_reason="Review/Rating request",
                    rule_version=1
                ))
                filtered_count += 1
                filtered_reasons["광고/프로모션"] += 1
                continue
            
            is_spam_result, classification = is_spam(full_check_text, db)
            if is_spam_result:
                alarm.status = "discarded"
                alarm.classification = classification
                db.add(SpamAlarm(
                    raw_text=alarm.raw_text, masked_text=masked_text, sender=alarm.sender,
                    app_name=alarm.app_name, package=alarm.package, app_title=alarm.app_title,
                    conversation=alarm.conversation, classification=classification,
                    discard_reason="Spam rule match",
                    rule_version=1
                ))
                filtered_count += 1
                filtered_reasons["광고/프로모션"] += 1
                continue

            if is_promo_spam(full_check_text, db):
                alarm.status = "discarded"
                alarm.classification = "promo_rule"
                db.add(SpamAlarm(
                    raw_text=alarm.raw_text, masked_text=masked_text, sender=alarm.sender,
                    app_name=alarm.app_name, package=alarm.package, app_title=alarm.app_title,
                    conversation=alarm.conversation, classification="promo_rule",
                    discard_reason="Promotion rule match",
                    rule_version=1
                ))
                filtered_count += 1
                filtered_reasons["광고/프로모션"] += 1
                continue
            
            # 1.6 LLM 기반 스팸 필터링 (실험적 단계 - 화이트리스트가 아닐 때만)
            # 보안: LLM에는 masked 텍스트만 전달 (민감정보 노출 방지)
            is_spam_llm_result, classification = is_spam_llm(full_check_text_llm)
            if is_spam_llm_result:
                alarm.status = "discarded"
                alarm.classification = classification
                db.add(SpamAlarm(
                    raw_text=alarm.raw_text, masked_text=masked_text, sender=alarm.sender,
                    app_name=alarm.app_name, package=alarm.package, app_title=alarm.app_title,
                    conversation=alarm.conversation, classification=classification,
                    discard_reason="LLM spam classification",
                    rule_version=1
                ))
                filtered_count += 1
                filtered_reasons["광고/프로모션"] += 1
                continue
        else:
            logger.info(f"Alarm whitelisted: {masked_text[:50]}...")

        if alarm.sender:
            senders.add(alarm.sender)

        # 2. 카드 승인 내역 시도 (정확한 파싱을 위해 원문 사용)
        card_info = parse_card_approval(original_text)
        if card_info:
            # 가맹점 분류 고도화 (NB 적용)
            category = "기타"
            if nb_pipeline and card_info["merchant"]:
                try:
                    category = nb_pipeline.predict([card_info["merchant"]])[0]
                except:
                    pass
            
            # 가계부 DB 저장
            expense = Expense(
                user_id=user.id,
                date=card_info["date"],
                amount=card_info["amount"],
                merchant=card_info["merchant"],
                method=card_info["method"],
                category=category,
                is_fixed=False
            )
            db.add(expense)
            alarm.status = "processed"
            alarm.classification = "rule"
            
            has_expenses = True
            to_analyze_expenses.append({
                "merchant": card_info["merchant"],
                "amount": card_info["amount"],
                "category": category
            })
            
            merchant_esc = html.escape(card_info['merchant'])
            summaries.append(f"💳 <b>결제 승인</b>: {merchant_esc} ({abs(card_info['amount']):,.0f}원)")
            continue

        # 3. 그 외 알림 (요약 대상 - 이미 마스킹된 정보를 리스트에 담음)
        alarm.status = "processed"
        alarm.classification = "llm" 
        to_summarize_alarms.append({
            "text": masked_text,
            "sender": mask_sensitive_info(alarm.sender) if alarm.sender else None,
            "app_name": alarm.app_name,
            "package": alarm.package,
            "app_title": mask_sensitive_info(alarm.app_title) if alarm.app_title else None,
            "conversation": mask_sensitive_info(alarm.conversation) if alarm.conversation else None
        })

    # 가계부 리포트 (Expense 인사이트)
    if to_analyze_expenses:
        expense_insight = await summarize_expenses_with_llm(to_analyze_expenses)
        if expense_insight:
            summaries.insert(0, f"💰 <b>지출 분석</b>: {html.escape(expense_insight)}\n")

    # 일반 알림 요약 (알람이 없어도 LLM이 랜덤 메시지 생성)
    llm_summary = await summarize_with_llm(to_summarize_alarms)
    if llm_summary:
        # URL은 보존하고 이외 텍스트만 이스케이프
        safe_summary = escape_html_preserve_urls(llm_summary)
        
        if to_summarize_alarms:
            summaries.append("\n<b>[주요 알림 요약]</b>\n" + safe_summary)
        else:
            # 알람이 없을 때는 헤더 없이 LLM 랜덤 메시지만
            summaries.append(safe_summary)

    db.commit()

    # 텔레그램 요약 전송
    if summaries:
        # 동적 헤더 결정
        if has_expenses and to_summarize_alarms:
            title = "알림 및 가계부 리포트"
        elif has_expenses:
            title = "가계부 리포트"
        elif to_summarize_alarms:
            title = "알림 리포트"
        else:
            # 알람도 없고 결제도 없을 때 - 다양한 제목 사용
            random_titles = [
                "랜덤 토픽",
                "잡학사전",
                "브레이크 타임",
                "오늘의 TMI",
                "잠깐 쉬어가기",
                "심심풀이 지식"
            ]
            title_index = (datetime.now().minute // 10) % len(random_titles)
            title = random_titles[title_index]

        sender_info = f" ({', '.join(list(senders)[:3])}{'...' if len(senders) > 3 else ''})" if senders else ""
        header = f"<b>[{title}]{sender_info}</b>\n\n"
        
        # 필터링 통계 추가 (알람이나 결제가 있을 때만, 랜덤 메시지에는 표시 안 함)
        if filtered_count > 0 and (to_summarize_alarms or has_expenses):
            filter_details = []
            for reason, count in filtered_reasons.items():
                if count > 0:
                    filter_details.append(f"{reason} {count}개")
            if filter_details:
                header += f"🗑️ <i>필터링됨: {', '.join(filter_details)}</i>\n\n"
        
        summary_text = header + "\n".join(summaries)
        
        # 유료 백엔드 폴백 사용 시 💰 표시 (파이프라인 오염 방지를 위해 전송 직전에만)
        try:
            from ..llm.service import LLMService
            if LLMService._instance and LLMService._instance.last_used_paid():
                summary_text = f"💰 {summary_text}"
                logger.info("LLM fallback to paid backend detected, adding 💰 prefix")
        except Exception:
            pass
        
        await send_telegram_message(summary_text)

    # 24시간 지난 데이터 삭제 (TTL) 로직은 별도 스케줄러에서 수행 권장
