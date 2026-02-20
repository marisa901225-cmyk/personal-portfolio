from datetime import datetime
from backend.core.esports_config import is_league_in_active_window

def test_lec_window():
    # LEC는 매일 22:00 ~ 익일 02:00 (24+2)
    test_cases = [
        ("오후 11시 (활성)", 23, 0, True),
        ("오전 1시 (활성)", 1, 0, True),
        ("오전 2시 (비활성 - 경계)", 2, 0, False),
        ("오전 3시 (비활성)", 3, 0, False),
        ("오후 9시 (비활성)", 21, 0, False),
    ]

    print("--- LEC Active Window Test ---")
    for desc, hour, minute, expected in test_cases:
        # 요일은 0(월)로 고정 (LEC는 매일 동일 설정)
        result = is_league_in_active_window("LEC", "league-of-legends", 0, hour * 60 + minute)
        status = "PASS" if result == expected else "FAIL"
        print(f"[{status}] {desc}: {hour:02d}:{minute:02d} -> Result: {result}, Expected: {expected}")

if __name__ == "__main__":
    test_lec_window()
