import unittest

from backend.services.alarm.filters import is_review_spam, is_whitelisted


class AlarmFilterTests(unittest.TestCase):
    def test_aliexpress_coin_promo_is_not_delivery_whitelisted(self):
        text = "[AliExpress] ₩ 303 상당 코인 20개가 기다리고 있어요!"

        self.assertFalse(is_whitelisted(text))
        self.assertTrue(is_review_spam(text))

    def test_aliexpress_delivery_notice_stays_whitelisted(self):
        text = "[AliExpress] 주문 상품이 배송 중입니다"

        self.assertTrue(is_whitelisted(text))
        self.assertFalse(is_review_spam(text))


if __name__ == "__main__":
    unittest.main()
