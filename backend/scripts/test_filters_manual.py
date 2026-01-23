import sys
import os
import logging

# Add backend to sys.path
# The script is in backend/scripts/, so we need to go up 2 levels to get to the project root
# But the code expects 'backend.xxx' so we should append the directory containing 'backend' folder.
# Project root is /home/dlckdgn/personal-portfolio/
sys.path.append("/app") # In docker, /app contains 'backend' folder

from backend.services.alarm.filters import (
    mask_sensitive_info, 
    is_spam, 
    is_review_spam, 
    is_spam_llm, 
    is_promo_spam, 
    is_whitelisted, 
    should_ignore
)
from backend.core.db import SessionLocal

# Setup logging to stdout
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def test_filters():
    db = SessionLocal()
    try:
        test_cases = [
            {
                "name": "Normal Delivery (HAM)",
                "text": "현대택배 배송이 시작되었습니다. 송장번호: 123-456-7890",
                "expected_spam": False
            },
            {
                "name": "OTP (Ignore)",
                "text": "[인증번호] 123456 입니다. 유효시간 3분.",
                "expected_ignore": True
            },
            {
                "name": "Bank Outflow (HAM)",
                "text": "[신한카드] 승인 12,000원 01/23 11:15 스타벅스",
                "expected_spam": False
            },
            {
                "name": "Game Event (SPAM)",
                "text": "[득템찬스] 지금 접속하면 전설 무기 지급! 마감 임박!",
                "expected_spam": True
            },
            {
                "name": "Review Request (SPAM)",
                "text": "어떠셨나요? 별점과 후기를 남겨주시면 큰 힘이 됩니다!",
                "expected_spam": True
            },
            {
                "name": "Stock Info (HAM-Whitelist)",
                "text": "[주가지수] 코스피 2,500 돌파! 현재가 확인하세요.",
                "expected_spam": False
            },
            {
                "name": "Ad with Whitelist keyword (SPAM)",
                "text": "[광고] 쿠팡 선물 도착! 50% 할인 쿠폰 받기",
                "expected_spam": True
            }
        ]

        print("\n" + "="*50)
        print("🚩 STARTING ALARM FILTER MANUAL TEST")
        print("="*50 + "\n")

        for case in test_cases:
            text = case["text"]
            name = case["name"]
            
            print(f"👉 CASE: {name}")
            print(f"   Original: {text}")
            print(f"   Masked  : {mask_sensitive_info(text)}")
            
            # 1. Whitelist check
            whitelisted = is_whitelisted(text)
            print(f"   Whitelisted: {whitelisted}")
            
            # 2. Ignore check
            ignored = should_ignore(text)
            print(f"   Should Ignore: {ignored}")
            
            # 3. Spam check (Rule/NB)
            spam_rule, reason_rule = is_spam(text, db)
            print(f"   Spam (Rule/NB): {spam_rule} ({reason_rule})")
            
            # 4. Review Spam check
            review_spam = is_review_spam(text)
            print(f"   Review Spam: {review_spam}")

            # Overall Spam result (simplified)
            is_any_spam = (spam_rule or review_spam or is_promo_spam(text, db)) and not whitelisted
            
            # 5. LLM Spam check (only if not already filtered or for edge cases)
            if os.environ.get("LLM") == "1":
                llm_spam, llm_reason = is_spam_llm(text)
                print(f"   Spam (LLM): {llm_spam} ({llm_reason})")
                is_any_spam = is_any_spam or (llm_spam and not whitelisted)

            print(f"   Final Result -> SPAM: {is_any_spam}")
            print("-" * 30)

    finally:
        db.close()

if __name__ == "__main__":
    test_filters()
