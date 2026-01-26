
import requests
import json
import time

URL = "http://127.0.0.1:8080/v1/chat/completions"

prompts = [
    ("Short", "오늘 점심 메뉴로 추천할 만한 한식 3가지만 짧게 알려줘."),
    ("Medium", "Intel B580 그래픽카드에서 LLM을 구동할 때 SYCL 백엔드가 왜 중요한지 설명해줘."),
    ("Long", "LLM의 오프로딩(Offloading) 개념을 초보자에게 설명하듯이 아주 자세하게 서술해줘. (레이어, VRAM, CPU 관계 포함)")
]

for cat, p in prompts:
    print(f"--- Testing {cat} ---")
    payload = {
        "messages": [{"role": "user", "content": p}],
        "temperature": 0.7,
        "max_tokens": 1000
    }
    start = time.time()
    resp = requests.post(URL, json=payload, timeout=600)
    end = time.time()
    if resp.status_code == 200:
        content = resp.json()['choices'][0]['message']['content']
        print(f"Time: {end-start:.2f}s\nContent:\n{content}\n")
    else:
        print(f"Error: {resp.status_code}\n")
