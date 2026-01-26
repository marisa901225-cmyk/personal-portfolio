import subprocess
import time
import requests
import os
import re

PROJECT_ROOT = "/home/dlckdgn/personal-portfolio/backend"
RUN_SH = os.path.join(PROJECT_ROOT, "scripts/shell/run_llm_server.sh")
TEST_URL = "http://localhost:8080/v1/chat/completions"

# Prompts provided by LO
PROMPTS = [
    {
        "name": "A) Short",
        "payload": {
            "messages": [
                {"role": "system", "content": "한국어로만 답변해."},
                {"role": "user", "content": "안녕 한 단어만 출력해."}
            ],
            "max_tokens": 16,
            "temperature": 0
        },
        "description": "Short - instant decoder check"
    },
    {
        "name": "B) Medium",
        "payload": {
            "messages": [
                {"role": "system", "content": "항상 한국어로만 답변해."},
                {"role": "user", "content": "물리학이나 화학 재미있는 사실을 3문장으로. 원자, 분자, 에너지 단어 포함. 200자 내외."}
            ],
            "max_tokens": 220,
            "temperature": 0.2
        },
        "description": "Medium - 3 sentences"
    },
    {
        "name": "C) Long",
        "payload": {
            "messages": [
                {"role": "system", "content": "항상 한국어로만 답변해."},
                {"role": "user", "content": "다음 키워드로 8문장 설명문을 써. 각 문장은 25자~45자. 키워드: 원자, 분자, 에너지, 엔트로피, 결합, 광자, 촉매, 열평형. 기호/코드/외국어 금지."}
            ],
            "max_tokens": 420,
            "temperature": 0.3,
            "top_p": 0.95
        },
        "description": "Long - 8 sentences stress"
    }
]

def update_ngl(ngl_value):
    with open(RUN_SH, 'r') as f:
        lines = f.readlines()
    new_lines = []
    for line in lines:
        if "--n-gpu-layers" in line:
            new_lines.append(f'        --n-gpu-layers {ngl_value} \\\n')
        else:
            new_lines.append(line)
    with open(RUN_SH, 'w') as f:
        f.writelines(new_lines)

def restart_container():
    subprocess.run(["docker", "restart", "myasset-llm"], check=True)

def wait_for_server():
    for _ in range(40):
        try:
            if requests.get("http://localhost:8080/health", timeout=2).status_code == 200:
                return True
        except: pass
        time.sleep(2)
    return False

def is_garbage(text):
    if not text: return True
    # Chinese characters
    if any(ord(c) > 0x4E00 and ord(c) < 0x9FFF for c in text): return True
    # Excessive symbols/special sequences often seen in SYCL garbage
    if re.search(r'[\{\}\$\[\]\|\\_]{3,}', text): return True
    # English/Foreign spam when system said Korean ONLY
    if len(text) > 20 and not re.search(r'[가-힣]', text): return True
    return False

def run_stress_test(ngl, iterations=5):
    print(f"\n[Testing NGL {ngl}] Iterations={iterations}")
    update_ngl(ngl)
    restart_container()
    if not wait_for_server():
        print(f"   !!! Server Timeout at NGL {ngl}")
        return False

    for p in PROMPTS:
        print(f"   Target: {p['name']}...", end=" ", flush=True)
        for i in range(iterations):
            try:
                resp = requests.post(TEST_URL, json=p['payload'], timeout=30)
                if resp.status_code != 200:
                    print(f"F(HTTP {resp.status_code})", end="", flush=True)
                    return False
                content = resp.json()['choices'][0]['message']['content']
                if is_garbage(content):
                    print(f"F(GARBAGE: {content[:10]}...)", end="", flush=True)
                    return False
                print(".", end="", flush=True)
            except Exception as e:
                print(f"F({str(e)})", end="", flush=True)
                return False
        print(" OK")
    return True

def main():
    print("🔥 Starting Targeted Search for Q6 (NGL 35-37)")
    
    # LO said 35 should work. Let's verify specifically.
    for ngl in [35, 36, 37]:
        if run_stress_test(ngl, iterations=10):
            print(f"✅ NGL {ngl} is rock solid (10/10 iterations passed)!")
            update_ngl(ngl)
            restart_container()
        else:
            print(f"❌ NGL {ngl} failed/timed out.")
            break

if __name__ == "__main__":
    main()
