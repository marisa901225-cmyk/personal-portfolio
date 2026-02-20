import unittest
from backend.services.news.core import _normalize_text, calculate_simhash, get_jaccard_similarity, is_duplicate_complex

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

if __name__ == '__main__':
    unittest.main()
