import re
import logging
import joblib
import os
import json
from datetime import datetime
from typing import List, Optional
from sqlalchemy.orm import Session
from ..core.models import IncomingAlarm, Expense, SpamAlarm
from ..integrations.telegram import send_telegram_message

logger = logging.getLogger(__name__)

# NB 모델 경로
MODEL_PATH = os.path.join(os.path.dirname(__file__), "../data/expense_model.joblib")

from .alarm.filters import mask_sensitive_info, is_spam, is_promo_spam, is_whitelisted, should_ignore, is_spam_llm, is_review_spam
from .alarm.sanitizer import infer_source, escape_html_preserve_urls, sanitize_llm_output, clean_exaone_tokens
from .alarm.parsers import parse_card_approval
from .alarm.match_notifier import check_upcoming_matches
from .alarm.processor import process_alarms_batch
from .prompt_loader import load_prompt

class AlarmService:
    @classmethod
    async def summarize_with_llm(cls, items: List[dict]) -> str:
        """
        3단계: Local LLM (llama-cpp-python)을 사용하여 여러 알림을 요약한다.
        items: [{"text": "...", "sender": "..."}, ...]
        알람이 없을 때는 LLM이 랜덤으로 재미있는 말을 한다.
        """
        from .llm_service import LLMService
        llm_service = LLMService.get_instance()
        
        if not llm_service.is_loaded():
            if not items:
                return "🤖 LLM 모델이 로드되지 않았습니다... 알람도 없고, 모델도 없네요 😅"
            return "\n".join([f"- [{item['sender']}] {item['text']}" for item in items])
        
        # 알람이 없을 때: 재미있는 말 하기 모드 (10분 간격으로만)
        if not items:
            from datetime import datetime
            current_minute = datetime.now().minute
            # 10분 간격이 아니면 조용히 스킵 (:00, :10, :20, :30, :40, :50만 전송)
            if current_minute % 10 != 0:
                logger.info(f"No alarms, but skipping random message (minute={current_minute}, not 10-min interval)")
                return None  # 메시지 안 보냄
            
            # 매 시간 정각(:00)에 LLM 세션 리셋 (주제 집착 방지)
            if current_minute == 0:
                llm_service.reset_context()
                logger.info("Hourly LLM context reset performed.")
            
            # 현재 시간의 분(minute)을 기반으로 카테고리 & 형식 강제 선택 (다양성 확보)
            category_index = (current_minute // 10) % 5  # 0~4 범위
            format_index = (datetime.now().hour + category_index) % 5  # 시간 + 카테고리로 형식도 분산
            
            categories = [
                "지식/과학 (우주, 물리학, 생물학, 기술사, 수학 퍼즐)",
                "역사/문화 (고대문명, 이상한 역사, 폐기된 발명품, 기묘한 법률)",
                "엔터/취미 (게임 트리비아, e스포츠, 마이너 스포츠, 영화/드라마 비하인드)",
                "언어유희/드립 (말장난, 아재개그, 논리 역설, 수수께끼)",
                "철학/심리 (사고실험, 심리학 실험, 인지 편향, 재미있는 통계)"
            ]
            
            # 문장 시작 형식도 강제 (반복 방지)
            formats = [
                "질문형으로 시작해라 (예: '혹시 알아?' / '이거 들어봤어?')",
                "팩트 단언형으로 시작해라 (예: '사실...' / '진짜 신기한 건...')",
                "감탄형으로 시작해라 (예: '와!' / '헐!' / '대박!')",
                "수수께끼/퀴즈형으로 시작해라 (예: 'OO는 왜 OO일까?')",
                "선택형으로 시작해라 (예: 'A vs B 중 뭐가 나을까?')"
            ]
            
            forced_category = categories[category_index]
            forced_format = formats[format_index]
            
            # 외부 프롤프트 파일에서 로드 (핵 리로드 지원)
            prompt_content = load_prompt("random_topic", category=forced_category, format=forced_format)
            if not prompt_content:
                # 펴백: 파일이 없으면 기본 메시지
                return "🤔 오늘도 심심한 하루... 뭐 재미있는 거 없나?"
            
            messages = [
                {
                    "role": "user",
                    "content": prompt_content
                }
            ]
            
            logger.info("No alarms to process. Asking LLM for random wisdom...")
            result = llm_service.generate_chat(messages, max_tokens=128, temperature=0.9)
            logger.info(f"LLM Random Response: {result}")
            return result

        
        # 알림 목록 구성 (발신자 포함)
        notification_list = []
        for item in items:
            source = infer_source(item)
            title = item.get('app_title') or ""
            conv = item.get('conversation') or ""
            text = item.get('text') or ""
            
            # Tasker 변수가 치환 안 된 경우 제외
            if title.startswith('%'): title = ""
            if conv.startswith('%'): conv = ""
            
            context = f"[앱: {source}]"
            if title: context += f" 제목: {title}"
            if conv: context += f" 발신/대화: {conv}"
            
            notification_list.append(f"- {context} 본문: {text}")

        # 외부 프롤프트 파일에서 로드 (핵 리로드 지원)
        notifications_str = chr(10).join(notification_list)
        prompt_content = load_prompt("alarm_summary", notifications=notifications_str)
        
        if not prompt_content:
            # 펴백: 파일이 없으면 기본 포맷 사용
            prompt_content = f"아래 스마트폰 알림들을 한국어로 요약해줘:\n{notifications_str}"
        
        messages = [
            {
                "role": "user",
                "content": prompt_content
            }
        ]
        
        logger.info(f"LLM Chat Messages: {messages}")
        total_prompt_len = sum(len(m['content']) for m in messages)
        logger.info(f"LLM Prompt total length: {total_prompt_len} characters")
        result = llm_service.generate_chat(messages, max_tokens=512)
        logger.info(f"LLM Response: {result}")
        
        # 환각 제거 및 특수 토큰 제거 후 반환
        result = sanitize_llm_output(items, result)
        result = clean_exaone_tokens(result)
        return result

    @classmethod
    async def summarize_expenses_with_llm(cls, expenses: List[dict]) -> str:
        """
        가계부 내역(결제 승인)을 분석하여 짧은 코멘트를 생성한다.
        """
        if not expenses:
            return ""
        
        from .llm_service import LLMService
        llm_service = LLMService.get_instance()
        
        if not llm_service.is_loaded():
            return ""

        expense_list = []
        for e in expenses:
            expense_list.append(f"- {e['merchant']}: {abs(e['amount']):,.0f}원 ({e['category']})")

        messages = [
            {"role": "user", "content": f"""You are a financial assistant. Analyze the following payment records and provide a short, witty one-sentence analysis in Korean about the user's spending patterns or characteristics.
Start directly with the result without any introductory phrases or greetings.

[Payments]
{chr(10).join(expense_list)}"""}
        ]
        result = llm_service.generate_chat(messages, max_tokens=128)
        return clean_exaone_tokens(result)

    @classmethod
    async def process_pending_alarms(cls, db: Session):
        """
        수신된 알림들을 5분 배차로 처리한다.
        알람이 없을 때는 LLM이 랜덤으로 재미있는 말을 한다.
        """
        pending = db.query(IncomingAlarm).filter(IncomingAlarm.status == "pending").all()
        
        # 경기 시작 알림 체크 (별도 try/except로 감싸서 실패해도 메인 처리 계속)
        try:
            catchphrases_file = os.path.join(os.path.dirname(__file__), "../data/esports_catchphrases.json")
            await check_upcoming_matches(db, catchphrases_file)
        except Exception as e:
            logger.warning(f"Match notification check failed: {e}")
        
        # 알람이 없을 때도 처리 (LLM 랜덤 메시지용)
        # if not pending:
        #     return

        summaries = []
        to_summarize_alarms = []
        to_analyze_expenses = []
        senders = set()
        has_expenses = False
        
        # 필터링 통계 추적
        filtered_count = 0
        filtered_reasons = {"광고/프로모션": 0, "OTP/보안": 0, "플레이스홀더": 0}
        
        # NB 모델 로드 (캐싱 가능)
        nb_pipeline = None
        if os.path.exists(MODEL_PATH):
            try:
                nb_pipeline = joblib.load(MODEL_PATH)
            except Exception as e:
                logger.warning(f"Failed to load NB model: {e}")

        # 기본 사용자 정보 가져오기
        from ..services.users import get_or_create_single_user
        user = get_or_create_single_user(db)

        import html

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
            full_check_text = f"[{alarm.sender or ''}] {alarm.app_title or ''} {original_text}"
            
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
                is_spam_llm_result, classification = is_spam_llm(full_check_text)
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
            expense_insight = await cls.summarize_expenses_with_llm(to_analyze_expenses)
            if expense_insight:
                summaries.insert(0, f"💰 <b>지출 분석</b>: {html.escape(expense_insight)}\n")

        # 일반 알림 요약 (알람이 없어도 LLM이 랜덤 메시지 생성)
        llm_summary = await cls.summarize_with_llm(to_summarize_alarms)
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
            await send_telegram_message(summary_text)

        # 24시간 지난 데이터 삭제 (TTL) 로직은 별도 스케줄러에서 수행 권장
