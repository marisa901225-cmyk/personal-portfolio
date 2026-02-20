import sys
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from unittest.mock import patch

# 프로젝트 경로 추가
sys.path.append(os.getcwd())

from backend.services.news.weather_kma import get_ultra_base_times_ordered

def test_ultra_short_time_logic():
    KST = ZoneInfo("Asia/Seoul")
    
    # 15:30 시뮬레이션 (초단기예보는 매시 30분 발표되므로, 15:30이면 15:30분 데이터가 후보에 있어야 함)
    # 기상청 지침상 보통 45분에 데이터가 생성되므로, 안전하게 15:00가 최신일 수 있지만 로직상 후보 추출 확인
    simulated_now = datetime(2026, 2, 6, 15, 30, tzinfo=KST)
    
    print(f"Simulated KST Time: {simulated_now}")
    
    with patch('backend.services.news.weather_kma.datetime') as mock_datetime:
        mock_datetime.now.return_value = simulated_now
        mock_datetime.replace = datetime.replace
        mock_datetime.strptime = datetime.strptime
        
        times = get_ultra_base_times_ordered(max_slots=5)
        print(f"Candidate ultra-short times for 15:30: {times}")
        
        # 15:30에 실행되면 15:30, 15:00, 14:30... 순으로 나와야 함
        expected_top = {'base_date': '20260206', 'base_time': '1530'}
        if times[0] == expected_top:
            print("✅ Test Passed: 15:30 base time correctly identified.")
        else:
            print(f"❌ Test Failed: Expected {expected_top}, but got {times[0]}")

if __name__ == "__main__":
    test_ultra_short_time_logic()
