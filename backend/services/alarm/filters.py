# Replace the entire file: backend/services/alarm/filters.py
import re
import logging
import os
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
DATA_DIR = os.path.join(BACKEND_DIR, "data")
SPAM_MODEL_PATH = os.path.join(DATA_DIR, "spam_model.joblib")

_spam_model_instance = None

# 성능 최적화: 민감정보 마스킹 정규식을 모듈 전역에서 컴파일
SENSITIVE_PATTERNS = [
    (re.compile(r"\[(?:인증번호|OTP|확인번호)\]\s*\d{4,6}", re.IGNORECASE), "[인증번호]"),
    (re.compile(r"(?:인증번호|OTP|확인번호)는?\s*\[?\d{4,6}\]?", re.IGNORECASE), "[인증번호]"),
    (re.compile(r"(?<=:)\s*\d{6}(?=\s)", re.IGNORECASE), "[인증번호]"),
    (re.compile(r"\b\d{3,6}-\d{2,6}-\d{3,}(?:\*+|)\b", re.IGNORECASE), "[계좌번호]"),
    (re.compile(r"\b\d{4}-\d{4}-\d{4}-\d{4}\b", re.IGNORECASE), "[카드번호]"),
    (re.compile(r"\b\d{4}-\*{4,}-\d{4}\b", re.IGNORECASE), "[카드번호]"),
    (re.compile(r"\b\d{4,}\*+\d{4,}\b", re.IGNORECASE), "[카드번호/계좌]"),
    (re.compile(r"\b010[- ]?\d{3,4}[- ]?\d{4}\b", re.IGNORECASE), "[전화번호]"),
    (re.compile(r"\b02[- ]?\d{1,4}[- ]?\d{3,4}[- ]?\d{4}\b", re.IGNORECASE), "[전화번호]"),
    (re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", re.IGNORECASE), "[이메일]"),
    (re.compile(r"\b\d{11,}\b", re.IGNORECASE), "[식별번호]"),
]


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
    성능 최적화: 전역 컴파일된 정규식 사용
    """
    masked_text = text
    for compiled_rx, replacement in SENSITIVE_PATTERNS:
        masked_text = compiled_rx.sub(replacement, masked_text)
    return masked_text


def is_spam(text: str, db: Session) -> tuple[bool, str]:
    """
    스팸 필터링 (규칙 -> AI)
    Returns: (is_spam, classification)
    """
    from ...core.models import SpamRule

    rules = (
        db.query(SpamRule)
        .filter(SpamRule.is_enabled.is_(True), SpamRule.rule_type.in_(["contains", "regex"]))
        .all()
    )

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
        r"리뷰.*기록",
        r"리뷰.*남기",
        r"리뷰.*작성",
        r"평가.*기다",
        r"별점.*매겨",
        r"후기.*남겨",
        r"어떠셨나요.*리뷰",
    ]

    # 게임 이벤트 패턴
    game_event_patterns = [
        r"득템",
        r"찬스.*놓치지",
        r"마감.*임박",
        r"\d+연참",  # 버그 수정: \\d+ -> \d+
        r"뽑기.*오픈",
        r"가챠",
        r"아래로.*드래그",
        r"클릭.*받기",
        r"오늘만.*특가",
        r"지금.*안.*사면",
    ]

    all_patterns = review_patterns + game_event_patterns

    for pattern in all_patterns:
        if re.search(pattern, text):
            # 보안: 로그에 민감정보 노출 방지
            logger.info(f"Review/Event spam filtered: {pattern} in {mask_sensitive_info(text)[:50]}...")
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
""",
        }
    ]
    # 성능 개선: 분류용이므로 enable_thinking=False
    result = llm.generate_chat(
        messages, 
        max_tokens=10, 
        temperature=0.1, 
        enable_thinking=False
    ).strip().lower()

    # 결과 파싱 강화: 첫 토큰만 추출
    token = result.split()[0] if result else ""
    if token == "spam":
        # 보안: 로그에 민감정보 노출 방지
        logger.info(f"LLM classified as SPAM: {mask_sensitive_info(text)[:50]}...")
        return True, "llm_spam"

    return False, "llm_ham"


def is_promo_spam(text: str, db: Session) -> bool:
    """
    프로모션 + 긴급성 조합 스팸 필터링 (DB 규칙)
    """
    from ...core.models import SpamRule

    rules = db.query(SpamRule).filter(SpamRule.is_enabled.is_(True), SpamRule.rule_type == "promo_combo").all()

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
        "현재가",
        "시세",
        "주가지수",
        "코스피",
        "코스닥",
        "도착",
        "배송",
        "택배",
        "우체국",
        "AliExpress",
        "내역",
        "안내",
        "공지",
        "리포트",
        # 배달 알림 보호 (중요!)
        "배달이 시작",
        "배달이 완료",
        "배달 되었습니다",
        "배달.*완료",
        "주문.*배달",
        "문앞.*배달",
        "배달.*감사",
        # 금융 거래
        "매매 체결",
        "접근 토큰",
        "체결 안내",
        # 결제 완료 (스팸 필터 우회용)
        "결제가 완료되었어요",
        "결제가 완료되었습니다",
        "결제되었습니다",
        "굿딜 결제가 완료",
        "승인되었습니다",
        # 웹소설/웹툰 업데이트 (사용자 관심사)
        r"\d+화 업로드",
        r"\d+화 업데이트",
        r"\d+화가 업로드",
        "새 연재",
        "연재 업데이트",
        "업로드 완료",
        "문피아",
        "리꼬타",
        "카카오페이지",
        "네이버시리즈",
        # 라이브 방송 시작
        "라이브 시작",
        "방송 시작",
        "라이브가 시작",
    ]

    # 광고가 포함되어 있으면 절대 화이트리스트가 아님
    if any(p in text for p in ["(광고)", "[광고]", "((광고)"]):
        return False

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
