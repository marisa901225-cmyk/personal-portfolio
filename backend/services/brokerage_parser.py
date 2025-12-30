import pandas as pd
from datetime import datetime
from typing import List, Dict, Any, Optional
from abc import ABC, abstractmethod
from ..schemas import ExternalCashflowCreate

class BrokerageParser(ABC):
    @abstractmethod
    def parse(self, file_path: str, user_id: int) -> List[ExternalCashflowCreate]:
        pass

class SamsungParser(BrokerageParser):
    def parse(self, file_path: str, user_id: int) -> List[ExternalCashflowCreate]:
        # Samsung Excel usually has a header row that needs to be skipped
        # We saw skiprows=1 was needed in our terminal investigation
        try:
            df = pd.read_excel(file_path, skiprows=1)
        except Exception as e:
            # Try without skiprows as backup
            df = pd.read_excel(file_path)
            if '거래명' not in df.columns:
                 raise ValueError("Invalid Samsung Securities Excel format")

        # Map Samsung transaction types to XIRR cashflow directions
        # Negative = Money into portfolio (Inflow)
        # Positive = Money out of portfolio (Outflow)
        
        inflow_types = [
            '이체입금', '대체입금', '외화이체입금', '타사입고', 
            '배당금입금', '이용료입금', '이자입금', '외화배당세금환급',
            '시간외환전정산차금입금'
        ]
        outflow_types = [
            '이체출금', '대체출금', '실시간자동출금', '오픈이체출금',
            '세금출금(해외)'
        ]
        
        results = []
        for _, row in df.iterrows():
            trade_name = str(row.get('거래명', ''))
            date_val = row.get('거래일자')
            
            # Handle date format
            if isinstance(date_val, str):
                try:
                    dt = datetime.strptime(date_val, '%Y-%m-%d').date()
                except:
                    continue
            elif isinstance(date_val, datetime):
                dt = date_val.date()
            else:
                continue
                
            amount = 0
            is_valid = False
            
            # KRW Handling
            if trade_name in inflow_types:
                # KRW amount is usually in '거래금액' or '정산금액'
                # For deposits, it's positive in the sheet, but we need it NEGATIVE for XIRR inflow
                krw = float(row.get('정산금액', 0) or row.get('거래금액', 0))
                if krw != 0:
                    amount = -abs(krw)
                    is_valid = True
                else:
                    # Check foreign currency
                    fx = float(row.get('외화정산금액', 0) or row.get('외화거래금액', 0))
                    if fx != 0:
                        # We might need a rate, but for now, if it's the main account, 
                        # maybe we use the KRW equivalent if available
                        # Samsung sheet often has '거래금액' as KRW even for FX trades
                        pass

            elif trade_name in outflow_types:
                krw = float(row.get('정산금액', 0) or row.get('거래금액', 0))
                if krw != 0:
                    amount = abs(krw)
                    is_valid = True
            
            if is_valid:
                results.append(ExternalCashflowCreate(
                    date=dt,
                    amount=amount,
                    description=f"[{trade_name}] {row.get('종목명', '')} {row.get('상대계좌명', '')}".strip(),
                    account_info=f"삼성증권 ({row.get('통화코드', 'KRW')})"
                ))
        
        return results

def get_parser(filename: str) -> Optional[BrokerageParser]:
    # Simple dispatcher
    if "삼성" in filename:
        return SamsungParser()
    return None
