import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from backend.services.news.core import (
    _normalize_text,
    calculate_simhash,
    detect_ad_keyword,
    get_jaccard_similarity,
    prepare_news_ingest_record,
    persist_news_record,
    is_duplicate_complex,
)
from backend.services.news.deduplication import compute_simhash_for_text, is_duplicate

class MockNews:
    def __init__(self, title, content_hash):
        self.title = title
        self.content_hash = content_hash

class TestNewsDedup(unittest.TestCase):
    def test_normalize_text(self):
        text = "<b>[속보]</b> T1, 롤드컵 결승 진출!  \n\n  "
        expected = "속보 t1 롤드컵 결승 진출"
        self.assertEqual(_normalize_text(text), expected)

    def test_jaccard_similarity(self):
        s1 = "T1 롤드컵 결승 진출 성공"
        s2 = "[속보] T1 롤드컵 결승 진출"
        sim = get_jaccard_similarity(s1, s2)
        self.assertGreaterEqual(sim, 0.6) # 유사함

    def test_is_duplicate_complex_simhash(self):
        # 거의 같은 제목/본문 -> Simhash 거리 가까움
        title1 = "삼성전자 하반기 실적 전망 맑음"
        desc1 = "반도체 수요 증가로 인해 실적이 개선될 것으로 보입니다."
        hash1 = calculate_simhash(title1 + desc1)
        
        title2 = "삼성전자 하반기 실적 전망 '맑음'"
        desc2 = "반도체 수요의 증가로 인하여 실적이 개선될 전망입니다."
        hash2 = calculate_simhash(title2 + desc2)
        
        # 가짜 기존 뉴스 리스트
        recent_news = [MockNews(title1, hash1)]
        
        # 하드한 중복 판별
        self.assertTrue(is_duplicate_complex(title2, hash2, recent_news))

    def test_is_duplicate_complex_jaccard(self):
        # Simhash는 조금 멀 수도 있지만 제목이 거의 같은 경우
        title1 = "이복현 금감원장 가상자산 시장 규제 강화 시사"
        hash1 = "1234567890" # 임의의 먼 해시
        
        title2 = "금감원장 이복현 가상자산 시장 규제 강화 시사"
        hash2 = "9876543210" # 임의의 먼 해시
        
        recent_news = [MockNews(title1, hash1)]
        
        # 제목 기반 자카드 유사도(0.8 이상)로 걸러져야 함
        self.assertTrue(is_duplicate_complex(title2, hash2, recent_news))

    def test_detect_ad_keyword(self):
        self.assertEqual(detect_ad_keyword("T1 팬미팅 이벤트 안내"), "이벤트")
        self.assertIsNone(detect_ad_keyword("T1 결승 진출"))

    def test_legacy_dedup_wrappers_use_core_simhash(self):
        text = "삼성전자 하반기 실적 전망 맑음"
        content_hash = calculate_simhash(text)
        self.assertEqual(compute_simhash_for_text(text), int(content_hash))
        self.assertTrue(is_duplicate(text, (content_hash,)))

    def test_prepare_news_ingest_record_skips_seen_in_batch(self):
        db = MagicMock()
        expected_hash = calculate_simhash("T1 결승 진출본문")
        content_hash, recent_news, should_skip = prepare_news_ingest_record(
            db,
            title="T1 결승 진출",
            content="본문",
            published_at=datetime.now(timezone.utc),
            recent_window_hours=48,
            seen_in_batch={expected_hash},
        )
        self.assertTrue(should_skip)
        self.assertEqual(recent_news, [])
        self.assertEqual(content_hash, expected_hash)
        db.query.assert_not_called()

    def test_persist_news_record_adds_model(self):
        db = MagicMock()
        db.add = MagicMock()

        class _DummyNews:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        record = persist_news_record(
            db,
            model_cls=_DummyNews,
            content_hash="hash",
            game_tag="LoL",
            category_tag="Esports",
            source_name="Naver",
            title="title",
            url="url",
            full_content="content",
            published_at=datetime.now(timezone.utc),
        )
        self.assertEqual(record.kwargs["title"], "title")
        db.add.assert_called_once()

if __name__ == '__main__':
    unittest.main()
