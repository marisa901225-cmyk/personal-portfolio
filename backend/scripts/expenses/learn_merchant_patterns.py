#!/usr/bin/env python3
"""
기존 DB 데이터를 학습해서 가맹점 → 카테고리 매핑 규칙을 자동으로 생성
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]


def analyze_existing_data(db_path: str) -> dict:
    """
    DB에서 기존 분류 패턴 분석
    
    Returns:
        {
            'exact_match': {가맹점명: 카테고리},
            'patterns': {카테고리: [키워드 리스트]},
            'stats': {카테고리: 건수}
        }
    """
    conn = sqlite3.connect(db_path)
    
    # 가맹점별 카테고리 빈도
    query = """
    SELECT merchant, category, COUNT(*) as count
    FROM expenses
    WHERE amount < 0
    GROUP BY merchant, category
    ORDER BY count DESC
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    
    # 1. Exact match 매핑 (가맹점명이 정확히 일치하는 경우)
    exact_match = {}
    merchant_categories = defaultdict(list)
    
    for _, row in df.iterrows():
        merchant = row['merchant']
        category = row['category']
        count = row['count']
        
        merchant_categories[merchant].append((category, count))
    
    # 각 가맹점의 가장 빈번한 카테고리를 선택
    for merchant, categories in merchant_categories.items():
        # 빈도순 정렬
        categories.sort(key=lambda x: x[1], reverse=True)
        most_common_category = categories[0][0]
        exact_match[merchant] = most_common_category
    
    # 2. 패턴 추출 (카테고리별 공통 키워드)
    patterns = defaultdict(set)
    
    for merchant, category in exact_match.items():
        # 가맹점명을 단어로 분리
        merchant_clean = merchant.strip()
        
        # 한글 2글자 이상 키워드 추출
        if len(merchant_clean) >= 2:
            # 전체 가맹점명
            patterns[category].add(merchant_clean)
            
            # 괄호 제거한 버전
            merchant_no_paren = merchant_clean.split('(')[0].split('（')[0].strip()
            if merchant_no_paren and len(merchant_no_paren) >= 2:
                patterns[category].add(merchant_no_paren)
    
    # 3. 통계
    stats = df.groupby('category')['count'].sum().to_dict()
    
    return {
        'exact_match': exact_match,
        'patterns': {cat: sorted(list(keywords)) for cat, keywords in patterns.items()},
        'stats': stats
    }


def generate_enhanced_classifier(analysis: dict, output_path: str):
    """
    분석 결과를 바탕으로 개선된 분류기 코드 생성
    """
    exact_match = analysis['exact_match']
    patterns = analysis['patterns']
    stats = analysis['stats']
    
    # Python 코드 생성
    code = '''"""
자동 생성된 가맹점 분류 규칙
DB 학습 데이터 기반으로 생성됨
"""

# 정확 매칭 (가맹점명 완전 일치)
EXACT_MERCHANT_MAPPING = {
'''
    
    # Exact match 추가 (상위 100개만)
    sorted_merchants = sorted(exact_match.items(), key=lambda x: len(x[0]), reverse=True)[:100]
    for merchant, category in sorted_merchants:
        merchant_escaped = merchant.replace('"', '\\"').replace("'", "\\'")
        code += f'    "{merchant_escaped}": "{category}",\n'
    
    code += '''}\n\n# 카테고리별 키워드 패턴
CATEGORY_KEYWORDS = {\n'''
    
    # 패턴 추가
    for category in sorted(patterns.keys()):
        keywords = patterns[category][:50]  # 상위 50개만
        code += f'    "{category}": [\n'
        for keyword in keywords:
            keyword_escaped = keyword.replace('"', '\\"').replace("'", "\\'")
            code += f'        "{keyword_escaped}",\n'
        code += '    ],\n'
    
    code += '''}\n\n# 통계 정보
CATEGORY_STATS = {\n'''
    
    for category, count in sorted(stats.items(), key=lambda x: x[1], reverse=True):
        code += f'    "{category}": {count},\n'
    
    code += '''}\n\n
def classify_with_learned_patterns(merchant: str) -> str | None:
    """
    학습된 패턴으로 가맹점 분류
    
    Returns:
        카테고리명 또는 None (분류 불가)
    """
    # 1. 정확 매칭
    if merchant in EXACT_MERCHANT_MAPPING:
        return EXACT_MERCHANT_MAPPING[merchant]
    
    # 2. 패턴 매칭
    for category, keywords in CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            if keyword in merchant:
                return category
    
    return None
'''
    
    # 파일 저장
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(code)
    
    return output_path


def main():
    db_path = str(REPO_ROOT / "backend" / "storage" / "db" / "portfolio.db")
    output_path = str(REPO_ROOT / "backend" / "scripts" / "maintenance" / "learned_merchant_rules.py")
    
    print("🤖 DB 데이터 학습 시작...\n")
    
    # 분석
    print("📊 Step 1: 기존 분류 패턴 분석")
    analysis = analyze_existing_data(db_path)
    
    print(f"   ✅ {len(analysis['exact_match'])}개 가맹점 매핑")
    print(f"   ✅ {sum(len(v) for v in analysis['patterns'].values())}개 키워드 패턴")
    print(f"   ✅ {len(analysis['stats'])}개 카테고리")
    
    # 카테고리 통계
    print("\n📈 카테고리별 거래 통계:")
    for category, count in sorted(analysis['stats'].items(), key=lambda x: x[1], reverse=True):
        print(f"   {category:<12} {count:>6}건")
    
    # 코드 생성
    print(f"\n🔧 Step 2: 분류 규칙 코드 생성")
    output = generate_enhanced_classifier(analysis, output_path)
    print(f"   ✅ {output} 생성 완료")
    
    # JSON도 저장
    json_path = output_path.replace('.py', '.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)
    print(f"   ✅ {json_path} 저장 완료")
    
    # 샘플 테스트
    print(f"\n🧪 Step 3: 학습된 규칙 테스트")
    
    # 동적 임포트
    sys.path.insert(0, str(Path(output_path).parent))
    from learned_merchant_rules import classify_with_learned_patterns
    
    test_merchants = [
        "스타벅스 강남점",
        "홈플러스신내점",
        "GS25중랑갤러리",
        "모바일이즐 후불무승인_지하철",
        "넷플릭스",
        "쿠팡",
        "새로운가게이름"
    ]
    
    print("\n   테스트 케이스:")
    for merchant in test_merchants:
        category = classify_with_learned_patterns(merchant)
        emoji = "✅" if category else "❌"
        print(f"   {emoji} {merchant:<30} → {category or '분류 안됨'}")
    
    print(f"\n✅ 학습 완료!")
    print("\n💡 이제 scripts/expenses/import_expenses.py에서 이 규칙을 우선순위로 사용할 수 있습니다.")


if __name__ == "__main__":
    main()
