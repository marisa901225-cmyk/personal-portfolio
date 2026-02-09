import requests
import time

TEST_URL = "http://localhost:8080/v1/chat/completions"

# Long generation prompt
LONG_PROMPT = {
    "messages": [
        {"role": "system", "content": "You are a prolific writer."},
        {"role": "user", "content": "Write a very detailed history of the Roman Empire, focusing on the rise and fall, major emperors, and cultural impact. Write at least 1000 words. Keep writing until stopped."}
    ],
    "max_tokens": 1024,  # Force long generation
    "temperature": 0.8,
    "stream": False
}

print("🔥 Testing LONG generation speed (NGL 37, Q6_K)")
print("=" * 60)

for i in range(3):
    print(f"\n[Test {i+1}/3]")
    start = time.time()
    
    try:
        resp = requests.post(TEST_URL, json=LONG_PROMPT, timeout=120)  # Longer timeout
        elapsed = time.time() - start
        
        if resp.status_code == 200:
            data = resp.json()
            usage = data.get('usage', {})
            completion_tokens = usage.get('completion_tokens', 0)
            
            # Extract just a snippet to verify quality
            content = data['choices'][0]['message']['content']
            snippet = content[:50] + "..." + content[-50:]
            
            tokens_per_sec = completion_tokens / elapsed if elapsed > 0 else 0
            
            print(f"✅ Success")
            print(f"   Time: {elapsed:.2f}s")
            print(f"   Tokens: {completion_tokens}")
            print(f"   Speed: {tokens_per_sec:.2f} tokens/sec") 
        else:
            print(f"❌ HTTP {resp.status_code}")
            print(resp.text)
    except Exception as e:
        print(f"❌ Error: {e}")

print("\n" + "=" * 60)
