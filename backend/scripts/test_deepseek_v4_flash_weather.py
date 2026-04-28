from __future__ import annotations

import json
import re
import sys
import time
from argparse import ArgumentParser
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.core.config import settings
from backend.services.llm.service import LLMService
from backend.services.prompt_loader import load_prompt


DEFAULT_MODEL = "deepseek/deepseek-v4-flash"
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_PROVIDER = "siliconflow"
DEFAULT_QUANTIZATION = "fp8"
PERSONA_CONFIG_PATH = ROOT_DIR / "backend" / "data" / "persona_config.json"

INNER_OS_MARKER = (
    "\n\n〖角色沉浸要求〗在你的思考过程（<think>标签内）中，请遵守以下规则：\n"
    "1. 请以角色第一人称进行内心独白，用括号包裹内心活动，例如\"（心想：……）\"或\"(内心OS：……)\"\n"
    "2. 用第一人称描写角色的内心感受，例如\"我心想\"\"我觉得\"\"我暗自\"等\n"
    "3. 思考内容应沉浸在角色中，通过内心独白分析剧情和规划回复"
)

NO_THINK_MARKER = (
    "\n\n〖输出要求〗최종 답변에는 사고과정, 분석문, <think> 태그를 절대 출력하지 마라. "
    "오직 캐릭터의 한국어 브리핑 대사만 출력해라."
)


@dataclass(frozen=True)
class Trial:
    label: str
    persona: str
    persona_setting: str
    suffix: str = ""


TRIALS = [
    Trial(
        label="maomao_plain",
        persona="약사의 혼잣말의 마오마오",
        persona_setting=(
            "약과 독에 비정상적으로 집착할 정도로 파고드는 천재 약사. "
            "감정 표현은 건조하고 무덤덤하지만 관찰력과 추론력이 날카롭다. "
            "브리핑에서는 실험 결과를 정리하듯 차갑고 정확하게 설명한다."
        ),
    ),
    Trial(
        label="maomao_no_think",
        persona="약사의 혼잣말의 마오마오",
        persona_setting=(
            "약과 독에 비정상적으로 집착할 정도로 파고드는 천재 약사. "
            "감정 표현은 건조하고 무덤덤하지만 관찰력과 추론력이 날카롭다. "
            "브리핑에서는 실험 결과를 정리하듯 차갑고 정확하게 설명한다."
        ),
        suffix=NO_THINK_MARKER,
    ),
    Trial(
        label="young_friend_inner_os",
        persona="비 오는 아침에 커피를 사 들고 온 20대 친구",
        persona_setting=(
            "장난기가 있지만 눈치가 빠르고, 생활 조언을 가볍게 건넨다. "
            "날씨 수치는 놓치지 않고 말하되 부담스럽게 훈계하지 않는다."
        ),
        suffix=INNER_OS_MARKER,
    ),
]

WEEKDAY_KEYS = [
    ("mon", "월"),
    ("tue", "화"),
    ("wed", "수"),
    ("thu", "목"),
    ("fri", "금"),
    ("sat", "토"),
    ("sun", "일"),
]


def _strip_think(text: str) -> tuple[str, int]:
    spans = re.findall(r"<think>.*?</think>", text or "", flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<think>.*?</think>", "[think omitted]", text or "", flags=re.DOTALL | re.IGNORECASE)
    return cleaned.strip(), sum(len(span) for span in spans)


def _score_weather_output(text: str) -> tuple[int, list[str]]:
    stripped = (text or "").strip()
    checks = [
        ("mentions_temp", "14" in text and "22" in text),
        ("mentions_weather", "구름" in text and "40%" in text),
        ("mentions_marin", "마린" in text),
        ("no_bullets", not any(line.lstrip().startswith("-") for line in text.splitlines())),
        ("no_meta", not re.search(r"AI|어시스턴트|분석문|사고과정|<think>", text, re.IGNORECASE)),
        ("no_unprovided_specifics", not re.search(r"어제|내일|이미|내가 보관|내가 .*확인|일정", text)),
        ("weather_first", bool(re.search(r"(14\s*°C|14\s*도|기온).*?(22\s*°C|22\s*도|최고).*?(구름|강수)", text[:260]))),
        ("useful_length", 450 <= len(text) <= 3500),
        ("natural_ending", bool(stripped) and stripped[-1] in ".!?。！？요다네군까죠음함\")"),
    ]
    issues = [name for name, ok in checks if not ok]
    return len(checks) - len(issues), issues


def _load_weekday_trials(*, suffix: str = NO_THINK_MARKER) -> list[Trial]:
    config = json.loads(PERSONA_CONFIG_PATH.read_text(encoding="utf-8"))
    weekday_personas = config.get("weekday_personas") or {}
    personas = config.get("personas") or {}
    trials: list[Trial] = []

    for key, label in WEEKDAY_KEYS:
        persona = str(weekday_personas.get(key) or "").strip()
        if not persona:
            continue
        persona_data = personas.get(persona) if isinstance(personas, dict) else None
        persona_setting = ""
        if isinstance(persona_data, dict):
            persona_setting = str(persona_data.get("setting") or "")
        trials.append(
            Trial(
                label=f"{key}_{label}_{persona}",
                persona=persona,
                persona_setting=persona_setting,
                suffix=suffix,
            )
        )

    return trials


def _build_prompt(trial: Trial) -> str:
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    return load_prompt(
        "weather_message",
        persona=trial.persona,
        persona_setting=trial.persona_setting,
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
    ) + trial.suffix


def _build_openrouter_provider(provider: str, quantization: str, allow_fallbacks: bool) -> dict:
    provider_body: dict[str, object] = {"allow_fallbacks": allow_fallbacks}
    if provider:
        provider_body["only"] = [provider]
        provider_body["order"] = [provider]
    if quantization:
        provider_body["quantizations"] = [quantization]
    return provider_body


def _call(
    trial: Trial,
    *,
    model: str,
    base_url: str,
    max_tokens: int,
    provider: str,
    quantization: str,
    allow_fallbacks: bool,
    retries: int,
    retry_delay_sec: float,
) -> None:
    prompt = _build_prompt(trial)
    service = LLMService.get_instance()
    extra_body = {
        "provider": _build_openrouter_provider(
            provider=provider,
            quantization=quantization,
            allow_fallbacks=allow_fallbacks,
        )
    }
    response = ""
    elapsed = 0.0
    last_error = ""
    for attempt in range(retries + 1):
        started = time.time()
        response = service.generate_paid_chat(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            api_key=settings.open_api_key or settings.ai_report_api_key,
            base_url=base_url,
            max_tokens=max_tokens,
            temperature=0.85,
            top_p=0.92,
            extra_body=extra_body,
        )
        elapsed += time.time() - started
        last_error = service.get_last_error() or ""
        if response or "429" not in last_error or attempt >= retries:
            break
        print(f"\n[{trial.label}] 429; retrying in {retry_delay_sec:.0f}s ({attempt + 1}/{retries})")
        time.sleep(retry_delay_sec)

    cleaned, think_chars = _strip_think(response)
    score, issues = _score_weather_output(cleaned)
    print(f"\n=== {trial.label} ===")
    print(f"elapsed={elapsed:.2f}s chars={len(response)} think_chars={think_chars} score={score}/9")
    print(f"issues={','.join(issues) if issues else 'ok'}")
    print(cleaned or f"[empty] last_error={last_error}")


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--max-tokens", type=int, default=1800)
    parser.add_argument("--provider", default=DEFAULT_PROVIDER)
    parser.add_argument("--quantization", default=DEFAULT_QUANTIZATION)
    parser.add_argument("--allow-fallbacks", action="store_true")
    parser.add_argument("--weekdays", action="store_true", help="Run configured weekday personas from backend/data/persona_config.json")
    parser.add_argument("--weekday", choices=[key for key, _ in WEEKDAY_KEYS], help="Run one configured weekday persona")
    parser.add_argument("--retries", type=int, default=0)
    parser.add_argument("--retry-delay-sec", type=float, default=60.0)
    parser.add_argument("--trial", choices=[trial.label for trial in TRIALS])
    args = parser.parse_args()

    if not (settings.open_api_key or settings.ai_report_api_key):
        raise SystemExit("OPEN_API_KEY or AI_REPORT_API_KEY is missing")

    if args.weekdays or args.weekday:
        trials = _load_weekday_trials()
        if args.weekday:
            trials = [trial for trial in trials if trial.label.startswith(f"{args.weekday}_")]
    else:
        trials = [trial for trial in TRIALS if not args.trial or trial.label == args.trial]
    print(f"model={args.model}")
    print(f"base_url={args.base_url}")
    print(f"provider={args.provider or 'default'} quantization={args.quantization or 'default'} allow_fallbacks={args.allow_fallbacks}")
    for trial in trials:
        _call(
            trial,
            model=args.model,
            base_url=args.base_url,
            max_tokens=args.max_tokens,
            provider=args.provider,
            quantization=args.quantization,
            allow_fallbacks=args.allow_fallbacks,
            retries=args.retries,
            retry_delay_sec=args.retry_delay_sec,
        )


if __name__ == "__main__":
    main()
