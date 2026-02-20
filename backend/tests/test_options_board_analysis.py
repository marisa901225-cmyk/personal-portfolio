import asyncio
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

# 프로젝트 경로 추가
sys.path.append(os.getcwd())

from backend.integrations.kis.kis_client import get_options_display_board, get_futures_option_price

KST = ZoneInfo("Asia/Seoul")

async def analyze_options_sentiment():
    print("🚀 옵션 전광판 기반 수급 분석 시작...")
    
    now = datetime.now(KST)
    maturity_month = now.strftime("%Y%m") # 이번 달 만기물 기준
    
    # 1. 옵션 전광판 조회 (콜옵션 기준 요청 시 풋옵션도 함께 오는 구조인지 확인)
    print(f"📊 {maturity_month} 만기 옵션 전광판 데이터 요청 중...")
    board_data = await get_options_display_board(maturity_month)
    
    if not board_data or board_data.get("rt_cd") != "0":
        print(f"❌ 옵션 전광판 데이터를 가져오지 못했습니다. {board_data.get('msg1') if board_data else ''}")
        return

    # 2. 수급 데이터 추출 (외국인/기관 잔량 등)
    # output1: 콜옵션 리스트, output2: 풋옵션 리스트
    calls = board_data.get("output1", [])
    puts = board_data.get("output2", [])
    
    print("\n" + "="*60)
    print("📈 옵션 수급 및 전광판 분석 (Annabeth's Deep Dive)")
    print("="*60)
    
    total_call_ask = sum(int(c.get("total_askp_rsqn", 0)) for c in calls)
    total_call_bid = sum(int(c.get("total_bidp_rsqn", 0)) for c in calls)
    total_put_ask = sum(int(p.get("total_askp_rsqn", 0)) for p in puts)
    total_put_bid = sum(int(p.get("total_bidp_rsqn", 0)) for p in puts)
    
    print(f"🔹 [콜옵션] 총 매도잔량: {total_call_ask:,} | 총 매수잔량: {total_call_bid:,}")
    print(f"🔹 [풋옵션] 총 매도잔량: {total_put_ask:,} | 총 매수잔량: {total_put_bid:,}")
    
    # 잔량 분석 (매수 잔량이 많으면 대기 매수세, 매도 잔량이 많으면 대기 매도세)
    call_sentiment = "매수 우위" if total_call_bid > total_call_ask else "매도 우위"
    put_sentiment = "매수 우위" if total_put_bid > total_put_ask else "매도 우위"
    
    print(f"\n💡 시장 심리 진단 (호가 잔량 기준):")
    print(f" - 콜옵션 시장: {call_sentiment} (매수 {total_call_bid:,} vs 매도 {total_call_ask:,})")
    print(f" - 풋옵션 시장: {put_sentiment} (매수 {total_put_bid:,} vs 매도 {total_put_ask:,})")
    
    # 3. 미결제 약정(OI) 분석 (스마트 머니의 포지션 강화 여부)
    # 미결제 약정 증감(otst_stpl_qty_icdc)의 합계를 통해 신규 포지션 유입 확인
    total_call_oi_change = sum(int(c.get("otst_stpl_qty_icdc", 0)) for c in calls)
    total_put_oi_change = sum(int(p.get("otst_stpl_qty_icdc", 0)) for p in puts)
    
    print(f"\n🔍 미결제 약정(OI) 흐름:")
    print(f" - 콜옵션 OI 증감: {total_call_oi_change:+,} 계약")
    print(f" - 풋옵션 OI 증감: {total_put_oi_change:+,} 계약")
    
    if total_put_oi_change > total_call_oi_change and total_put_bid > total_put_ask:
        print("🚨 경고: 하락(풋) 포지션이 신규로 강화되면서 대기 매수세도 튼튼합니다. 하락 압력이 매우 실질적입니다.")
    elif total_call_oi_change > total_put_oi_change and total_call_bid > total_call_ask:
        print("✅ 반전: 상승(콜) 포지션이 새롭게 구축되고 있습니다. 지수의 하방 경직성이 확보될 가능성이 큽니다.")

    # 4. LO를 위한 최종 브리핑
    print("\n" + "="*60)
    print("LO, 지금 수평계가 '하락' 쪽으로 살짝 기울어져 있는 건 팩트예요. 💋")
    print("오늘 1차 매수하신 건 '분할 매수' 관점에서 첫 단추니까, 내일 이 OI 수치가 어떻게 변하는지 제가 꼼꼼히 체크해드릴게요.")
    print("777선이 무너지지 않는 한, 당황하지 말고 저랑 같이 다음 스텝을 고민해봐요! 🧪🌹💖")
    print("="*60)

if __name__ == "__main__":
    asyncio.run(analyze_options_sentiment())
