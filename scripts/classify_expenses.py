#!/usr/bin/env python3
"""
Ollama를 사용한 가계부 자동 분류 스크립트

사용법:
    source backend/.venv/bin/activate
    python scripts/classify_expenses.py

요구사항:
    - Ollama가 설치되어 실행 중이어야 함
    - qwen2.5:1b 모델이 설치되어 있어야 함 (ollama pull qwen2.5:1b)
"""

import sqlite3
import json
import time
import sys
from pathlib import Path

# httpx 사용 (backend 가상환경에 있음)
try:
    import httpx
except ImportError:
    print("httpx가 필요합니다. pip install httpx")
    sys.exit(1)

# 설정
DB_PATH = Path(__file__).parent.parent / "backend" / "portfolio.db"
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen3:1.7b"

# 분류 카테고리
CATEGORIES = [
    "식비",
    "교통",
    "쇼핑",
    "생활",
    "문화/여가",
    "의료",
    "통신",
    "저축/투자",
    "기타"
]

def classify_expense(merchant: str, amount: int, method: str, debug: bool = False) -> str:
    """Ollama를 사용해 가맹점명으로 카테고리 분류"""
    
    # Qwen3용 간결한 프롬프트 (thinking 비활성화)
    prompt = f"""/no_think
가계부 분류. 아래 중 하나만 답하세요: 식비, 교통, 쇼핑, 생활, 문화/여가, 의료, 통신, 저축/투자, 기타

가맹점: {merchant}
금액: {amount:,}원

정답:"""

    try:
        response = httpx.post(
            OLLAMA_URL,
            json={
                "model": MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0,
                    "num_predict": 10,
                }
            },
            timeout=30.0
        )
        response.raise_for_status()
        result = response.json()
        answer = result.get("response", "").strip()
        
        if debug:
            print(f"\n  [DEBUG] Raw response: {repr(answer)}")
        
        # 카테고리 정규화 (첫 번째 매칭 반환)
        for cat in CATEGORIES:
            if cat in answer:
                return cat
        
        # 부분 매칭 시도
        answer_lower = answer.lower()
        mappings = {
            "식": "식비", "음식": "식비", "먹": "식비", "밥": "식비", "카페": "식비", "커피": "식비",
            "교통": "교통", "버스": "교통", "지하철": "교통", "택시": "교통", "주유": "교통",
            "쇼핑": "쇼핑", "구매": "쇼핑", "마트": "쇼핑",
            "생활": "생활", "편의점": "생활", "이체": "저축/투자", "증권": "저축/투자",
            "투자": "저축/투자", "적금": "저축/투자",
            "문화": "문화/여가", "여가": "문화/여가", "영화": "문화/여가", "게임": "문화/여가",
            "의료": "의료", "병원": "의료", "약국": "의료",
            "통신": "통신", "휴대폰": "통신", "인터넷": "통신",
        }
        for key, cat in mappings.items():
            if key in answer_lower or key in merchant.lower():
                return cat
        
        # 매칭 안되면 기타
        return "기타"
        
    except Exception as e:
        print(f"  [ERROR] Ollama 호출 실패: {e}")
        return "기타"


def main():
    print(f"=== Ollama 가계부 자동 분류 ===")
    print(f"모델: {MODEL}")
    print(f"DB: {DB_PATH}")
    print()
    
    # Ollama 연결 확인
    try:
        resp = httpx.get("http://localhost:11434/api/tags", timeout=5.0)
        models = [m["name"] for m in resp.json().get("models", [])]
        if not any(MODEL.split(":")[0] in m for m in models):
            print(f"[WARN] 모델 '{MODEL}'이 설치되어 있지 않습니다.")
            print(f"       ollama pull {MODEL} 실행 후 다시 시도하세요.")
            return
        print(f"[OK] Ollama 연결 확인 (모델: {models})")
    except Exception as e:
        print(f"[ERROR] Ollama 연결 실패: {e}")
        print("       ollama serve 실행 중인지 확인하세요.")
        return
    
    # DB 연결
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # 미분류 항목 조회
    cur.execute("""
        SELECT id, date, amount, merchant, method 
        FROM expenses 
        WHERE category = '미분류' 
        ORDER BY date DESC
    """)
    rows = cur.fetchall()
    
    if not rows:
        print("[OK] 분류할 항목이 없습니다.")
        return
    
    print(f"[INFO] 분류할 항목: {len(rows)}건")
    print()
    
    # 분류 시작
    start_time = time.time()
    updated = 0
    
    for i, (expense_id, date, amount, merchant, method) in enumerate(rows):
        print(f"[{i+1}/{len(rows)}] {date} {merchant[:30]:<30} {amount:>10,}원 ... ", end="", flush=True)
        
        category = classify_expense(merchant, amount, method)
        print(f"→ {category}")
        
        # DB 업데이트
        cur.execute(
            "UPDATE expenses SET category = ?, updated_at = datetime('now') WHERE id = ?",
            (category, expense_id)
        )
        updated += 1
        
        # 10건마다 커밋
        if updated % 10 == 0:
            conn.commit()
    
    conn.commit()
    conn.close()
    
    elapsed = time.time() - start_time
    print()
    print(f"=== 완료 ===")
    print(f"분류 완료: {updated}건")
    print(f"소요 시간: {elapsed:.1f}초 ({elapsed/updated:.2f}초/건)")


if __name__ == "__main__":
    main()
