"""카테고리 자동 분류 로직"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
KEYWORD_CONFIG_PATH = REPO_ROOT / "backend" / "expense_category_keywords.json"


def load_category_keywords() -> dict[str, list[str]]:
    """카테고리별 키워드 로드"""
    try:
        with KEYWORD_CONFIG_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {key: value for key, value in data.items() if isinstance(value, list)}


CATEGORY_KEYWORDS = load_category_keywords()


def classify_category(merchant: str, amount: float, learned_patterns: dict[str, str] = None, model = None) -> str:
    """
    상점명과 금액을 기반으로 카테고리 자동 분류
    
    Args:
        merchant: 가맹점명
        amount: 금액 (양수: 수입, 음수: 지출)
        learned_patterns: DB에서 가져온 가맹점-카테고리 매핑 사전
        model: 학습된 AI 모델 (optional)
    
    Returns:
        카테고리명 (식비, 교통, 쇼핑, 통신, 구독, 이체, 기타)
    """
    # 0. DB에서 학습된 패턴 우선 사용 (가장 정확)
    if learned_patterns and merchant in learned_patterns:
        return learned_patterns[merchant]

    # 1. 학습된 모델(AI) 사용
    if model and amount < 0:
        try:
            return model.predict([merchant])[0]
        except Exception:
            pass

    # 2. 학습된 패턴(파일 기반) 사용
    try:
        from backend.learned_merchant_rules import classify_with_learned_patterns
        learned_category = classify_with_learned_patterns(merchant)
        if learned_category:
            return learned_category
    except (ImportError, ModuleNotFoundError):
        pass
    
    merchant_lower = merchant.lower()
    
    # 수입 관련
    if amount >= 0:
        if any(x in merchant_lower for x in ['급여', 'salary', '월급', '입금']):
            return '급여'
        if any(x in merchant_lower for x in ['캐시백', '포인트', '이자', '환급']):
            return '기타수입'
        return '기타수입'
    
    # 지출 카테고리 분류
    merchant_kr = merchant
    
    # 1. 식비 (마트, 편의점, 음식점, 카페)
    if any(kw in merchant_kr for kw in CATEGORY_KEYWORDS.get('식비', [])):
        return '식비'
    
    # 2. 교통
    if any(kw in merchant_kr for kw in CATEGORY_KEYWORDS.get('교통', [])):
        return '교통'
    
    # 3. 통신 (아파트 관리비 포함)
    if any(kw in merchant_kr for kw in CATEGORY_KEYWORDS.get('통신', [])):
        return '통신'
    
    # 4. 구독
    if any(kw in merchant_kr for kw in CATEGORY_KEYWORDS.get('구독', [])):
        return '구독'
    
    # 5. 쇼핑
    if any(kw in merchant_kr for kw in CATEGORY_KEYWORDS.get('쇼핑', [])):
        return '쇼핑'
    
    # 6. 투자 (증권사 입금, ISA 등 - 대형 이체만)
    if '네이버파이낸셜' in merchant_kr and amount <= -500000:
        return '투자'
    
    if any(kw in merchant_kr for kw in [
        '증권', '한국투자', '삼성증권', '키움증권', '미래에셋',
        'NH투자증권', '신한투자증권', 'KB증권', 'ISA'
    ]) and amount <= -100000:
        return '투자'
    
    # 7. 이체 (일반 계좌이체, 소액 증권 이체 등)
    if any(kw in merchant_kr for kw in CATEGORY_KEYWORDS.get('이체', [])) and not any(x in merchant_kr for x in ['카드', '할부', '결제']):
        return '이체'
    
    # 개인 이름처럼 보이는 경우 (한글 2-4자, 숫자/영문 없음)
    merchant_clean = merchant_kr.replace(' ', '').replace('　', '')
    if (len(merchant_clean) >= 2 and len(merchant_clean) <= 4 and 
        all('\uac00' <= c <= '\ud7a3' for c in merchant_clean)):
        return '이체'
    
    # 8. 기타 (분류 불가)
    return '기타'
