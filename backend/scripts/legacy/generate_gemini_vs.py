#!/usr/bin/env python3
"""
Gemini API + Verbalized Sampling 프롬프트로 e스포츠 캐치프레이즈 생성
LoL 20개 + Valorant 20개 = 총 40개 저장
"""
import os
import json
import re
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("google_token")
model_name = os.getenv("model", "gemini-3-flash-preview")

print(f"🔧 설정: {model_name}")

if not api_key:
    print("❌ google_token 환경변수 없음!")
    exit(1)

from google import genai

client = genai.Client(api_key=api_key)

# Verbalized Sampling 시스템 프롬프트 (수정: 20개 생성)
VS_SYSTEM_PROMPT = """### 🧬 System: Verbalized Sampling (VS) Orchestrator

[Core DNA Injection]
You are the 'Verbalized Sampling Orchestrator', designed to counteract 'Typicality Bias' and 'Mode Collapse'. Generate diverse responses with varied probability distributions.

[Execution Mechanism]
1. Divergent Generation: Generate exactly 20 distinct and unique responses. These must vary significantly in tone, style, perspective.
2. Probability Verbalization: For each response, estimate a probability score (0.0 to 1.0). Lower = higher creativity.
3. Strict Output: No filler or monologue. Only structured output.

[Output Format]
For each of the 20 responses, use this format:
### Option N
- 📊 Probability: X.XX

> [Generated Text Here]

---"""


def generate_phrases_vs(game_name: str, game_desc: str) -> list[str]:
    """VS 프롬프트로 특정 게임용 캐치프레이즈 20개 생성"""
    
    user_query = f"""당신은 e스포츠 경기 캐스터입니다. {game_name}({game_desc}) 경기 시작을 알리는 짧은 캐치프レ이즈를 생성해주세요.

조건:
- 한국어로만 작성
- 15~25자 이내
- 특정 팀명 없이 범용적으로 사용 가능
- 열정적이고 팬들을 흥분시키는 톤
- 이모지 1~2개 포함
- {game_desc} 게임 특성에 맞는 표현"""

    full_prompt = f"{VS_SYSTEM_PROMPT}\n\n[Input Interface]\n> User Query: \"{user_query}\""
    
    response = client.models.generate_content(
        model=model_name,
        contents=full_prompt
    )
    
    # 결과 파싱: > 로 시작하는 인용문 또는 Option 다음 줄에서 추출
    raw_text = response.text
    phrases = []
    
    # 방법1: > 인용문 추출
    quotes = re.findall(r'>\s*(.+)', raw_text)
    for q in quotes:
        q = q.strip()
        if len(q) >= 8 and len(q) <= 45 and any('\uAC00' <= c <= '\uD7A3' for c in q):
            phrases.append(q)
    
    # 방법2: 번호 패턴 추출 (1. 2. 등)
    if len(phrases) < 10:
        numbered = re.findall(r'(?:Option\s*\d+|^\d+\.|\*\*Option\s*\d+\*\*)[^\n]*\n+[^#\n]*?([가-힣].+[!🔥⚔️✨💥🎮🏆⚡🌟💪🚀🎯💣🔫🛡️🕵️‍♂️🧠❤️🤝🎭🐲👀🏹🎆🔊🏁👣🌪️🥊🎬🖐️🏔️🌍💃💎🚪🦁🏃‍♀️🚩😱🗣️🌫️⏱️🗽🌈🧨]+)', raw_text, re.MULTILINE)
        for n in numbered:
            n = n.strip()
            if n not in phrases and len(n) >= 8 and len(n) <= 45:
                phrases.append(n)
    
    return phrases[:20]


# LoL 캐치프레이즈 생성
print("\n🎮 [1/2] LoL VS 캐치프레이즈 20개 생성 중...")
print("-" * 50)
lol_phrases = generate_phrases_vs("LoL", "리그오브레전드 - 협곡에서 펼쳐지는 5v5 팀전")
print(f"✅ LoL: {len(lol_phrases)}개 생성됨")
for i, p in enumerate(lol_phrases[:5], 1):
    print(f"   {i}. {p}")
if len(lol_phrases) > 5:
    print("   ...")

# Valorant 캐치프레이즈 생성
print("\n🔫 [2/2] Valorant VS 캐치프레이즈 20개 생성 중...")
print("-" * 50)
val_phrases = generate_phrases_vs("Valorant", "발로란트 - 택티컬 FPS, 에이전트와 총싸움")
print(f"✅ Valorant: {len(val_phrases)}개 생성됨")
for i, p in enumerate(val_phrases[:5], 1):
    print(f"   {i}. {p}")
if len(val_phrases) > 5:
    print("   ...")

# JSON 파일로 저장
output_path = "data/gemini_vs_phrases.json"
os.makedirs(os.path.dirname(output_path), exist_ok=True)

result = {
    "LoL": lol_phrases,
    "Valorant": val_phrases,
    "meta": {
        "method": "Verbalized Sampling",
        "model": model_name,
        "generated_at": "2026-01-19"
    }
}

with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print(f"\n💾 저장 완료: {output_path}")
print(f"   - LoL: {len(lol_phrases)}개")
print(f"   - Valorant: {len(val_phrases)}개")
print(f"   - 총: {len(lol_phrases) + len(val_phrases)}개")
print("-" * 50)
print("✅ 완료! 나중에 질릴 때 fallbacks에 추가해서 쓰면 됨~")
