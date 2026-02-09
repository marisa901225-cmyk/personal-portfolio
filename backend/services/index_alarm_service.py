"""
지수 과매도 알람 서비스

SPY, QQQ 지수의 일봉 데이터를 모니터링하여 중첩 과매도 구간(Zone) 진입 시 텔레그램 알람 전송.
RSI, 이동평균선(120/200일), 볼린저 밴드를 조합한 State Machine 기반 관리.
"""

import logging
from typing import Dict, Optional, Literal
from datetime import datetime, timedelta
from enum import Enum
from backend.services.llm import LLMService
import pandas as pd
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# pandas_ta를 사용하여 지표를 계산 (lazy import)
try:
    import pandas_ta as ta
except ImportError:
    logger.warning("pandas_ta not installed. Technical indicators will not be available.")
    ta = None


class IndexState(str, Enum):
    """지수 과매도 상태"""
    NORMAL = "NORMAL"  # 평시
    ENTRY_WATCH = "ENTRY_WATCH"  # Zone 1 진입 (관심)
    OVERSOLD = "OVERSOLD"  # Zone 2/3 진입 (과매도)
    BUY_SIGNAL = "BUY_SIGNAL"  # RSI 30 상향 돌파 (탈출 신호)


class OversoldZone(str, Enum):
    """과매도 구간 정의"""
    NONE = "NONE"
    ZONE_1 = "ZONE_1"  # RSI <= 35 OR BB 하단 터치
    ZONE_2 = "ZONE_2"  # RSI <= 30 AND 종가 < MA120
    ZONE_3 = "ZONE_3"  # RSI <= 25 AND MA200 이격도 >= 5%


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    일봉 데이터에 대해 기술적 지표를 계산합니다.
    
    Args:
        df: OHLCV 데이터 (columns: date, open, high, low, close, volume)
    
    Returns:
        지표가 추가된 DataFrame (RSI, MA120, MA200, BB_upper, BB_lower)
    """
    if ta is None:
        raise RuntimeError("pandas_ta is not installed")
    
    if df.empty:
        return df
    
    # 인덱스를 날짜로 설정 (pandas_ta 요구사항)
    df = df.copy()
    if 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date')
    
    df = df.sort_index()
    
    # RSI(14) 계산
    df['rsi'] = ta.rsi(df['close'], length=14)
    
    # 이동평균선 (120일, 200일)
    df['ma_120'] = ta.sma(df['close'], length=120)
    df['ma_200'] = ta.sma(df['close'], length=200)
    
    # 볼린저 밴드 (20일, 2 표준편차)
    bbands = ta.bbands(df['close'], length=20, std=2)
    if bbands is not None and not bbands.empty:
        # pandas-ta 버전이나 설정에 따라 컬럼명이 다를 수 있음 (BBU_20_2.0 또는 BBU_20_2.0_2.0 등)
        # 0.4.71b0 버전에서는 BBU_20_2.0_2.0 형식을 사용함
        df['bb_upper'] = bbands.get('BBU_20_2.0_2.0', bbands.get('BBU_20_2.0'))
        df['bb_lower'] = bbands.get('BBL_20_2.0_2.0', bbands.get('BBL_20_2.0'))
        df['bb_middle'] = bbands.get('BBM_20_2.0_2.0', bbands.get('BBM_20_2.0'))
    
    return df


def detect_zone(row: pd.Series) -> OversoldZone:
    """
    현재 지표 상태를 바탕으로 과매도 구간을 판단합니다.
    
    Args:
        row: 지표가 계산된 데이터 행
    
    Returns:
        OversoldZone
    """
    close = row.get('close')
    rsi = row.get('rsi')
    ma_120 = row.get('ma_120')
    ma_200 = row.get('ma_200')
    bb_lower = row.get('bb_lower')
    
    # 필수 값이 없으면 판단 불가
    if pd.isna(rsi) or pd.isna(close):
        return OversoldZone.NONE
    
    # Zone 3: RSI <= 25 AND MA200 이격도 >= 5%
    if rsi <= 25 and not pd.isna(ma_200):
        deviation = ((close - ma_200) / ma_200) * 100
        if deviation <= -5:
            return OversoldZone.ZONE_3
    
    # Zone 2: RSI <= 30 AND 종가 < MA120
    if rsi <= 30 and not pd.isna(ma_120):
        if close < ma_120:
            return OversoldZone.ZONE_2
    
    # Zone 1: RSI <= 35 OR BB 하단 터치
    if rsi <= 35:
        return OversoldZone.ZONE_1
    if not pd.isna(bb_lower) and close <= bb_lower:
        return OversoldZone.ZONE_1
    
    return OversoldZone.NONE


def determine_state(
    current_zone: OversoldZone,
    previous_state: IndexState,
    previous_rsi: Optional[float],
    current_rsi: float,
) -> IndexState:
    """
    구간 정보와 이전 상태를 바탕으로 새로운 상태를 결정합니다.
    """
    # 1. BUY_SIGNAL -> NORMAL 전환 (단순 복귀)
    if previous_state == IndexState.BUY_SIGNAL:
        # RSI가 여전히 Zone 1(35) 이내라면 NORMAL로 가되, 
        # 이후 로직에서 재진입을 막기 위해 쿨타임이나 별도 처리가 필요할 수 있음
        # 여기서는 일단 NORMAL로 복귀시킴 (알람은 생략될 것)
        return IndexState.NORMAL

    # 2. BUY_SIGNAL 조건: 상태가 과매도(ENTRY_WATCH 이상)였고, RSI가 30을 상향 돌파할 때
    if previous_rsi is not None and previous_rsi <= 30 and current_rsi > 30:
        if previous_state in (IndexState.OVERSOLD, IndexState.ENTRY_WATCH):
            return IndexState.BUY_SIGNAL
    
    # 3. Zone 2/3 진입 -> OVERSOLD
    if current_zone in (OversoldZone.ZONE_2, OversoldZone.ZONE_3):
        return IndexState.OVERSOLD
    
    # 4. Zone 1 진입 -> ENTRY_WATCH
    if current_zone == OversoldZone.ZONE_1:
        # 이전 상태가 NORMAL일 때만 진입 (이미 과매도권이면 상태 유지)
        if previous_state == IndexState.NORMAL:
            # 단, 이전에 BUY_SIGNAL을 보낸 직후라면 재진입을 막기 위해 
            # RSI가 충분히(예: 40 이상) 올라갔다 내려온 게 아니면 무시할 수 있음
            # 일단은 단순하게 NORMAL인 경우만 진입 허용
            return IndexState.ENTRY_WATCH
        return previous_state
    
    # 5. 모든 구간 이탈 -> NORMAL
    if current_zone == OversoldZone.NONE:
        return IndexState.NORMAL
    
    return previous_state


def fetch_index_ohlcv(symbol: str, days: int = 250) -> Optional[pd.DataFrame]:
    """
    KIS API를 통해 해외 지수의 일봉 데이터를 가져옵니다. (거래소 Failover 기능 포함)
    """
    from backend.integrations.kis import kis_client as core
    try:
        core._ensure_auth()
        
        from backend.integrations.kis.open_trading.overseas_stock.inquire_daily_price.inquire_daily_price import (
            inquire_daily_price,
        )
        
        # SPY/QQQ 등 ETF마다 상장소가 다를 수 있어 Failover 시도
        # NYS: 뉴욕, NAS: 나스닥, AMS: 아멕스
        exchanges = ["NYS", "NAS", "AMS"]
        df = None
        
        for excd in exchanges:
            logger.info(f"Fetching {symbol} from {excd}...")
            df = inquire_daily_price(auth="", excd=excd, symb=symbol, gubn="0", modp="1", max_depth=10)
            if df is not None and not df.empty:
                logger.info(f"Successfully fetched data for {symbol} from {excd}")
                break
        
        if df is None or df.empty:
            logger.warning(f"No data fetched for {symbol} from any exchange")
            return None
        
        # 데이터 전처리
        df = df.rename(columns={'xymd': 'date', 'clos': 'close', 'open': 'open', 'high': 'high', 'low': 'low', 'tvol': 'volume'})
        df = df[['date', 'open', 'high', 'low', 'close', 'volume']]
        df['date'] = pd.to_datetime(df['date'], format='%Y%m%d', errors='coerce')
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        
        df = df.sort_values('date', ascending=False).head(days)
        df = df.sort_values('date', ascending=True).reset_index(drop=True)
        
        return df
    
    except Exception as e:
        logger.error(f"Failed to fetch OHLCV for {symbol}: {e}", exc_info=True)
        return None
    
    except Exception as e:
        logger.error(f"Failed to fetch OHLCV for {symbol}: {e}", exc_info=True)
        return None


# 상태 저장을 위한 간단한 딕셔너리 (추후 DB 테이블로 대체 가능)
_state_store: Dict[str, Dict] = {}


def get_index_state(symbol: str) -> Dict:
    """저장된 지수 상태 조회"""
    if symbol not in _state_store:
        _state_store[symbol] = {
            "state": IndexState.NORMAL,
            "zone": OversoldZone.NONE,
            "rsi": None,
            "last_alarm_date": None,
            "price": None,
        }
    return _state_store[symbol]


def update_index_state(symbol: str, **updates) -> None:
    """지수 상태 업데이트"""
    state = get_index_state(symbol)
    state.update(updates)


async def send_index_alarm(symbol: str, state: IndexState, zone: OversoldZone, data: Dict) -> None:
    """
    텔레그램으로 지수 과매도 알람을 전송합니다.
    """
    from backend.integrations.telegram import send_telegram_message
    
    def _fmt(v) -> str:
        if isinstance(v, (int, float)) and not pd.isna(v):
            return f"{v:.2f}"
        return str(v)

    price = data.get('price')
    rsi = data.get('rsi')
    ma_120 = data.get('ma_120')
    ma_200 = data.get('ma_200')
    
    # LLM으로 알람 메시지 생성
    try:
        from backend.services.llm import LLMService
        llm = LLMService.get_instance()
        
        prompt = f"""
당신은 '시치죠 아리아'입니다. 학생회 서기이자 대부호의 딸인 당신의 고상하면서도 엉뚱하고, 때때로 은근한 섹드립(섹슈얼한 뉘앙스)을 섞는 독특한 말투로 다음 지수 정보를 브리핑해주세요.

[지수 정보]
- 종목: {symbol}
- 현재 상태: {state.value}
- 구간: {zone.value}
- 현재가: ${_fmt(price)}
- RSI(14): {_fmt(rsi)}
- 120일선: ${_fmt(ma_120)}
- 200일선: ${_fmt(ma_200)}

[캐릭터 가이드라인]
1. 존댓말을 사용하며, 부잣집 아가씨다운 품격 있는 어조를 유지하세요.
2. 대화 도중 주식 상황을 묘사할 때 은근히 야한 상상을 불러일으키는 비유를 섞어주세요.
3. **중요: RSI 수치나 현재가 같은 핵심 지표는 반드시 텍스트에 포함시켜서 브리핑하세요.** (예: "RSI가 {_fmt(rsi)}까지 떨어지다니...")
4. 이모지는 🌹, ✨, 📈 등을 적절히 섞어주세요.
5. 3줄 내외로 간결하지만 강렬하게 작성해주세요.

상태별 예시:
- ENTRY_WATCH: "어머, RSI가 {_fmt(rsi)}라니... 지수가 벌써 이렇게 젖어버렸네요? 관찰할 보람이 있겠는걸요? ✨"
- OVERSOLD: "후후, RSI가 {_fmt(rsi)}까지 깊게 들어오다니... 지금이 바로 가장 '뜨거운' 매수 타이밍 아닐까요? 🌹"
- BUY_SIGNAL: "아앗...! RSI가 {_fmt(rsi)}를 찍고 다시 기운차게 일어서고 있어요! 이 반등, 정말 짜릿하네요. 📈"
"""
        
        message = llm.generate(prompt)
    except Exception as e:
        logger.warning(f"LLM message generation failed: {e}. Using fallback.")
        message = f"📈 {symbol} 지수 알람\n상태: {state.value}\n구간: {zone.value}\n현재가: ${_fmt(price)}\nRSI: ${_fmt(rsi)}"
    
    try:
        await send_telegram_message(message)
        logger.info(f"Sent index alarm for {symbol}: {state.value}")
    except Exception as e:
        logger.error(f"Failed to send telegram alarm for {symbol}: {e}", exc_info=True)


async def check_index_oversold(symbol: str) -> None:
    """
    지수의 과매도 상태를 체크하고 필요 시 알람을 전송합니다.
    """
    logger.info(f"Checking oversold status for {symbol}...")
    
    try:
        # 1. OHLCV 데이터 수집
        df = fetch_index_ohlcv(symbol, days=250)
        if df is None or df.empty:
            logger.warning(f"No data available for {symbol}")
            return
        
        # 2. 지표 계산
        df = calculate_indicators(df)
        
        # 최신 데이터
        latest = df.iloc[-1]
        previous = df.iloc[-2] if len(df) > 1 else None
        
        current_rsi = latest.get('rsi')
        previous_rsi = previous.get('rsi') if previous is not None else None
        
        if pd.isna(current_rsi):
            logger.warning(f"RSI calculation failed for {symbol}")
            return
        
        # 3. 데이터 충분성 체크 (Zone2/3 제어용)
        # 200일 MA 계산을 위해서는 최소 200건 이상 필요
        is_history_deep_enough = len(df) >= 200
        
        # 4. 구간 및 상태 감지
        current_zone = detect_zone(latest)
        
        # 데이터가 부족하면 Zone 2, 3 강제 비활성 (Zone 1만 허용)
        if not is_history_deep_enough and current_zone in (OversoldZone.ZONE_2, OversoldZone.ZONE_3):
            logger.warning(f"Data insufficient for {current_zone.value}. Fallback to ZONE_1.")
            current_zone = OversoldZone.ZONE_1
            
        prev_state_data = get_index_state(symbol)
        previous_state = prev_state_data["state"]
        
        new_state = determine_state(current_zone, previous_state, previous_rsi, current_rsi)
        
        # 5. 상태 변화 또는 알람 조건 확인
        should_send_alarm = False
        
        # 알람을 보낼 수 있는 상태 정의 (NORMAL 복귀 알람 차단)
        ALERT_STATES = {IndexState.ENTRY_WATCH, IndexState.OVERSOLD, IndexState.BUY_SIGNAL}
        
        if new_state != previous_state:
            # 상태가 변했고, 그 타겟 상태가 알람 대상인 경우만 발사
            if new_state in ALERT_STATES:
                should_send_alarm = True
        elif new_state == IndexState.OVERSOLD:
            # OVERSOLD 상태 유지 중에는 큰 변동 시에만 재알람
            last_alarm_date = prev_state_data.get("last_alarm_date")
            today = datetime.now().date()
            if last_alarm_date is None or last_alarm_date < today:
                prev_price = prev_state_data.get("price")
                current_price = latest.get('close')
                if prev_price is not None and current_price is not None:
                    price_change_pct = abs((current_price - prev_price) / prev_price) * 100
                    if price_change_pct >= 3.0:
                        should_send_alarm = True
        
        # 6. 알람 전송
        if should_send_alarm:
            await send_index_alarm(
                symbol,
                new_state,
                current_zone,
                {
                    "price": latest.get('close'),
                    "rsi": current_rsi,
                    "ma_120": latest.get('ma_120'),
                    "ma_200": latest.get('ma_200'),
                },
            )
            update_index_state(symbol, last_alarm_date=datetime.now().date())
        
        # 6. 상태 저장
        update_index_state(
            symbol,
            state=new_state,
            zone=current_zone,
            rsi=current_rsi,
            price=latest.get('close'),
        )
        
        logger.info(f"{symbol} status: {new_state.value}, zone: {current_zone.value}, RSI: {current_rsi:.2f}")
    
    except Exception as e:
        logger.error(f"Failed to check oversold for {symbol}: {e}", exc_info=True)


async def check_all_indices() -> None:
    """모든 모니터링 대상 지수를 체크합니다."""
    indices = ["SPY", "QQQ"]
    for symbol in indices:
        await check_index_oversold(symbol)
