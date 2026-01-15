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

def mask_sensitive_info(text: str) -> str:
    """
    인증번호, 계좌번호, 전화번호, 이메일 등 민감 정보를 마스킹한다.
    """
    patterns = [
        # 1. OTP/인증번호
        (r'\[(?:인증번호|OTP|확인번호)\]\s*\d{4,6}', "[인증번호]"),
        (r'(?:인증번호|OTP|확인번호)는?\s*\[?\d{4,6}\]?', "[인증번호]"),
        (r'(?<=:)\s*\d{6}(?=\s)', "[인증번호]"),
        
        # 2. 계좌번호 (3~6자리 - 2~6자리 - 3~자리)
        # 예: 1002-556-011***, 68694229-01
        (r'\b\d{3,6}-\d{2,6}-\d{3,}(?:\*+|)\b', "[계좌번호]"),
        
        # 3. 카드번호 (4자리-4자리-4자리-4자리 또는 마스킹 포함)
        (r'\b\d{4}-\d{4}-\d{4}-\d{4}\b', "[카드번호]"),
        (r'\b\d{4}-\*{4,}-\d{4}\b', "[카드번호]"),
        (r'\b\d{4,}\*+\d{4,}\b', "[카드번호/계좌]"),
        
        # 4. 전화번호
        (r'\b010[- ]?\d{3,4}[- ]?\d{4}\b', "[전화번호]"),
        (r'\b02[- ]?\d{1,4}[- ]?\d{3,4}[- ]?\d{4}\b', "[전화번호]"),
        
        # 5. 이메일
        (r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', "[이메일]"),
        
        # 6. 기타 긴 식별 번호 (11자리 이상 연속 숫자, 고객번호/송장번호 등)
        (r'\b\d{11,}\b', "[식별번호]"),
    ]
    
    masked_text = text
    for pattern, replacement in patterns:
        masked_text = re.sub(pattern, replacement, masked_text, flags=re.IGNORECASE)
    
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

def is_review_spam(text: str) -> bool:
    """
    리뷰 요청 및 게임 이벤트 스팸 필터링 (규칙 기반)
    """
    # 리뷰 요청 패턴
    review_patterns = [
        r'리뷰.*기록', r'리뷰.*남기', r'리뷰.*작성',
        r'평가.*기다', r'별점.*매겨', r'후기.*남겨',
        r'어떠셨나요.*리뷰'
    ]
    
    # 게임 이벤트 패턴
    game_event_patterns = [
        r'득템', r'찬스.*놓치지', r'마감.*임박',
        r'\d+연참', r'뽑기.*오픈', r'가챠',
        r'아래로.*드래그', r'클릭.*받기',
        r'오늘만.*특가', r'지금.*안.*사면'
    ]
    
    import re
    all_patterns = review_patterns + game_event_patterns
    
    for pattern in all_patterns:
        if re.search(pattern, text):
            logger.info(f"Review/Event spam filtered: {pattern} in {text[:50]}...")
            return True
    
    return False

def is_spam_llm(text: str) -> tuple[bool, str]:
    """
    3단계: LLM을 사용하여 스팸 여부를 판단한다. (실험적 기능)
    Returns: (is_spam, confidence_label)
    """
    from ..llm_service import LLMService
    llm = LLMService.get_instance()
    
    if not llm.is_loaded():
        return False, ""

    # 모델 템플릿에 의존하지 않고 generate_chat 사용
    messages = [
        {
            "role": "user",
            "content": f"""
스팸인지 판단해줘. "spam" 또는 "ham" 중 하나만 출력해.

[스팸 기준]
- 광고, 프로모션, 할인, 이벤트, 쿠폰
- 포인트/캐시 적립, 리워드
- 리뷰 작성 요청, 평가 유도
- 게임 이벤트 (연참, 뽑기, 득템)
- 대출, 금융상품 권유

[정상(ham) 기준]  
- 결제 승인, 배송 안내, 택시 도착
- 개인 메시지 (카카오톡, Discord 등)
- 웹툰/웹소설 업데이트, 라이브 방송 시작
- 주식 체결, 금융 거래 알림
- 중요 공지, API 토큰 발급

확실하지 않으면 "ham" 출력.

내용:
{text}
"""
        }
    ]
    result = llm.generate_chat(messages, max_tokens=10, temperature=0.1, enable_thinking=True).lower()
    
    if "spam" in result:
        logger.info(f"LLM classified as SPAM: {text[:50]}...")
        return True, "llm_spam"
    
    return False, "llm_ham"

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
        "내역", "안내", "공지", "리포트",
        # 배달 알림 보호 (중요!)
        "배달이 시작", "배달이 완료", "배달 되었습니다", "배달.*완료",
        "주문.*배달", "문앞.*배달", "배달.*감사",
        # 금융 거래
        "매매 체결", "접근 토큰", "체결 안내",
        # 결제 완료 (스팸 필터 우회용)
        "결제가 완료되었어요", "결제가 완료되었습니다", "결제되었습니다",
        "굿딜 결제가 완료", "승인되었습니다",
        # 웹소설/웹툰 업데이트 (사용자 관심사)
        r"\d+화 업로드", r"\d+화 업데이트", r"\d+화가 업로드",
        "새 연재", "연재 업데이트", "업로드 완료",
        "문피아", "리꼬타", "카카오페이지", "네이버시리즈",
        # 라이브 방송 시작
        "라이브 시작", "방송 시작", "라이브가 시작"
    ]
    
    # 광고가 포함되어 있으면 절대 화이트리스트가 아님
    if any(p in text for p in ["(광고)", "[광고]", "((광고)"]):
        return False
    
    # 정규식 패턴도 지원
    import re
    for kw in whitelist_keywords:
        if re.search(kw, text):
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
