from backend.routers.telegram_webhook import classify_query

test_cases = [
    ("T1 경기 언제야?", "esports_schedule"),
    ("롤드컵 일정 알려줘", "esports_schedule"),
    ("요즘 유행하는 스팀 게임 추천해줘", "game_trend"),
    ("신작 게임 트렌드 어때?", "game_trend"),
    ("나스닥 지수 알려줘", "economy_news"),
    ("환율 전망이 어떻게 돼?", "economy_news"),
    ("이번 달 리포트 보여줘", "report"),
    ("내 가계부 지출 내역 알려줘", "report"),
    ("안녕? 오늘 날씨 어때?", "general_chat"),
    ("뭐해?", "general_chat"),
    ("STEAM 신작", "game_trend"),
    ("REPORT", "report")
]

failed = 0
for text, expected in test_cases:
    actual = classify_query(text)
    if actual == expected:
        print(f"✅ [PASS] '{text}' -> {actual}")
    else:
        print(f"❌ [FAIL] '{text}' -> Expected {expected}, got {actual}")
        failed += 1

if failed == 0:
    print("\nAll tests passed! 🎉")
    exit(0)
else:
    print(f"\n{failed} tests failed. 😢")
    exit(1)
