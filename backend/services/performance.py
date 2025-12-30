from datetime import date, datetime
from typing import List, Tuple

def xirr(transactions: List[Tuple[date, float]]) -> float:
    """
    Calculates the internal rate of return for a series of cash flows that occur at 
    irregular intervals.
    
    transactions: List of (date, amount) tuples.
    - Deposits to portfolio: Negative (outflow from pocket)
    - Withdrawals/Terminal Value: Positive (inflow to pocket)
    """
    if not transactions:
        return 0.0
        
    # Newton-Raphson method
    def xnpv(rate: float, transactions: List[Tuple[date, float]]) -> float:
        d0 = transactions[0][0]
        return sum([amount / (1.0 + rate) ** ((d - d0).days / 365.2425) for d, amount in transactions])

    def dxnpv(rate: float, transactions: List[Tuple[date, float]]) -> float:
        d0 = transactions[0][0]
        return sum([amount * (-(d - d0).days / 365.2425) * (1.0 + rate) ** (-(d - d0).days / 365.2425 - 1) for d, amount in transactions])

    # Initial guess
    rate = 0.1
    for i in range(100):
        f = xnpv(rate, transactions)
        df = dxnpv(rate, transactions)
        if abs(df) < 1e-10:
            break
        new_rate = rate - f / df
        if abs(new_rate - rate) < 1e-6:
            return new_rate
        rate = new_rate
        
    return rate
