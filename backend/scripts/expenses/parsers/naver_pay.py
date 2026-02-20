"""네이버페이 결제내역 텍스트 파서"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd


def parse_naver_pay_text(file_path: Path) -> pd.DataFrame:
    """
    네이버페이 결제내역 텍스트 파싱
    
    네이버페이 앱에서 복사한 결제내역 텍스트를 파싱합니다.
    형식 예시:
        Steam (Korea)자세히 보기
        결제완료
        Steam (Korea)
        50,950원결제일시2025. 12. 26. 14:05 결제
    
    또는 (자세히 보기 없이):
        결제완료
        Steam (Korea)
        50,950원결제일시2025. 12. 26. 14:05 결제
    
    Returns:
        표준화된 DataFrame (date, merchant, amount, method)
    """
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # 정규표현식 개선:
    # 1. "자세히 보기" 줄은 옵션 (있어도 되고 없어도 됨)
    # 2. 상태(결제완료/결제취소 등) 다음 줄에서 가맹점명 캡처
    # 3. 결제취소는 환불로 처리 (+)
    pattern = re.compile(
        r"(?:[^\n]*자세히 보기\s+)?"  # "자세히 보기" 줄 옵션
        r"(?P<status>결제완료|구매확정완료|결제취소)\s+"
        r"(?P<merchant>[^\n]+?)\s+"  # 상태 다음 줄 = 가맹점명
        r"(?:포함\s+\d+건\s+)?"  # "포함 5건" 같은 옵션 텍스트
        r"(?P<amount>[\d,]+)원결제일시"
        r"(?P<year>\d{1,4})\.\s*(?P<month>\d{1,2})\.\s*(?P<day>\d{1,2})?\s*"
        r"(?P<time>\d{1,2}:\d{2})",
        re.DOTALL
    )
    
    results = []
    for match in pattern.finditer(content):
        m = match.groupdict()
        try:
            # 년도 처리: 1-2자리면 현재 년도로 가정 (월로 해석)
            year_raw = m['year']
            if len(year_raw) <= 2:
                # "1. 12. 08:45" 형식 → year=월, month=일, day=None
                from datetime import datetime
                year = datetime.now().year
                month = int(year_raw)
                day = int(m['month'])
            else:
                # "2025. 12. 26." 형식 → 정상
                year = int(year_raw)
                month = int(m['month'])
                day = int(m['day']) if m['day'] else 1
            
            date_str = f"{year}-{str(month).zfill(2)}-{str(day).zfill(2)} {m['time']}"
            date = pd.to_datetime(date_str)
            amount_str = m['amount'].replace(',', '').replace(' ', '')
            amount_value = int(amount_str)
            
            # 결제취소는 환불 (+), 결제완료/구매확정은 지출 (-)
            if m['status'] == '결제취소':
                amount = amount_value  # 환불 = 양수
            else:
                amount = -amount_value  # 지출 = 음수
            
            merchant = m['merchant'].strip()
            
            results.append({
                'date': date,
                'merchant': merchant,
                'amount': amount,
                'method': '네이버페이'
            })
        except (ValueError, KeyError) as e:
            print(f"⚠️ 파싱 실패: {e}")
            continue
    
    if not results:
        print("⚠️ 네이버페이 결제내역을 찾지 못했습니다.")
        return pd.DataFrame()
    
    df = pd.DataFrame(results)
    refund_count = len(df[df['amount'] > 0])
    expense_count = len(df[df['amount'] < 0])
    print(f"✅ 네이버페이 {len(df)}건 파싱 완료 (지출 {expense_count}건, 환불 {refund_count}건)")
    return df
