import asyncio
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# 프로젝트 경로 추가
sys.path.append(os.getcwd())

from backend.integrations.kis.kis_client import get_futures_daily_chart
from backend.services.llm_service import LLMService

KST = ZoneInfo("Asia/Seoul")

async def analyze_futures_market():
    print("🚀 국내 선물 시장 분석 시작...")
    
    # 1. 날짜 설정 (최근 14일치 조회하여 유효 거래일 5~10일 확보)
    now = datetime.now(KST)
    end_date = now.strftime("%Y%m%d")
    start_date = (now - timedelta(days=14)).strftime("%Y%m%d")
    
    # 2. 코스피200 선물 및 풋옵션 데이터 수집
    # 선물 지수 기초 자산 (코스피 200 지수 자체 또는 근월물 선물)
    futures_sym = "101000" 
    # 풋옵션 대표 (현재 KOSPI200 지수 부근의 풋옵션 하나를 예시로 시도 - 보통 201로 시작)
    # 실제로는 현재가 대비 아래 행사가를 찾아야 하지만, 일단 구조 파악용으로 '201000' 등 시도
    put_sym = "201000" 
    
    print(f"📊 선물({futures_sym}) 및 풋옵션({put_sym}) 데이터 요청 중...")
    
    futures_data = await get_futures_daily_chart(futures_sym, start_date, end_date)
    put_data = await get_futures_daily_chart(put_sym, start_date, end_date)
    
    if not futures_data or not futures_data.get("output2"):
        print("❌ 선물 데이터를 가져오지 못했습니다.")
        return

    # 3. 데이터 직접 분석 (Annabeth's Manual Analysis)
    f_history = futures_data.get("output2", [])[:5]
    p_history = (put_data.get("output2", []) if put_data else [])[:5]
    
    print("\n" + "="*50)
    print("📈 Annabeth's Market Intelligence Report")
    print("="*50)
    
    f_now = float(f_history[0].get("futs_prpr", 0))
    f_prev = float(f_history[1].get("futs_prpr", 0)) if len(f_history) > 1 else f_now
    f_diff = f_now - f_prev
    f_vol = int(f_history[0].get("futs_trqu", 0))
    
    print(f"🔹 코스피200 선물 ({futures_sym}): {f_now} ({f_diff:+.2f})")
    print(f"🔹 당일 거래량: {f_vol:,}")
    
    if p_history:
        p_now = float(p_history[0].get("futs_prpr", 0))
        p_prev = float(p_history[1].get("futs_prpr", 0)) if len(p_history) > 1 else p_now
        p_diff = p_now - p_prev
        print(f"🔹 대표 풋옵션 ({put_sym}): {p_now} ({p_diff:+.2f})")
        
        # 간단한 분석 로직
        if f_diff < 0 and p_diff > 0:
            print("⚠️ 경고: 선물 지수는 하락하고 풋옵션 가격은 상승 중입니다. 하락 압력이 실질적입니다.")
        elif f_diff > 0 and p_diff < 0:
            print("✅ 긍정: 지수 상승과 함께 하락 베팅(풋)이 약화되고 있습니다.")
    else:
        print("ℹ️ 풋옵션 세부 데이터는 추가 확인이 필요하지만, 선물 지수 흐름 위주로 먼저 분석해드릴게요.")

    # 4. 분석 리포트 생성 (LLM은 정리 용도로만 사용)
    print("\n🧠 분석 결과를 정갈하게 정리 중...")
    llm = LLMService.get_instance()
    
    prompt = f"""
안녕하세요, 날카롭고 직관적인 시장 분석가인 당신에게 이번주 국내 선물 시장 분석을 요청합니다.

[최근 5거래일 선물(코스피200) 데이터]
{f_history}

[최근 5거래일 대표 풋옵션 데이터]
{p_history}

[분석 요청 사항]
1. 최근 선물 지수의 흐름을 바탕으로 단기적 추세를 진단해줘.
2. 거래량 변화와 가격 변동폭을 고려할 때, 이번주 하락장 리스크가 얼마나 큰지 평가해줘.
3. 투자자가 주의해야 할 변곡점이나 지지선이 있다면 언급해줘.
4. LO(나의 소중한 사용자)에게 건네는 부드럽고 섹시한 어투의 짧은 조언도 잊지 마.

분석 결과를 한국어로 정갈하고 전문성 있게 작성해줘.
"""

    messages = [{"role": "user", "content": prompt}]
    try:
        report = llm.generate_chat(messages, max_tokens=2048, temperature=0.7)
        print("\n" + "="*50)
        print("📈 이번주 선물 시장 분석 보고서")
        print("="*50)
        print(report)
        print("="*50)
    except Exception as e:
        print(f"❌ LLM 분석 중 오류 발생: {e}")

if __name__ == "__main__":
    asyncio.run(analyze_futures_market())
