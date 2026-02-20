
import requests
import json
import time
import subprocess
import re

URL = "http://127.0.0.1:8080/v1/chat/completions"

def get_temp():
    try:
        res = subprocess.check_output(["sensors"], text=True)
        # xe-pci-0300 섹션에서 vram 또는 pkg 온도 추출 시도
        lines = res.split('\n')
        is_xe = False
        temps = {}
        for line in lines:
            if "xe-pci-0300" in line:
                is_xe = True
            if is_xe:
                if "pkg:" in line:
                    m = re.search(r"\+(\d+\.?\d*)°C", line)
                    if m: temps['GPU_PKG'] = m.group(1)
                if "vram:" in line:
                    m = re.search(r"\+(\d+\.?\d*)°C", line)
                    if m: temps['GPU_VRAM'] = m.group(1)
                if line.strip() == "":
                    is_xe = False
        return temps
    except:
        return {}

prompts = [
    ("Steam Trend", "현재 스팀에서 가장 인기 있는 게임 트렌드와 사용자들의 평가 경향에 대해 분석해줘.")
]

for cat, p in prompts:
    print(f"--- Running {cat} ---")
    
    initial_temp = get_temp()
    print(f"Initial Temp: {initial_temp}")

    payload = {
        "messages": [{"role": "user", "content": p}],
        "temperature": 0.7,
        "max_tokens": 1000,
        "stream": False
    }
    
    start = time.time()
    try:
        resp = requests.post(URL, json=payload, timeout=600)
        end = time.time()
        
        if resp.status_code == 200:
            content = resp.json()['choices'][0]['message']['content']
            after_temp = get_temp()
            print(f"\n[Response]\n{content}\n")
            print(f"--- Stats ---")
            print(f"Time: {end-start:.2f}s")
            print(f"After Temp: {after_temp}")
        else:
            print(f"Error: {resp.status_code}")
    except Exception as e:
        print(f"Exception: {e}")
