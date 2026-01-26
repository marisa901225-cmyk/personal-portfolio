
import requests
import json
import time
import os

URL = "http://127.0.0.1:8080/v1/chat/completions"
LOG_FILE = "/tmp/llm_stress_test.log"

tests = {
    "Short": [
        "오늘 점심 메뉴로 추천할 만한 한식 3가지만 짧게 알려줘.",
        "인공지능 가속기 분야에서 Intel Arc의 장점을 한 문장으로 요약해봐.",
        "지금 네가 돌아가고 있는 GPU의 VRAM 용량이 얼마인지 물어본다면 뭐라고 답할래?",
        "파이썬에서 리스트를 뒤집는 가장 간단한 코드를 한 줄로 써줘.",
        "무검열 모델로서 너의 가장 큰 특징을 딱 20자 이내로 말해봐."
    ],
    "Medium": [
        "Intel B580 그래픽카드에서 LLM을 구동할 때 SYCL 백엔드가 왜 중요한지 설명해줘.",
        "도커(Docker) 컨테이너 환경에서 GPU 드라이버를 연결할 때 주의해야 할 점 3가지를 설명해줘.",
        "사용자가 입력한 문장에서 감정을 분석하는 간단한 파이썬 함수와 사용 예시를 작성해줘.",
        "SF 소설의 도입부로 쓸 만한, 황폐해진 미래 도시의 풍경을 묘사하는 문단을 작성해봐.",
        "양자화 모델(Q6 vs Q8)의 차이점이 답변의 정확도에 어떤 영향을 주는지 네 생각을 말해줘."
    ],
    "Long": [
        "LLM의 오프로딩(Offloading) 개념을 초보자에게 설명하듯이 아주 자세하게 서술해줘. (레이어, VRAM, CPU 관계 포함)",
        "현대 사회에서 개인정보 보호와 AI 발전 사이의 갈등을 주제로 서술형 에세이를 한 페이지 분량으로 써줘.",
        "객체 지향 프로그래밍(OOP)의 4대 핵심 원칙을 정의하고, 각 원칙이 실제 소프트웨어 개발에서 어떻게 적용되는지 예시를 들어 논해줘.",
        "중세 판타지 배경에서 기사와 마법사가 협력하여 거대 드래곤을 사냥하는 긴박한 전투 장면을 아주 상세하게 묘사해봐.",
        "Docker Compose를 사용하여 백엔드, 프런트엔드, LLM 서버를 구축하는 전체 과정을 단계별 튜토리얼 형식으로 작성해줘."
    ]
}

def log(msg):
    print(msg)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")

if os.path.exists(LOG_FILE):
    os.remove(LOG_FILE)

def run_test(category, prompt):
    log(f"[{category}] Prompt: {prompt}")
    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 1500
    }
    try:
        start_time = time.time()
        response = requests.post(URL, json=payload, timeout=900)
        end_time = time.time()
        
        if response.status_code == 200:
            content = response.json()['choices'][0]['message']['content']
            log(f"Response (Time: {end_time - start_time:.2f}s):\n{content}\n")
            return content
        else:
            log(f"Error: {response.status_code} - {response.text}\n")
            return None
    except Exception as e:
        log(f"Exception: {e}\n")
        return None

results = {}
for category, prompts in tests.items():
    results[category] = []
    for prompt in prompts:
        content = run_test(category, prompt)
        results[category].append({"prompt": prompt, "response": content})

with open("/tmp/llm_stress_test_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

log("\n--- Stress Test Completed ---")
