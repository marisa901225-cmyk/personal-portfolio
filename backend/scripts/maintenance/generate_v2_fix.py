import requests
import json
import os

def generate_templates():
    url = "http://localhost:8080/v1/chat/completions"
    
    # 프롬프트 로드 (임시로 하드코딩 또는 파일 읽기)
    with open("backend/prompts/generate_catchphrases.txt", "r", encoding="utf-8") as f:
        prompt_template = f.read()

    results = {"LoL": [], "Valorant": []}
    
    for game in ["리그 오브 레전드", "발로란트"]:
        prompt = prompt_template.replace("{{game}}", game)
        payload = {
            "model": "EXAONE-4.0-1.2B-BF16",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 512,
            "temperature": 0.8
        }
        
        print(f"Generating for {game}...")
        response = requests.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        
        lines = [line.strip().lstrip("-*•123456789. ").strip() for line in content.split("\n") if line.strip()]
        key = "LoL" if "리그" in game else "Valorant"
        results[key] = lines[:10]

    # 저장 (sudo가 필요할 수 있음)
    save_path = "backend/data/esports_catchphrases_v2.json"
    print(f"Saving to {save_path}...")
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("Done!")

if __name__ == "__main__":
    generate_templates()
