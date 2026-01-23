import requests
import json

def test_samples():
    url = "http://127.0.0.1:8080/v1/chat/completions"
    samples = [
        "내일이면 소멸되는 포인트 5,000점이 있어요! 지금 바로 확인하세요.",
        "[대한통운] 고객님의 소중한 상품이 오늘 배송 완료되었습니다.",
        "KB카드 승인: 12,500원 일시불 결제 완료.",
        "이번주 한정 특가! 최신형 건조기 반값 할인 찬스!",
        "오늘의 증시 리포트: 반도체 섹터 강세 지속 전망",
        "이벤트 당첨을 축하드려요! 아래 링크를 클릭해서 선물을 받으세요."
    ]
    
    print("--- 8B AI Spam Filter Direct API Test ---")
    for text in samples:
        payload = {
            "model": "model",
            "messages": [
                {
                    "role": "user", 
                    "content": f"스팸인지 판단해줘. 'spam' 또는 'ham' 중 하나만 출력해.\n내용: {text}"
                }
            ],
            "max_tokens": 10
        }
        try:
            r = requests.post(url, json=payload)
            res = r.json()["choices"][0]["message"]["content"].strip().lower()
            print(f"Result: {res} | Text: {text[:40]}...")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    test_samples()
