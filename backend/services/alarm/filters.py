import re
import logging
import os
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

SPAM_MODEL_PATH = os.path.join(os.path.dirname(__file__), "../../data/spam_model.joblib")
_spam_model_instance = None

def get_spam_model():
    """
    스팸 분류용 NB 모델을 싱글톤으로 로드한다.
    """
    global _spam_model_instance
    if _spam_model_instance is None:
        if os.path.exists(SPAM_MODEL_PATH):
            try:
                import joblib
                logger.info(f"Loading Spam AI model from {SPAM_MODEL_PATH}...")
                _spam_model_instance = joblib.load(SPAM_MODEL_PATH)
            except Exception as e:
                logger.error(f"Failed to load Spam AI model: {e}")
    return _spam_model_instance

def mask_otp(text: str) -> str:
    """
    인증번호/OTP 패턴을 마스킹한다.
    """
    otp_patterns = [
        r'\[(?:인증번호|OTP|확인번호)\]\s*\d{4,6}',
        r'(?:인증번호|OTP|확인번호)는?\s*\[?\d{4,6}\]?',
        r'(?<=:)\s*\d{6}(?=\s)', # SMS 인증번호 특화
    ]
    masked_text = text
    for pattern in otp_patterns:
        masked_text = re.sub(pattern, "[인증번호 마스킹]", masked_text, flags=re.IGNORECASE)
    return masked_text

def is_spam(text: str, db: Session) -> tuple[bool, str]:
    """
    스팸 필터링 (규칙 -> AI)
    Returns: (is_spam, classification)
    """
    from ...core.models import SpamRule
    
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
    model = get_spam_model()
    if model:
        try:
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

def is_promo_spam(text: str, db: Session) -> bool:
    """
    프로모션 + 긴급성 조합 스팸 필터링 (DB 규칙)
    """
    from ...core.models import SpamRule
    
    rules = db.query(SpamRule).filter(
        SpamRule.is_enabled == True,
        SpamRule.rule_type == "promo_combo"
    ).all()
    
    t = text.replace("\n", " ")
    
    for rule in rules:
        parts = rule.pattern.split("|")
        if len(parts) != 2:
            continue
        promo_list = [p.strip() for p in parts[0].split(",")]
        urgency_list = [u.strip() for u in parts[1].split(",")]
        
        if any(p in t for p in promo_list) and any(u in t for u in urgency_list):
            logger.info(f"Promo spam filtered by DB rule: {rule.note or rule.pattern}")
            return True
    
    return False

def is_whitelisted(text: str) -> bool:
    """
    중요 알림 키워드 화이트리스트 (스팸 필터링 방지)
    """
    whitelist_keywords = [
        "현재가", "시세", "주가지수", "코스피", "코스닥", 
        "도착", "배송", "택배", "우체국", "AliExpress", 
        "내역", "안내", "공지", "리포트"
    ]
    
    if "(광고)" in text:
        return False
        
    if any(kw in text for kw in whitelist_keywords):
        return True
        
    return False

def should_ignore(text: str) -> bool:
    """
    텔레그램으로 전달할 필요가 없는 메시지인지 확인한다.
    """
    ignore_keywords = ["인증번호", "OTP", "인증 요청", "비밀번호 확인"]
    if any(kw in text for kw in ignore_keywords):
        return True
    return False
