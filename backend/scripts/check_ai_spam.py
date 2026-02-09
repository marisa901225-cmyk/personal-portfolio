import sys
import os
import logging
import asyncio

# 로깅 설정
logging.basicConfig(level=logging.INFO)

# 경로 추가
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.services.alarm.filters import is_spam_llm

def test_samples():
    samples = [
        ("내일이면 소멸되는 포인트 5,000점이 있어요! 지금 바로 확인하세요.", True),
        ("[대한통운] 고객님의 소중한 상품이 오늘 배송 완료되었습니다.", False),
        ("KB카드 승인: 12,500원 일시불 결제 완료.", False),
        ("이번주 한정 특가! 최신형 건조기 반값 할인 찬스!", True),
        ("오늘의 증시 리포트: 반도체 섹터 강세 지속 전망", False),
        ("이벤트 당첨을 축하드려요! 아래 링크를 클릭해서 선물을 받으세요.", True)
    ]
    
    print("--- 8B AI Spam Filter Test ---")
    for text, expected in samples:
        try:
            is_sp, label = is_spam_llm(text)
            status = "PASS" if is_sp == expected else "FAIL"
            print(f"[{status}] Result: {is_sp} (Label: {label}) | Expected: {expected} | Text: {text[:40]}...")
        except Exception as e:
            print(f"[ERROR] {e} | Text: {text[:40]}...")

if __name__ == "__main__":
    test_samples()
