import unittest
from backend.services.alarm.sanitizer import clean_exaone_tokens

class TestPromptFix(unittest.TestCase):
    def test_clean_exaone_tokens_meta_talk(self):
        # Case 1: "지문을 잘 이해했어" 시작
        text1 = "지문을 잘 이해했어! 우주를 보면 지구도 작아 보이지?"
        self.assertEqual(clean_exaone_tokens(text1), "우주를 보면 지구도 작아 보이지?")
        
        # Case 2: "알겠습니다" 시작
        text2 = "알겠습니다. 과학 같으면 무조건 웃음이 날 거야."
        self.assertEqual(clean_exaone_tokens(text2), "과학 같으면 무조건 웃음이 날 거야.")
        
        # Case 3: 기존 COT 패턴과 섞인 경우
        text3 = "아하, 지문을 완벽히 이해했어. 실험해본 적 있어?"
        # "아하,"가 먼저 제거되고 그 다음 "지문을...이해했어"가 제거되어야 함
        # 현재 로직상 순차적으로 제거됨
        self.assertEqual(clean_exaone_tokens(text3), "실험해본 적 있어?")

if __name__ == "__main__":
    unittest.main()
