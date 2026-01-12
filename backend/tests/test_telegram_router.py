import pytest
from backend.routers.telegram_webhook import classify_query

@pytest.mark.parametrize("text,expected", [
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
])
def test_classify_query(text, expected):
    """분류 함수 정합성 테스트"""
    assert classify_query(text) == expected

def test_classify_query_case_insensitivity():
    """대소문자 구분 없이 작동하는지 테스트"""
    assert classify_query("STEAM 신작") == "game_trend"
    assert classify_query("t1 경기") == "esports_schedule"
    assert classify_query("REPORT") == "report"
