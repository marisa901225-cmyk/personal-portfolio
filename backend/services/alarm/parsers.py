import re
from datetime import datetime

def parse_card_approval(text: str):
    """
    카드 승인/결제 내역 파싱 시도 (Regex)
    - 멀티라인 (카카오페이 등), 단일라인 (SMS), 뱅킹 출금 지원
    """
    amount = 0
    merchant = "알 수 없는 가맹점"
    method = "신용카드"

    # 1. 카카오페이 멀티라인 형태 (결제가 완료되었어요 등)
    # --------------------------------------------------
    # - 구매처 : (.+)
    # - 결제금액 : ([0-9,]+)원
    if "결제가 완료" in text or "굿딜 결제" in text:
        m_amt = re.search(r'(?:결제|주문)금액\s*:\s*([0-9,]+)원', text)
        m_mer = re.search(r'구매처\s*:\s*(.+)$', text, re.MULTILINE)
        m_met = re.search(r'결제수단\s*:\s*(.+)$', text, re.MULTILINE)
        
        if m_amt:
            amount = float(m_amt.group(1).replace(",", ""))
            if m_mer: merchant = m_mer.group(1).strip()
            if m_met: method = m_met.group(1).strip()
            return {
                "amount": -amount,
                "merchant": merchant,
                "method": f"카카오페이({method})",
                "date": datetime.now().date()
            }

    # 2. 뱅킹 출금 알림 형태
    # --------------------------------------------------
    # 예: [출금] 카카오페이 10,000원 ...
    m_withdraw = re.search(r'\[출금\]\s*([^\d\s]+)\s*([0-9,]+)원', text)
    if m_withdraw:
        merchant = m_withdraw.group(1).strip()
        
        # [추가] 자기이체/충전 제외 로직
        # 가계부에 "카카오페이"가 가맹점으로 찍히는 건 보통 충전임. 
        # 실제 소비는 카카오페이 결제 완료 알림에서 잡힘.
        if merchant in ["카카오페이", "(주)카카오페이", "이창후", "충전"]:
            return None
            
        amount = float(m_withdraw.group(2).replace(",", ""))
        return {
            "amount": -amount,
            "merchant": merchant,
            "method": "계좌이체/페이충전",
            "date": datetime.now().date()
        }

    # 3. 기존 SMS/단일라인 형태
    # --------------------------------------------------
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
