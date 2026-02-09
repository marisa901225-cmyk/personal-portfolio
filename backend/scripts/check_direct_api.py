import requests
import json

def test_api():
    url = "http://127.0.0.1:8080/v1/chat/completions"
    payload = {
        "model": "model",
        "messages": [{"role": "user", "content": "안녕, 스팸인지 판단해줘: [광고] 지금 가입하면 포인트 10000점!"}],
        "max_tokens": 10
    }
    try:
        r = requests.post(url, json=payload)
        print(f"Status: {r.status_code}")
        print(f"Response: {r.text}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_api()
