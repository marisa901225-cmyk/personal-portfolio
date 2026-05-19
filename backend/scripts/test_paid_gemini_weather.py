from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests


ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.services.prompt_loader import load_prompt


KST = ZoneInfo("Asia/Seoul")
DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemma-4-31b-it"
DEFAULT_ENV_PATH = Path("/home/dlckdgn/ai-models/myasset.secrets.env")


def _load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def _resolve_api_key(env_file: Path | None) -> str:
    merged = dict(os.environ)
    if env_file:
        merged = {**_load_env_file(env_file), **merged}
    for key in ("paidgemini_api", "PAIDGEMINI_API"):
        value = str(merged.get(key) or "").strip()
        if value:
            return value
    raise SystemExit("paidgemini_api is not set")


def _build_weather_prompt() -> str:
    now = datetime.now(KST)
    return load_prompt(
        "weather_message",
        persona="비 오는 아침에 커피를 사 들고 온 20대 친구",
        persona_setting=(
            "장난기가 있지만 눈치가 빠르고, 생활 조언을 가볍게 건넨다. "
            "날씨 수치는 놓치지 않고 말하되 부담스럽게 훈계하지 않는다."
        ),
        temp=14,
        today_max_temp=22,
        weather_status="구름 많음",
        pop=40,
        base_date=now.strftime("%Y%m%d"),
        base_time=now.strftime("%H%M"),
        formatted_datetime=now.strftime("%Y년 %-m월 %-d일 %H시 %M분"),
        ultra_short_data="서울은 현재 구름 많음, 기온 14°C, 낮 최고 22°C, 강수확률 40%, 습도 58%, 풍속 2.1m/s.",
        economic_data="없음",
        futures_options_data="데이터 없음",
        weekly_derivatives_briefing="데이터 없음",
        market_outlook_news="데이터 없음",
        culture_context="없음",
        dust_info="없음",
    )


def _extract_text(payload: dict) -> str:
    parts: list[str] = []
    for candidate in payload.get("candidates") or []:
        content = candidate.get("content") or {}
        for part in content.get("parts") or []:
            text = part.get("text")
            if text:
                parts.append(str(text))
    return "\n".join(parts).strip()


def _call_generate_content(*, api_key: str, model: str, prompt: str, base_url: str) -> tuple[int, dict]:
    url = f"{base_url.rstrip('/')}/models/{model}:generateContent"
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}],
            }
        ],
        "generationConfig": {
            "temperature": 0.85,
            "topP": 0.92,
            "maxOutputTokens": 4096,
        },
    }

    response = requests.post(
        url,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "x-goog-api-key": api_key,
        },
        json=payload,
        timeout=(5, 120),
    )
    try:
        data = response.json()
    except ValueError:
        data = {"raw_text": response.text}
    return response.status_code, data


def main() -> int:
    parser = argparse.ArgumentParser(description="Direct Gemini weather prompt smoke test using paidgemini_api.")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_PATH), help="Path to env file containing paidgemini_api")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Gemini model name")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Google Generative Language API base URL")
    args = parser.parse_args()

    env_file = Path(args.env_file).expanduser() if args.env_file else None
    api_key = _resolve_api_key(env_file)
    prompt = _build_weather_prompt()
    status_code, data = _call_generate_content(
        api_key=api_key,
        model=args.model,
        prompt=prompt,
        base_url=args.base_url,
    )

    print(f"status={status_code}")
    text = _extract_text(data)
    if text:
        print(text)
        return 0

    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
