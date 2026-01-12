import re
import logging
import joblib
import os
import json
from datetime import datetime
from typing import List, Optional
from sqlalchemy.orm import Session
from ..core.models import IncomingAlarm, Expense
from ..integrations.telegram import send_telegram_message

logger = logging.getLogger(__name__)

# NB 모델 경로
MODEL_PATH = os.path.join(os.path.dirname(__file__), "../data/expense_model.joblib")

from .alarm.filters import mask_otp, is_spam, is_promo_spam, is_whitelisted, should_ignore
from .alarm.sanitizer import infer_source, escape_html_preserve_urls, sanitize_llm_output
from .alarm.parsers import parse_card_approval

class AlarmService:
    _llm_instance = None

    @classmethod
    def get_llm(cls):
        """
        LLM 인스턴스를 싱글톤으로 반환한다.
        """
        model_path = os.getenv("LOCAL_LLM_MODEL_PATH", "backend/data/gemma-3-4b-it-q4_k_m.gguf")
        if cls._llm_instance is None:
            try:
                from llama_cpp import Llama
                if os.path.exists(model_path):
                    logger.info(f"Loading LLM model from {model_path}...")
                    cls._llm_instance = Llama(model_path=model_path, n_ctx=2048, verbose=False)
                else:
                    logger.warning(f"LLM model not found at {model_path}")
            except ImportError:
                logger.error("llama-cpp-python not installed.")
            except Exception as e:
                logger.error(f"Failed to load LLM: {e}")
        return cls._llm_instance


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
                # TODO: LLM Random Message Improvements
                # - [x] UX Refinement
                # - [x] Remove redundant prefixes from random messages
                # - [x] Improve LLM message variety (bye bye penguins/dogs)
                logger.info(f"No alarms, but skipping random message (minute={current_minute}, not 10-min interval)")
                return None  # 메시지 안 보냄
            
            # 매 시간 정각(:00)에 LLM 세션 리셋 (주제 집착 방지)
            if current_minute == 0:
                llm_service.reset_context()
                logger.info("Hourly LLM context reset performed.")
            
            random_prompt = """<start_of_turn>user
You are a witty personal assistant. There are no notifications.
Say something random and entertaining - choose ONE from: a dad joke, a pun, a fun fact/TMI (재미있는 상식), useless trivia, a bizarre science fact, or a "would you rather" question.
CRITICAL: Write ONLY in Korean. No English. 
CRITICAL: Be extremely creative. Do NOT keep talking about the same topics. Pick from diverse topics like: food, weird history, absurd museums, failed inventions, unusual animals, ancient technology, bizarre laws, obscure sports, pop culture, video games, science, astronomy, psychology, or pure nonsense.
One or two sentences max. Be silly but fresh. Start directly. Do NOT use "왜냐하면" or "because".

Output:<end_of_turn>
<start_of_turn>model
"""
            logger.info("No alarms to process. Asking LLM for random wisdom...")
            result = llm_service.generate(random_prompt, max_tokens=128, temperature=0.9)
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

        # Gemma-3에 최적화된 프롬프트 구성 (English Prompt for better 3-bit performance)
        prompt = f"""<start_of_turn>user
You are a witty and competent personal assistant. Summarize the following smartphone notifications strictly in Korean. Use NO English in your final summary.

[Rules]
1. Group similar topics and write in concise Korean bullet points.
2. Include the app name or sender information for each item.
3. **ONLY include URLs that are EXPLICITLY present in the original notifications. NEVER invent or guess URLs.**
4. **NEVER output self-referential or meta phrases like "I will summarize", "Here is the summary", "비서의 말투로 작성해드리겠습니다", etc. Just output the actual summary content directly.**
5. **Exclude all ads, spam, or low-value messages.**
6. Use casual-polite Korean (해요체). Be friendly and slightly witty.
7. Write ONLY in Korean. No English.
8. **CRITICAL: You MUST NOT mention any app/service name that is not explicitly present in the [앱: ...] context. Do not invent service names like "Credo".**
9. **If a notification item has no URL in its text, do NOT mention any URL for that item.**
10. **Do NOT hallucinate or invent information. Only summarize what is explicitly stated in the notifications. If information is unclear, say so instead of guessing.**
11. **NEVER make up numbers, statistics, stages, levels, or any specific details that were not in the original message.**

[Notifications]
{chr(10).join(notification_list)}

Summary (in Korean):<end_of_turn>
<start_of_turn>model
"""
        logger.info(f"LLM Prompt: {prompt}")
        result = llm_service.generate(prompt, max_tokens=512)
        logger.info(f"LLM Response: {result}")
        
        # 환각 제거 후 반환
        result = sanitize_llm_output(items, result)
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

        prompt = f"""<start_of_turn>user
You are a financial assistant. Analyze the following payment records and provide a short, witty one-sentence analysis in Korean about the user's spending patterns or characteristics.
Start directly with the result without any introductory phrases or greetings.

[Payments]
{chr(10).join(expense_list)}

Analysis (in Korean):<end_of_turn>
<start_of_turn>model
"""
        return llm_service.generate(prompt, max_tokens=128)

    @classmethod
    async def process_pending_alarms(cls, db: Session):
        """
        수신된 알림들을 5분 배차로 처리한다.
        알람이 없을 때는 LLM이 랜덤으로 재미있는 말을 한다.
        """
        pending = db.query(IncomingAlarm).filter(IncomingAlarm.status == "pending").all()
        
        # 알람이 없을 때도 처리 (LLM 랜덤 메시지용)
        # if not pending:
        #     return

        summaries = []
        to_summarize_alarms = []
        to_analyze_expenses = []
        senders = set()
        has_expenses = False
        
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
            # 1. 마스킹 및 스팸 필터링 (보안 및 1단계)
            masked_text = mask_otp(alarm.raw_text)
            
            # 태스크어 변수가 아직 치환되지 않은 경우 필터링
            if "%antext" in masked_text or "%evtprm" in masked_text:
                alarm.status = "discarded"
                alarm.classification = "placeholder"
                continue

            # 1.3 무시할 알림인지 확인 (인증번호 등)
            if should_ignore(masked_text):
                alarm.status = "discarded"
                alarm.classification = "ignored"
                logger.info(f"Alarm ignored (OTP/Security): {masked_text[:30]}...")
                continue

            # 1.5 화이트리스트 체크 (스팸 필터보다 우선)
            if not is_whitelisted(masked_text):
                is_spam_result, classification = is_spam(masked_text, db)
                if is_spam_result:
                    alarm.status = "discarded"
                    alarm.classification = classification
                    continue

                if is_promo_spam(masked_text, db):
                    alarm.status = "discarded"
                    alarm.classification = "promo_rule"
                    continue
            else:
                logger.info(f"Alarm whitelisted: {masked_text[:50]}...")

            if alarm.sender:
                senders.add(alarm.sender)

            # 2. 카드 승인 내역 시도
            card_info = parse_card_approval(masked_text)
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

            # 3. 그 외 알림 (요약 대상)
            alarm.status = "processed"
            alarm.classification = "llm" 
            to_summarize_alarms.append({
                "text": masked_text,
                "sender": alarm.sender,
                "app_name": alarm.app_name,
                "package": alarm.package,
                "app_title": alarm.app_title,
                "conversation": alarm.conversation
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
                title = "일일 체크인"  # 알람도 없고 결제도 없을 때

            sender_info = f" ({', '.join(list(senders)[:3])}{'...' if len(senders) > 3 else ''})" if senders else ""
            header = f"<b>[{title}]{sender_info}</b>\n\n"
            summary_text = header + "\n".join(summaries)
            await send_telegram_message(summary_text)

        # 24시간 지난 데이터 삭제 (TTL) 로직은 별도 스케줄러에서 수행 권장
