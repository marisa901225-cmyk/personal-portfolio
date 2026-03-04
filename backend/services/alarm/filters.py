# backend/services/alarm/filters.py
import re
import logging
import os
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
DATA_DIR = os.path.join(BACKEND_DIR, "data")
SPAM_MODEL_PATH = os.path.join(DATA_DIR, "spam_model.joblib")

_spam_model_instance = None

# -----------------------------
# Config (env)
# -----------------------------
def _env_bool(key: str, default: bool = True) -> bool:
    v = os.getenv(key)
    if v is None:
        return default
    return v.strip().lower() not in ("0", "false", "no", "off", "n")

SPAM_NB_ENABLED = _env_bool("SPAM_NB_ENABLED", True)
SPAM_NB_THRESHOLD = float(os.getenv("SPAM_NB_THRESHOLD", "0.8"))

# 선거/정치 문자 지역 필터
# 예)
#   ELECTION_REGION_ALLOWLIST="서울,서초,강남"
#   ELECTION_REGION_MODE="strict"  (default) allowlist 없으면 차단
#   ELECTION_REGION_MODE="lenient" 지역이 명시된 경우에만 allowlist 불일치 시 차단
ELECTION_REGION_ALLOWLIST = [
    s.strip() for s in os.getenv("ELECTION_REGION_ALLOWLIST", "").split(",") if s.strip()
]
ELECTION_REGION_MODE = os.getenv("ELECTION_REGION_MODE", "strict").strip().lower()

# -----------------------------
# 성능 최적화: 민감정보 마스킹 정규식을 모듈 전역에서 컴파일
# -----------------------------
SENSITIVE_PATTERNS = [
    (re.compile(r"\[(?:인증번호|OTP|확인번호)\]\s*\d{4,6}", re.IGNORECASE), "[인증번호]"),
    (re.compile(r"(?:인증번호|OTP|확인번호)는?\s*\[?\d{4,6}\]?", re.IGNORECASE), "[인증번호]"),
    (re.compile(r"(?<=:)\s*\d{6}(?=\s)"), "[인증번호]"),
    (re.compile(r"\b\d{3,6}-\d{2,6}-\d{3,}(?:\*+|)\b"), "[계좌번호]"),
    (re.compile(r"\b\d{4}-\d{4}-\d{4}-\d{4}\b"), "[카드번호]"),
    (re.compile(r"\b\d{4}-\*{4,}-\d{4}\b"), "[카드번호]"),
    (re.compile(r"\b\d{4,}\*+\d{4,}\b"), "[카드번호/계좌]"),
    (re.compile(r"\b010[- ]?\d{3,4}[- ]?\d{4}\b"), "[전화번호]"),
    (re.compile(r"\b0\d{1,2}[- ]?\d{3,4}[- ]?\d{4}\b"), "[전화번호]"),
    (re.compile(r"\b1[3568]\d{2}[- ]?\d{4}\b"), "[전화번호]"),
    (re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"), "[이메일]"),
    (re.compile(r"\b\d{11,}\b"), "[식별번호]"),
    # 개인화된 호출 마스킹
    (re.compile(r"칼라의빛(?:님|님께|님을|님이)?"), "[사용자]"),
    (re.compile(r"[가-힣]{2,4}님(?:께|을|이)?"), "[사용자]"),
]

# -----------------------------
# 선거/정치 문자 필터 (지방선거 시즌 대응)
# -----------------------------
# 강한 신호: 후보/기호/선거운동/공직선거법/수신거부 등
_ELECTION_STRONG_RX = re.compile(
    r"(?:공직선거법|선거관리위원회|선거운동정보|지방선거|대통령선거|국회의원선거|보궐선거|재선거|사전투표|선거일|기호\s*\d+|후보(?:자)?|지지\s*부탁|한\s*표|투표\s*부탁|수신거부)",
    re.IGNORECASE,
)

# “경주시장 000입니다 …” 같은 케이스를 잡는 핵심 패턴 (이번 케이스!)
# 지역(경주) + 직책(시장/군수/구청장/도지사/교육감) + (이름/기호 등) + 입니다
_LOCAL_OFFICE_INTRO_RX = re.compile(
    r"(?:^|\s)"
    r"(?P<region>[가-힣]{2,10})"
    r"(?:특별시|광역시|특별자치시|특별자치도|도|시|군|구)?\s*"
    r"(?P<office>시장|군수|구청장|도지사|교육감)\s*"
    r"(?P<name>[가-힣]{2,4}|\d{2,4}|[^\s]{2,10})?\s*"
    r"(?:입니다|인사드립니다)\b",
    re.IGNORECASE,
)

# 지역+직책이 언급되는 형태(allowlist 비교에 사용)
_REGION_OFFICE_MENTION_RX = re.compile(
    r"(?P<region>[가-힣]{2,10})"
    r"(?:특별시|광역시|특별자치시|특별자치도|도|시|군|구)?\s*"
    r"(?:시장|군수|구청장|도지사|교육감|시의원|구의원|도의원|국회의원)",
    re.IGNORECASE,
)

# 명절/축하/인사 문구 (약한 신호, 단독으로는 차단하지 않음)
_GREETING_RX = re.compile(
    r"(?:정월대보름|대보름|설(?:날)?|추석|한가위|새해|연휴|명절|기원(?:합니다|드립니다)|바랍니다|희망(?:합니다|드립니다)|건강과\s*평안|가정에|행복|따뜻한\s*정|복된\s*날)",
    re.IGNORECASE,
)

# 재난/긴급 안내는 절대 정치 스팸으로 잡지 않기 위한 안전장치
_EMERGENCY_SAFE_RX = re.compile(
    r"(?:재난|긴급|대피|경보|위험|지진|호우|태풍|산불|폭염|한파|감염병|확진|정전|단수|통제|도로\s*통제)",
    re.IGNORECASE,
)


def _contains_any(text: str, keywords: list[str]) -> bool:
    t = (text or "").lower()
    return any(k and (k.lower() in t) for k in keywords)


def mask_sensitive_info(text: str) -> str:
    """
    인증번호, 계좌번호, 전화번호, 이메일 등 민감 정보를 마스킹한다.
    """
    masked_text = text
    for compiled_rx, replacement in SENSITIVE_PATTERNS:
        masked_text = compiled_rx.sub(replacement, masked_text)
    return masked_text


def _is_political_like(text: str) -> bool:
    """
    선거/정치성 메시지인지(스팸 처리 후보군인지) 판단.
    - 강한 신호(공직선거법/후보/기호/수신거부 등) OR
    - 지역 직책 + 자기소개(“경주시장 000입니다”) OR
    - 지역 직책 언급 + 인사/명절 문구(낚시용 덕담)
    """
    t = text or ""
    if not t:
        return False

    # 안전장치: 재난/긴급류는 정치문자로 오인 금지
    if _EMERGENCY_SAFE_RX.search(t):
        return False

    if _ELECTION_STRONG_RX.search(t):
        return True

    if _LOCAL_OFFICE_INTRO_RX.search(t):
        return True

    # “경주시장님이…(인사)” 같은 변형을 잡기 위한 약한 조합
    if _REGION_OFFICE_MENTION_RX.search(t) and _GREETING_RX.search(t):
        return True

    return False


def _region_allowed(text: str) -> bool:
    """
    allowlist가 설정되어 있을 때, 해당 지역(키워드)이 텍스트에 포함되면 허용.
    """
    if not ELECTION_REGION_ALLOWLIST:
        return False
    return _contains_any(text, ELECTION_REGION_ALLOWLIST)


def is_election_spam(text: str) -> bool:
    """
    선거/정치성 문자 스팸 처리.
    - allowlist 미설정: 정치성 문자는 전부 스팸 처리(깔끔하게 제거)
    - allowlist 설정:
        * strict: allowlist 키워드 없으면 스팸
        * lenient: 지역이 명시된 경우에만 allowlist 불일치 시 스팸
    """
    if not _is_political_like(text):
        return False

    # allowlist가 없으면 정치성 문자 전체 차단
    if not ELECTION_REGION_ALLOWLIST:
        return True

    # allowlist 포함되면 통과
    if _region_allowed(text):
        return False

    mode = ELECTION_REGION_MODE
    if mode == "lenient":
        # 지역이 명시된 정치문자만 타지역으로 보고 차단
        return bool(_REGION_OFFICE_MENTION_RX.search(text or ""))

    # strict(default): allowlist 미포함이면 차단
    return True


def get_spam_model():
    """
    스팸 분류용 NB 모델을 싱글톤으로 로드한다.
    """
    global _spam_model_instance

    if not SPAM_NB_ENABLED:
        return None

    if _spam_model_instance is None:
        if os.path.exists(SPAM_MODEL_PATH):
            try:
                import joblib
                logger.info(f"Loading Spam AI model from {SPAM_MODEL_PATH}...")
                _spam_model_instance = joblib.load(SPAM_MODEL_PATH)
            except Exception as e:
                logger.error(f"Failed to load Spam AI model: {e}")
    return _spam_model_instance


def is_spam(text: str, db: Session) -> tuple[bool, str]:
    """
    스팸 필터링 (정치/선거 규칙 -> DB 규칙 -> NB AI)
    Returns: (is_spam, classification)
    """
    from ...core.models import SpamRule

    # 0단계: 정치/선거 문자 우선 차단 (지역 allowlist 반영)
    if is_election_spam(text):
        logger.info(f"Election/Political spam filtered: {mask_sensitive_info(text)[:80]}...")
        return True, "rule_political"

    # 1단계: DB 규칙
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
            try:
                if re.search(rule.pattern, text):
                    logger.info(f"Spam filtered by DB rule (regex): {rule.pattern}")
                    return True, "rule"
            except re.error as e:
                logger.error(f"Invalid regex in DB rule: {rule.pattern} ({e})")

    # 2단계: NB 모델 (옵션)
    model = get_spam_model()
    if model:
        try:
            prediction = model.predict([text])[0]
            if prediction == 1:
                probs = model.predict_proba([text])[0]
                spam_prob = float(probs[1])
                if spam_prob >= SPAM_NB_THRESHOLD:
                    logger.info(f"Spam filtered by NB model (confidence: {spam_prob:.2%})")
                    return True, "nb"
        except Exception as e:
            logger.error(f"NB classification failed: {e}")

    return False, ""


def is_review_spam(text: str) -> bool:
    """
    리뷰 요청 및 게임 이벤트 스팸 필터링 (규칙 기반)
    """
    review_patterns = [
        r"리뷰.*기록",
        r"리뷰.*남기",
        r"리뷰.*작성",
        r"평가.*기다",
        r"별점.*매겨",
        r"후기.*남겨",
        r"어떠셨나요.*리뷰",
    ]

    game_event_patterns = [
        r"득템",
        r"찬스.*놓치지",
        r"마감.*임박",
        r"\d+연참",
        r"뽑기.*오픈",
        r"가챠",
        r"아래로.*드래그",
        r"클릭.*받기",
        r"오늘만.*특가",
        r"지금.*안.*사면",
        r"포인트.*뽑기",
        r"포인트.*선물",
        r"추억.*알아보세요",
        r"오늘의.*포인트",
    ]

    for pattern in (review_patterns + game_event_patterns):
        if re.search(pattern, text or ""):
            logger.info(f"Review/Event spam filtered: {pattern} in {mask_sensitive_info(text)[:50]}...")
            return True

    return False


def is_spam_llm(text: str, model: str | None = None, **llm_kwargs) -> tuple[bool, str]:
    """
    3단계: LLM 기반 스팸 판독(필요할 때만 호출되는 용도)
    Returns: (is_spam, confidence_label)
    """
    from ..llm_service import LLMService

    llm = LLMService.get_instance()
    if not llm.is_loaded():
        return False, ""

    messages = [
        {
            "role": "user",
            "content": f"""
당신은 고성능 뉴스/알림 필터링 전문가입니다. 다음 메시지가 사용자가 즉시 확인해야 할 '중요 정보'인지, 아니면 차단해야 할 '스팸/광고'인지 판별하세요.

[판별 기준]
1. SPAM (광고/유도/이벤트):
   - 마케팅, 할인 쿠폰, 포인트 적립, 이벤트 참여 유도
   - "지금 확인하세요", "혜택이 기다려요", "소멸 예정" 등의 촉구성 문구
   - 주식/코인 리딩방 유도, 대출 권유
   - 게임 내 이벤트(연참, 뽑기, 득템 등)나 단순 출석 알림
   - 서비스 이용 후기나 별점 작성 요청
   - 선거/정치 홍보성 인사/캠페인 문자

2. HAM (정상/중요 알림):
   - 실제 결제 승인(카드/페이), 은행 이체 알림, 입출금 정보 (매우 중요)
   - 택배 배송 상태(배송 시작/완료), 택시/배달 앱 도착 정보
   - 주식 체결 안내, 증권사 리포트 알림 
   - 웹툰/웹소설 신작 및 연재 업데이트 알림
   - 라이브 방송 시작, 본인 인증 번호, 보안 로그인 안내

[출력 형식]
단 한 단어 "spam" 또는 "ham"만 출력하세요.
금융 거래나 배송 알람은 절대 스팸이 아닙니다.
판단이 모호하다면 "ham"을 선택하세요.

메시지 내용:
{text}
""",
        }
    ]

    result = llm.generate_chat(
        messages,
        max_tokens=10,
        temperature=0.1,
        enable_thinking=False,
        model=model,
        **llm_kwargs,
    )

    out = (result or "").strip().lower()
    first = out.split()[0] if out.split() else ""

    logger.info(f"LLM spam classifier raw result: {out}")

    if first == "spam":
        logger.info(f"LLM classified as SPAM: {mask_sensitive_info(text)[:50]}...")
        return True, "llm_spam"

    return False, "llm_ham"


def is_promo_spam(text: str, db: Session) -> bool:
    """
    프로모션 + 긴급성 조합 스팸 필터링 (DB 규칙)
    """
    from ...core.models import SpamRule

    rules = (
        db.query(SpamRule)
        .filter(SpamRule.is_enabled.is_(True), SpamRule.rule_type == "promo_combo")
        .all()
    )

    t = (text or "").replace("\n", " ")

    for rule in rules:
        parts = (rule.pattern or "").split("|")
        if len(parts) != 2:
            continue

        promo_list = [p.strip() for p in parts[0].split(",") if p.strip()]
        urgency_list = [u.strip() for u in parts[1].split(",") if u.strip()]

        if any(p in t for p in promo_list) and any(u in t for u in urgency_list):
            logger.info(f"Promo spam filtered by DB rule: {rule.note or rule.pattern}")
            return True

    return False


def is_whitelisted(text: str) -> bool:
    """
    중요 알림 키워드 화이트리스트 (스팸 필터링 방지)
    """
    t = text or ""

    # 정치/선거 문자는 화이트리스트로 통과시키지 않음
    if is_election_spam(t):
        return False

    whitelist_keywords = [
        # 시세/증권
        r"현재가", r"시세", r"주가지수", r"코스피", r"코스닥",
        r"매매\s*체결", r"체결\s*안내", r"리포트",
        # 배송/도착
        r"도착", r"배송", r"택배", r"우체국", r"AliExpress",
        r"배송\s*안내",
        # 배달 알림
        r"배달이\s*시작", r"배달이\s*완료", r"배달\s*되었", r"문앞.*배달", r"주문.*배달",
        # 결제/승인
        r"결제가\s*완료", r"결제\s*완료", r"결제\s*내역", r"승인되었", r"승인\s*완료",
        # 인증/보안
        r"접근\s*토큰", r"인증번호", r"\bOTP\b", r"보안\s*로그인",
        # 웹소설/웹툰
        r"\d+화\s*(?:업로드|업데이트)", r"새\s*연재", r"연재\s*업데이트", r"업로드\s*완료",
        # 라이브/방송
        r"라이브\s*시작", r"방송\s*시작", r"라이브가\s*시작",
    ]

    promo_keywords = [
        "(광고)", "[광고]", "((광고)",
        "무료 이용권",
        "캐시 뽑기", "무료 캐시",
        "포인트 뽑기", "포인트뽑기",
        "추억을 알아보세요", "오늘의 포인트",
        "이벤트", "당첨자", "당첨 안내", "응모",
        "럭키박스", "득템", "사전예약", "쿠폰",
    ]
    if any(p in t for p in promo_keywords):
        return False

    for kw in whitelist_keywords:
        if re.search(kw, t):
            return True

    return False


def should_ignore(text: str) -> bool:
    """
    텔레그램으로 전달할 필요가 없는 메시지인지 확인한다.
    """
    ignore_keywords = [
        "인증번호", "OTP", "인증 요청", "비밀번호 확인",
        "OneDrive", "Google Photos", "보안 알림", "새 로그인",
    ]
    t = (text or "")
    if any(kw.lower() in t.lower() for kw in ignore_keywords):
        return True
    return False