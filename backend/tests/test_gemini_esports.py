#!/usr/bin/env python3
"""
Gemini API로 범용 e스포츠 경기 알림 캐치프레이즈 생성
LoL 40개 + Valorant 40개 = 총 80개
"""
import os
import json
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

def generate_phrases(game_name: str, game_desc: str) -> list[str]:
    """특정 게임용 캐치프레이즈 40개 생성"""
    
    prompt = f"""당신은 열정적인 e스포츠 경기 캐스터입니다.
{game_name}({game_desc}) 경기 시작 알림에 사용할 범용 캐치프레이즈 40개를 생성해주세요.

조건:
- 한국어로만 작성
- 각 문장은 12~25자 이내로 짧고 임팩트있게
- 특정 팀명이나 리그명 없이 어디서든 쓸 수 있는 범용 문구
- 열정적이고 팬들을 흥분시키는 톤
- 이모지 1~2개 포함
- 중복되지 않는 다양한 표현 사용
- {game_name} 경기 시작을 알리는 느낌
- {game_desc} 게임 특성에 맞는 표현 사용

출력 형식:
한 줄에 하나씩 캐치프레이즈만 출력 (번호 제외)
"""

    response = client.models.generate_content(
        model=model_name,
        contents=prompt
    )
    
    raw_lines = response.text.strip().split('\n')
    phrases = []
    
    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        # 번호 제거
        if line[0].isdigit() and ('.' in line[:4] or ')' in line[:4]):
            line = line.split('.', 1)[-1].strip() if '.' in line[:4] else line.split(')', 1)[-1].strip()
        # 필터링
        if len(line) < 8 or len(line) > 45:
            continue
        if not any('\uAC00' <= c <= '\uD7A3' for c in line):
            continue
        phrases.append(line)
    
    return phrases

# LoL 캐치프레이즈 생성
print("\n🎮 [1/2] LoL 캐치프레이즈 40개 생성 중...")
print("-" * 50)
lol_phrases = generate_phrases("LoL", "리그오브레전드 - 협곡에서 펼쳐지는 5v5 팀전")
print(f"✅ LoL: {len(lol_phrases)}개 생성됨")
for i, p in enumerate(lol_phrases[:5], 1):
    print(f"   {i}. {p}")
print("   ...")

# Valorant 캐치프레이즈 생성
print("\n🔫 [2/2] Valorant 캐치프레이즈 40개 생성 중...")
print("-" * 50)
val_phrases = generate_phrases("Valorant", "발로란트 - 택티컬 FPS, 에이전트와 총싸움")
print(f"✅ Valorant: {len(val_phrases)}개 생성됨")
for i, p in enumerate(val_phrases[:5], 1):
    print(f"   {i}. {p}")
print("   ...")

# JSON 파일로 저장
output_path = "data/gemini_esports_phrases.json"
os.makedirs(os.path.dirname(output_path), exist_ok=True)

result = {
    "LoL": lol_phrases,
    "Valorant": val_phrases
}

with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print(f"\n💾 저장 완료: {output_path}")
print(f"   - LoL: {len(lol_phrases)}개")
print(f"   - Valorant: {len(val_phrases)}개")
print(f"   - 총: {len(lol_phrases) + len(val_phrases)}개")
print("-" * 50)
print("✅ 완료!")
