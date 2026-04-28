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

    def test_clean_exaone_tokens_keeps_decimal_paragraphs(self):
        text = (
            "시장 흐름을 생각해 보면 오늘은 급하게 낙관할 날은 아니야.\n\n"
            "17.48라는 숫자는 VIX가 완전 안심 구간은 아니라는 뜻이지.\n\n"
            "파생 쪽 숫자도 같이 봐야 해."
        )
        self.assertEqual(clean_exaone_tokens(text), text)

    def test_clean_exaone_tokens_still_trims_meta_before_numbered_list(self):
        text = "사용자가 원하는 형식으로 정리해 보면 이렇다.\n1. 첫째 줄\n2. 둘째 줄"
        self.assertEqual(clean_exaone_tokens(text), "1. 첫째 줄\n2. 둘째 줄")

if __name__ == "__main__":
    unittest.main()
