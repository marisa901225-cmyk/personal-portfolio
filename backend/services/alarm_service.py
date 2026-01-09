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
SPAM_MODEL_PATH = os.path.join(os.path.dirname(__file__), "../data/spam_model.joblib")
# LLM 모델 경로 (env에서 가져오거나 기본값)
LLM_MODEL_PATH = os.getenv("LOCAL_LLM_MODEL_PATH", "backend/data/gemma-3-4b-it-q4_k_m.gguf")

class AlarmService:
    _llm_instance = None
    _spam_model_instance = None

    @classmethod
    def get_llm(cls):
        """
        LLM 인스턴스를 싱글톤으로 반환한다.
        """
        if cls._llm_instance is None:
            try:
                from llama_cpp import Llama
                if os.path.exists(LLM_MODEL_PATH):
                    logger.info(f"Loading LLM model from {LLM_MODEL_PATH}...")
                    cls._llm_instance = Llama(model_path=LLM_MODEL_PATH, n_ctx=2048, verbose=False)
                else:
                    logger.warning(f"LLM model not found at {LLM_MODEL_PATH}")
            except ImportError:
                logger.error("llama-cpp-python not installed.")
            except Exception as e:
                logger.error(f"Failed to load LLM: {e}")
        return cls._llm_instance

    @classmethod
    def get_spam_model(cls):
        """
        스팸 분류용 NB 모델을 싱글톤으로 로드한다.
        """
        if cls._spam_model_instance is None:
            if os.path.exists(SPAM_MODEL_PATH):
                try:
                    import joblib
                    logger.info(f"Loading Spam AI model from {SPAM_MODEL_PATH}...")
                    cls._spam_model_instance = joblib.load(SPAM_MODEL_PATH)
                except Exception as e:
                    logger.error(f"Failed to load Spam AI model: {e}")
        return cls._spam_model_instance
    @staticmethod
    def mask_otp(text: str) -> str:
        """
        인증번호/OTP 패턴을 마스킹한다.
        """
        # 4-6자리 숫자 패턴 (앞뒤 문맥 고려)
        otp_patterns = [
            r'\[(?:인증번호|OTP|확인번호)\]\s*\d{4,6}',
            r'(?:인증번호|OTP|확인번호)는?\s*\[?\d{4,6}\]?',
            r'(?<=:)\s*\d{6}(?=\s)', # SMS 인증번호 특화
        ]
        masked_text = text
        for pattern in otp_patterns:
            masked_text = re.sub(pattern, "[인증번호 마스킹]", masked_text, flags=re.IGNORECASE)
        return masked_text

    @classmethod
    def is_spam(cls, text: str, db: Session) -> tuple[bool, str]:
        """
        스팸 필터링 (규칙 -> AI)
        Returns: (is_spam, classification)
        """
        from ..core.models import SpamRule
        
        rules = db.query(SpamRule).filter(
            SpamRule.is_enabled == True,
            SpamRule.rule_type.in_(["contains", "regex"])
        ).all()
        
        for rule in rules:
            if rule.rule_type == "contains":
                if rule.pattern in text:
                    logger.info(f"Spam filtered by DB rule (contains): {rule.pattern}")
                    return True, "rule"
            elif rule.rule_type == "regex":
                if re.search(rule.pattern, text):
                    logger.info(f"Spam filtered by DB rule (regex): {rule.pattern}")
                    return True, "rule"

        # 2단계: AI 기반 스팸 필터링 (Fallback)
        model = cls.get_spam_model()
        if model:
            try:
                # 1 이면 스팸, 0 이면 정상
                prediction = model.predict([text])[0]
                if prediction == 1:
                    probs = model.predict_proba([text])[0]
                    spam_prob = probs[1]
                    if spam_prob >= 0.8:
                        logger.info(f"Spam filtered by AI model (confidence: {spam_prob:.2%})")
                        return True, "nb"
            except Exception as e:
                logger.error(f"AI classification failed: {e}")

        return False, ""

    @classmethod
    def is_promo_spam(cls, text: str, db: Session) -> bool:
        """
        프로모션 + 긴급성 조합 스팸 필터링 (DB 규칙)
        """
        from ..core.models import SpamRule
        
        rules = db.query(SpamRule).filter(
            SpamRule.is_enabled == True,
            SpamRule.rule_type == "promo_combo"
        ).all()
        
        t = text.replace("\n", " ")
        
        for rule in rules:
            # pattern format: "promo1,promo2|urgency1,urgency2"
            parts = rule.pattern.split("|")
            if len(parts) != 2:
                continue
            promo_list = [p.strip() for p in parts[0].split(",")]
            urgency_list = [u.strip() for u in parts[1].split(",")]
            
            if any(p in t for p in promo_list) and any(u in t for u in urgency_list):
                logger.info(f"Promo spam filtered by DB rule: {rule.note or rule.pattern}")
                return True
        
        return False
        
    @classmethod
    def is_whitelisted(cls, text: str) -> bool:
        """
        중요 알림 키워드 화이트리스트 (스팸 필터링 방지)
        """
        # 스팸으로 오인되기 쉬우나 중요한 키워드들
        whitelist_keywords = [
            "현재가", "시세", "주가지수", "코스피", "코스닥", # 주식/금융
            "도착", "배송", "택배", "우체국", "AliExpress", # 배송
            "내역", "안내", "공지", "리포트" # 공식 정보
        ]
        
        # (광고)가 포함된 경우는 화이트리스트에서 제외 (강력한 스팸 신호)
        if "(광고)" in text:
            return False
            
        if any(kw in text for kw in whitelist_keywords):
            return True
            
        return False

    @classmethod
    def should_ignore(cls, text: str) -> bool:
        """
        텔레그램으로 전달할 필요가 없는 메시지인지 확인한다.
        """
        ignore_keywords = ["인증번호", "OTP", "인증 요청", "비밀번호 확인"]
        if any(kw in text for kw in ignore_keywords):
            return True
        return False

    @staticmethod
    def parse_card_approval(text: str):
        """
        카드 승인 내역 파싱 시도 (Regex)
        예: [Web발신] 우리카드(1234) 승인 15,000원 01/07 10:20 스타벅스
        """
        # 1) "승인/결제" 뒤에 금액이 오는 형태
        m = re.search(r'(?:승인|결제)\s*([0-9,]+)원', text)
        # 2) 보조: "15,000원 승인" 같은 반대 형태도 허용
        if not m:
            m = re.search(r'([0-9,]+)원\s*(?:승인|결제)', text)

        if not m:
            return None

        amount = float(m.group(1).replace(",", ""))
        
        # 시간 뒤 가맹점
        merchant_match = re.search(r'\d{2}/\d{2}\s+\d{2}:\d{2}\s+(.+)$', text)
        merchant = merchant_match.group(1).strip() if merchant_match else "알 수 없는 가맹점"
        
        # 카드사/카드 정보
        card_match = re.search(r'([^\s]+카드)', text)
        method = card_match.group(1) if card_match else "신용카드"

        return {
            "amount": -amount,
            "merchant": merchant,
            "method": method,
            "date": datetime.now().date()
        }

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
        
        # 알람이 없을 때: 재미있는 말 하기 모드
        if not items:
            random_prompt = """<start_of_turn>user
당신은 사용자의 스마트폰 알림을 모니터링하는 개인 비서 AI입니다.
현재 처리할 알림이 하나도 없습니다.
이럴 때는 짧고 위트있는 한마디를 해주세요. 농담, 명언, 철학적 사색, 랜덤한 사실, 또는 그냥 아무 헛소리나 좋습니다.
한두 문장으로 간결하게 작성해 주세요. 매번 다른 내용으로 창의적으로!

한마디:<end_of_turn>
<start_of_turn>model
"""
            logger.info("No alarms to process. Asking LLM for random wisdom...")
            result = llm_service.generate(random_prompt, max_tokens=128, temperature=0.9)
            logger.info(f"LLM Random Response: {result}")
            return f"🔕 알람 없음 - {result}"
        
        # 알림 목록 구성 (발신자 포함)
        notification_list = []
        for item in items:
            app = item.get('app_name') or item.get('sender') or "알 수 없는 앱"
            # ... (기존 로직 동일) ...
            pkg = item.get('package') or ""
            title = item.get('app_title') or ""
            conv = item.get('conversation') or ""
            text = item.get('text') or ""
            
            # Tasker 변수가 치환 안 된 경우 제외
            if title.startswith('%'): title = ""
            if conv.startswith('%'): conv = ""
            
            context = f"[앱: {app}]"
            if title: context += f" 제목: {title}"
            if conv: context += f" 발신/대화: {conv}"
            
            notification_list.append(f"- {context} 본문: {text}")

        # Gemma-3에 최적화된 프롬프트 구성
        prompt = f"""<start_of_turn>user
당신은 사용자의 스마트폰 알림을 요약해주는 유능하고 위트 있는 개인 비서입니다. 
아래 나열된 알람 목록을 보고 다음 규칙에 따라 요약 리포트를 작성해 주세요.

[요약 규칙]
1. 비슷한 주제끼리 묶어서 간결한 한글 불렛 포인트로 작성하세요.
2. 각 항목에는 앱 이름이나 발신자 정보를 포함하세요.
3. **중요: 단순 광고, 스팸성 프로모션, 또는 가치가 없는 쓰레기 메시지는 요약에서 완전히 제외하세요.** (이미 필터링을 거쳤지만 남아있을 수 있는 찌꺼기를 처리하는 최종 문지기 역할을 수행하세요.)
4. 위트 있지만 정중한 비서의 말투를 유지하세요.

[알림 목록]
{chr(10).join(notification_list)}

요약 결과:<end_of_turn>
<start_of_turn>model
"""
        logger.info(f"LLM Prompt: {prompt}")
        result = llm_service.generate(prompt, max_tokens=512)
        logger.info(f"LLM Response: {result}")
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
당신은 사용자의 가계부 내역을 분석해주는 재무 비서입니다.
아래 나열된 결제 내역들을 보고, 소비 패턴이나 특징을 한 문장으로 짧고 위트 있게 분석해 주세요.
인사말 없이 분석 결과만 출력해 주세요.

[결제 내역]
{chr(10).join(expense_list)}

분석 결과:<end_of_turn>
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
            masked_text = cls.mask_otp(alarm.raw_text)
            
            # 태스크어 변수가 아직 치환되지 않은 경우 필터링
            if "%antext" in masked_text or "%evtprm" in masked_text:
                alarm.status = "discarded"
                alarm.classification = "placeholder"
                continue

            # 1.3 무시할 알림인지 확인 (인증번호 등)
            if cls.should_ignore(masked_text):
                alarm.status = "discarded"
                alarm.classification = "ignored"
                logger.info(f"Alarm ignored (OTP/Security): {masked_text[:30]}...")
                continue

            # 1.5 화이트리스트 체크 (스팸 필터보다 우선)
            if not cls.is_whitelisted(masked_text):
                is_spam_result, classification = cls.is_spam(masked_text, db)
                if is_spam_result:
                    alarm.status = "discarded"
                    alarm.classification = classification
                    continue

                if cls.is_promo_spam(masked_text, db):
                    alarm.status = "discarded"
                    alarm.classification = "promo_rule"
                    continue
            else:
                logger.info(f"Alarm whitelisted: {masked_text[:50]}...")

            if alarm.sender:
                senders.add(alarm.sender)

            # 2. 카드 승인 내역 시도
            card_info = cls.parse_card_approval(masked_text)
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
            # HTML 특수문자 이스케이프 (텔레그램 파싱 에러 방지)
            if to_summarize_alarms:
                summaries.append("\n<b>[주요 알림 요약]</b>\n" + html.escape(llm_summary))
            else:
                # 알람이 없을 때는 헤더 없이 LLM 랜덤 메시지만
                summaries.append(html.escape(llm_summary))

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
