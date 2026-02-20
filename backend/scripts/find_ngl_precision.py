import subprocess
import time
import requests
import os

PROJECT_ROOT = "/home/dlckdgn/personal-portfolio/backend"
RUN_SH = os.path.join(PROJECT_ROOT, "scripts/shell/run_llm_server.sh")
TEST_URL = "http://localhost:8080/v1/chat/completions"

# Test NGLs from 31 to 37
NGL_VALUES = [31, 32, 33, 34, 35, 36, 37]

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
    for _ in range(30):
        try:
            if requests.get("http://localhost:8080/health", timeout=2).status_code == 200:
                return True
        except: pass
        time.sleep(2)
    return False

def run_test():
    payload = {
        "messages": [
            {"role": "system", "content": "너는 재미있는 잡학 박사야. 한국어로만 대답해."},
            {"role": "user", "content": "신기한 사실 하나만 딱 알려줘."}
        ],
        "max_tokens": 150,
        "temperature": 0.85
    }
    try:
        resp = requests.post(TEST_URL, json=payload, timeout=15)
        if resp.status_code == 200:
            return True, resp.json()['choices'][0]['message']['content']
        return False, f"HTTP {resp.status_code}"
    except Exception as e: return False, str(e)

print("🔍 31-37 레이어 정밀 탐색 시작!")
for ngl in NGL_VALUES:
    print(f"Testing NGL {ngl}...", end=" ", flush=True)
    update_ngl(ngl)
    restart_container()
    if wait_for_server():
        success, output = run_test()
        # 중국어 유니코드 범위 체크
        is_garbage = any(ord(c) > 0x4E00 and ord(c) < 0x9FFF for c in output) or "{" in output[:10]
        if success and not is_garbage:
            print(f"✅ [SAFE] {output[:50]}...")
        else:
            print(f"❌ [BROKEN] {output[:50]}...")
    else: print("⏳ [TIMEOUT]")
