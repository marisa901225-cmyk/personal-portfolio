import re
from datetime import datetime

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
