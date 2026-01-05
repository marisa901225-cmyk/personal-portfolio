
import os
import httpx
import json

API_KEY = "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"
BASE_URL = "https://api.openai.com/v1"
MODEL = "gpt-5.2"

def test_ai():
    print(f"Testing OpenAI API with model: {MODEL}")
    try:
        response = httpx.post(
            f"{BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": MODEL,
                "messages": [{"role": "user", "content": "Hello"}],
                "max_completion_tokens": 10
            },
            timeout=10.0
        )
        print(f"Status Code: {response.status_code}")
        print("Response Body:")
        print(response.text)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_ai()
