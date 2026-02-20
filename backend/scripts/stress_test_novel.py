import subprocess
import time
import requests
import os
import re

PROJECT_ROOT = "/home/dlckdgn/personal-portfolio/backend"
RUN_SH = os.path.join(PROJECT_ROOT, "scripts/shell/run_llm_server.sh")
TEST_URL = "http://localhost:8080/v1/chat/completions"

# Novel Prompt for heavy stress testing
PROMPT = {
    "name": "D) Heavy Novel",
    "payload": {
        "messages": [
            {"role": "system", "content": "너는 한국의 베스트셀러 소설가야. 항상 한국어로만 아주 매혹적이고 상세하게 답변해."},
            {"role": "user", "content": "비 오는 날, 낡은 카페에서 우연히 만난 두 남녀의 이야기를 단편 소설로 써줘. 공감각적인 묘사를 풍부하게 사용하고, 분량은 공백 포함 1500자 정도로 아주 길게 작성해줘."}
        ],
        "max_tokens": 2048,
        "temperature": 0.7,
        "top_p": 0.9
    },
    "description": "Heavy - 1500 characters story"
}

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
    print("🔄 Container restarting...", end=" ", flush=True)
    subprocess.run(["docker", "restart", "myasset-llm"], check=True)
    print("Done.")

def wait_for_server():
    print("⏳ Waiting for server...", end=" ", flush=True)
    for _ in range(60):
        try:
            if requests.get("http://localhost:8080/health", timeout=2).status_code == 200:
                print("Ready.")
                return True
        except: pass
        time.sleep(2)
    print("Timed out.")
    return False

def is_garbage(text):
    if not text: return True, "Empty text"
    # Chinese characters check
    if any(ord(c) > 0x4E00 and ord(c) < 0x9FFF for c in text):
        return True, "Chinese characters detected"
    # Excessive symbols check
    if re.search(r'[\{\}\$\[\]\|\\_]{5,}', text):
        return True, "Excessive symbols detected"
    # Lack of Korean check
    if len(text) > 100 and not re.search(r'[가-힣]', text):
        return True, "No Korean characters in long text"
    return False, ""

def run_novel_test(iterations=10):
    print(f"\n🚀 Starting Heavy Novel Stress Test (NGL 37) - {iterations} rounds")
    
    if not wait_for_server():
        return False

    for i in range(1, iterations + 1):
        print(f"   [Round {i:02d}] Generating...", end=" ", flush=True)
        start_time = time.time()
        try:
            # Increase timeout for 1500 chars
            resp = requests.post(TEST_URL, json=PROMPT['payload'], timeout=120) 
            elapsed = time.time() - start_time
            
            if resp.status_code != 200:
                print(f"FAILED (HTTP {resp.status_code})")
                return False
            
            content = resp.json()['choices'][0]['message']['content']
            length = len(content)
            
            failed, reason = is_garbage(content)
            if failed:
                print(f"FAILED (GARBAGE: {reason})")
                print(f"--- Full Content Start ---\n{content}\n--- Full Content End ---")
                return False
            
            print(f"Success! ({length} chars, {elapsed:.1f}s)")
            
        except Exception as e:
            print(f"FAILED (Error: {str(e)})")
            return False
            
    return True

def main():
    # Make sure NGL is 37
    update_ngl(37)
    restart_container()
    
    if run_novel_test(10):
        print("\n✨ ALL 10 ROUNDS PASSED! NGL 37 is truly rock solid. ✨")
    else:
        print("\n💥 Test failed during rounds.")

if __name__ == "__main__":
    main()
