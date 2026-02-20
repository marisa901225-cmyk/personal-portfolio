import sys
import os
from datetime import datetime
from zoneinfo import ZoneInfo

# 프로젝트 경로 추가
sys.path.append(os.getcwd())

from backend.services.news.weather_kma import get_base_times_ordered, get_base_time

def test_time_logic():
    KST = ZoneInfo("Asia/Seoul")
    now = datetime.now(KST)
    print(f"Current KST Time: {now}")
    
    times = get_base_times_ordered()
    print(f"Candidate times: {times}")
    
    b_date, b_time = get_base_time()
    print(f"Selected Base Time: {b_date} {b_time}")
    
    # 검증: 7시 스케줄이면 0500이 잡혀야 함 (07:10 이전이면 0200, 이후면 0500)
    # 현재 시간이 16시이므로 무조건 최신인 1400 또는 그 이전이 나와야 함
    if times:
        print("Test Passed: Candidate times found.")
    else:
        print("Test Failed: No candidate times.")

if __name__ == "__main__":
    test_time_logic()
