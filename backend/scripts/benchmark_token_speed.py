import requests
import time
import json

TEST_URL = "http://localhost:8080/v1/chat/completions"

# Medium prompt from stress test
MEDIUM_PROMPT = {
    "messages": [
        {"role": "system", "content": "항상 한국어로만 답변해."},
        {"role": "user", "content": "물리학이나 화학 재미있는 사실을 3문장으로. 원자, 분자, 에너지 단어 포함. 200자 내외."}
    ],
    "max_tokens": 220,
    "temperature": 0.2,
    "stream": False
}

print("🔥 Testing token generation speed (NGL 37, Q6_K)")
print("=" * 60)

for i in range(5):
    print(f"\n[Test {i+1}/5]")
    start = time.time()
    
    try:
        resp = requests.post(TEST_URL, json=MEDIUM_PROMPT, timeout=30)
        elapsed = time.time() - start
        
        if resp.status_code == 200:
            data = resp.json()
            content = data['choices'][0]['message']['content']
            usage = data.get('usage', {})
            
            completion_tokens = usage.get('completion_tokens', 0)
            tokens_per_sec = completion_tokens / elapsed if elapsed > 0 else 0
            
            print(f"✅ Success")
            print(f"   Time: {elapsed:.2f}s")
            print(f"   Tokens: {completion_tokens}")
            print(f"   Speed: {tokens_per_sec:.2f} tokens/sec")
            print(f"   Response: {content[:80]}...")
        else:
            print(f"❌ HTTP {resp.status_code}")
    except Exception as e:
        print(f"❌ Error: {e}")

print("\n" + "=" * 60)
