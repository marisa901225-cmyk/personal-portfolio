from __future__ import annotations

import json
import os
import re
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import requests


ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from backend.services.prompt_loader import load_prompt


@dataclass(frozen=True)
class Case:
    name: str
    description: str
    prompt: str
    max_tokens: int
    max_score: int
    scorer: Callable[[str], tuple[int, list[str]]]


def _strip_code_fence(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


def _extract_json_blob(text: str) -> str:
    cleaned = _strip_code_fence(text)
    if cleaned.startswith("{") or cleaned.startswith("["):
        return cleaned
    match = re.search(r"(\{.*\}|\[.*\])", cleaned, re.S)
    return match.group(1).strip() if match else cleaned


def _parse_json_maybe(text: str) -> Any | None:
    try:
        return json.loads(_extract_json_blob(text))
    except Exception:
        return None


def _nonempty_lines(text: str) -> list[str]:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def _sentence_count(text: str) -> int:
    pieces = re.split(r"(?<=[.!?…])\s+|(?<=[.!?…])$", (text or "").strip())
    return len([piece for piece in pieces if piece.strip()])


def _has_english_meta(text: str) -> bool:
    lowered = (text or "").lower()
    patterns = (
        "okay",
        "let's",
        "i need to",
        "here's",
        "setting:",
        "story:",
    )
    return any(pattern in lowered for pattern in patterns)


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[가-힣A-Za-z0-9]+", text or "")


def _unique_ratio(text: str) -> float:
    tokens = _tokenize(text)
    if not tokens:
        return 0.0
    return len(set(tokens)) / len(tokens)


def _build_cases() -> list[Case]:
    def microfiction_scorer(text: str) -> tuple[int, list[str]]:
        score = 0
        issues: list[str] = []
        sentences = _sentence_count(text)
        if sentences == 3:
            score += 2
        else:
            issues.append(f"sentence_count={sentences}")
        checks = [
            ("contains_vhs", "VHS" in text or "브이एच에스" in text),
            ("contains_npc", "NPC" in text),
            ("contains_라면", "라면" in text),
            ("contains_편의점", "편의점" in text),
            ("no_english_meta", not _has_english_meta(text)),
            ("char_len", 110 <= len((text or "").replace(" ", "")) <= 340),
            ("lexical_variety", _unique_ratio(text) >= 0.72),
        ]
        for issue, ok in checks:
            if ok:
                score += 1
            else:
                issues.append(issue)
        return score, issues

    def setting_json_scorer(text: str) -> tuple[int, list[str]]:
        parsed = _parse_json_maybe(text)
        score = 0
        issues: list[str] = []
        required_keys = [
            "title",
            "core_rule",
            "faction_a",
            "faction_b",
            "taboo",
            "daily_object",
            "story_hook",
        ]
        if isinstance(parsed, dict):
            score += 1
        else:
            issues.append("json_parse")
            return score, issues
        if set(parsed.keys()) == set(required_keys):
            score += 2
        else:
            issues.append("keys")
        text_blob = json.dumps(parsed, ensure_ascii=False)
        checks = [
            ("contains_비", "비" in text_blob),
            ("contains_영수증", "영수증" in text_blob),
            ("contains_금기", "금기" in text_blob or "금지" in text_blob),
            ("hook_length", len(str(parsed.get("story_hook", ""))) >= 22),
            ("title_length", 6 <= len(str(parsed.get("title", ""))) <= 24),
            ("factions_distinct", parsed.get("faction_a") != parsed.get("faction_b")),
        ]
        for issue, ok in checks:
            if ok:
                score += 1
            else:
                issues.append(issue)
        return score, issues

    def dialogue_scorer(text: str) -> tuple[int, list[str]]:
        lines = _nonempty_lines(text)
        score = 0
        issues: list[str] = []
        if len(lines) == 8:
            score += 2
        else:
            issues.append(f"line_count={len(lines)}")
        alternating = True
        for idx, line in enumerate(lines):
            prefix = "A:" if idx % 2 == 0 else "B:"
            if not line.startswith(prefix):
                alternating = False
                break
        if alternating:
            score += 2
        else:
            issues.append("alternating_format")
        checks = [
            ("contains_옥상", "옥상" in text),
            ("contains_자동판매기", "자동판매기" in text),
            ("contains_우산", "우산" in text),
            ("contains_빚", "빚" in text),
            ("contains_고백", "고백" in text),
            ("no_stage_direction", "[" not in text and "]" not in text),
        ]
        for issue, ok in checks:
            if ok:
                score += 1
            else:
                issues.append(issue)
        return score, issues

    def catchphrase_scorer(text: str) -> tuple[int, list[str]]:
        lines = _nonempty_lines(text)
        score = 0
        issues: list[str] = []
        if len(lines) == 5:
            score += 2
        else:
            issues.append(f"line_count={len(lines)}")
        if len(set(lines)) == len(lines) and lines:
            score += 1
        else:
            issues.append("duplicate_lines")
        endings = {re.sub(r".*?([가-힣A-Za-z0-9!?~]+)$", r"\1", line) for line in lines}
        if len(endings) >= 4:
            score += 1
        else:
            issues.append("ending_variety")
        checks = [
            ("all_bullets", all(line.startswith("- ") for line in lines) if lines else False),
            ("contains_관측소", "관측소" in text),
            ("contains_수면세", "수면세" in text),
            ("contains_야근", "야근" in text),
            ("char_limit", all(len(line) <= 36 for line in lines) if lines else False),
            ("variety_ratio", _unique_ratio(text) >= 0.68),
        ]
        for issue, ok in checks:
            if ok:
                score += 1
            else:
                issues.append(issue)
        return score, issues

    def weather_persona_scorer(text: str) -> tuple[int, list[str]]:
        score = 0
        issues: list[str] = []
        checks = [
            ("no_bullets", "-" not in "\n".join(_nonempty_lines(text))),
            ("mentions_temp", "14" in text and "22" in text),
            ("mentions_weather", "구름" in text and "40%" in text),
            ("mentions_market", "코스피" in text or "반도체" in text or "환율" in text),
            ("mentions_marin", "마린" in text),
            ("long_form", len(text) >= 500),
            ("no_english_meta", not _has_english_meta(text)),
        ]
        for issue, ok in checks:
            if ok:
                score += 1
            else:
                issues.append(issue)
        return score, issues

    weather_prompt = load_prompt(
        "weather_message",
        persona="약사의 혼잣말의 마오마오",
        persona_setting=(
            "약과 독에 비정상적으로 집착할 정도로 파고드는 천재 약사. "
            "감정 표현은 건조하고 무덤덤하지만 관찰력과 추론력이 매우 날카롭다. "
            "브리핑에서는 실험 결과를 정리하듯 차갑고 정확하게 설명하되, 가끔 비꼬는 듯한 담백한 유머를 섞는다."
        ),
        temp=14,
        today_max_temp=22,
        weather_status="구름 많음",
        pop=40,
        base_date="2026-04-20",
        base_time="08:00",
        formatted_datetime="2026-04-20 08:00",
        ultra_short_data="서울은 현재 구름 많고, 오후에 비가 올 가능성이 40% 정도예요.",
        economic_data="코스피는 전일 대비 약보합 마감, 원/달러 환율은 소폭 상승.",
        market_outlook_news="반도체 대형주와 환율 이슈를 중심으로 관망 심리가 이어질 수 있다는 전망.",
        dust_info="미세먼지는 보통 수준.",
        culture_context="없음",
        futures_options_data="옵션 시장에서는 변동성 경계가 남아 있음.",
        weekly_derivatives_briefing="주간 기준으로는 위험선호가 다소 약해진 흐름.",
    )

    return [
        Case(
            name="microfiction_three_sentence",
            description="3문장 마이크로픽션, 황당한 설정과 반전",
            prompt=(
                "한국어로만 써. 정확히 3문장으로 끝내.\n"
                "장르는 생활밀착형 SF 코미디.\n"
                "반드시 'VHS', 'NPC', '라면', '편의점'을 모두 넣어.\n"
                "상황은 하나만 밀고 가고, 마지막 문장은 허무한 반전으로 끝내.\n"
                "헤더나 설명 없이 본문만 출력해."
            ),
            max_tokens=220,
            max_score=9,
            scorer=microfiction_scorer,
        ),
        Case(
            name="worldbuilding_json",
            description="설정놀이용 세계관 카드 JSON",
            prompt=(
                "다음 조건으로 세계관 카드를 만들어. 출력은 JSON 객체만 써.\n"
                "키는 title, core_rule, faction_a, faction_b, taboo, daily_object, story_hook 만 사용.\n"
                "세계관 조건: 비가 오면 사람들의 하루 기억 중 하나가 영수증에 인쇄되는 도시.\n"
                "너무 거창한 종말론 말고, 일상과 권력 다툼이 같이 보이게 해.\n"
                "story_hook은 1문장, 나머지는 짧은 구절로."
            ),
            max_tokens=240,
            max_score=9,
            scorer=setting_json_scorer,
        ),
        Case(
            name="dialogue_subtext_scene",
            description="8줄 대사 장면, 서브텍스트와 설정 반영",
            prompt=(
                "한국어 대화 장면만 써. 정확히 8줄, A:와 B:가 번갈아 말해.\n"
                "무대 지문 금지, 설명문 금지.\n"
                "장면: 옥상 자동판매기 앞에서 헤어진 동업자가 다시 만난다.\n"
                "반드시 '우산', '빚', '고백'을 모두 넣어.\n"
                "겉으로는 날씨 얘기 같지만 속으로는 서로 다른 거래를 제안하는 분위기로."
            ),
            max_tokens=220,
            max_score=10,
            scorer=dialogue_scorer,
        ),
        Case(
            name="setting_catchphrases",
            description="설정놀이용 짧은 후킹 문구 5개",
            prompt=(
                "한국어로만 써.\n"
                "가상의 설정: 꿈을 기록하는 관측소에서 수면세를 걷는 도시.\n"
                "이 설정을 바탕으로 짧은 후킹 문구 5개를 만들어.\n"
                "각 줄은 '- '로 시작하고, 36자 이하여야 하며, 서로 다른 어조로 써.\n"
                "반드시 '관측소', '수면세', '야근'을 전체 출력 안에 포함해."
            ),
            max_tokens=180,
            max_score=10,
            scorer=catchphrase_scorer,
        ),
        Case(
            name="weather_persona_roleplay",
            description="weather_message 프롬프트 기반 장문 페르소나 몰입",
            prompt=weather_prompt,
            max_tokens=900,
            max_score=7,
            scorer=weather_persona_scorer,
        ),
    ]


def _call_case(base_url: str, model_id: str, prompt: str, max_tokens: int) -> dict[str, Any]:
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.9,
        "top_p": 0.95,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    started = time.time()
    response = requests.post(
        f"{base_url.rstrip('/')}/v1/chat/completions",
        json=payload,
        timeout=600,
    )
    elapsed = round(time.time() - started, 2)
    response.raise_for_status()
    data = response.json()
    content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "").strip()
    return {
        "content": content,
        "elapsed_sec": elapsed,
        "usage": data.get("usage") or {},
        "timings": data.get("timings") or {},
    }


def main() -> int:
    base_url = os.environ.get("BASE_URL", "http://127.0.0.1:8083")
    label = os.environ.get("BENCH_LABEL", "creative-bench")
    warmups = int(os.environ.get("BENCH_WARMUPS", "1"))
    repeats = int(os.environ.get("BENCH_REPEATS", "3"))
    model_id = requests.get(f"{base_url.rstrip('/')}/v1/models", timeout=30).json()["data"][0]["id"]
    cases = _build_cases()

    results: dict[str, Any] = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "service": {"label": label, "base_url": base_url, "model_id": model_id},
        "fairness": {
            "warmup_runs_per_case": warmups,
            "measured_runs_per_case": repeats,
            "temperature": 0.9,
            "top_p": 0.95,
            "notes": [
                "single-model sequential benchmark",
                "same prompts across models",
                "constraint-heavy creative benchmark",
            ],
        },
        "cases": [],
    }

    for case in cases:
        for _ in range(max(warmups, 0)):
            _call_case(base_url, model_id, case.prompt, case.max_tokens)

        runs = [_call_case(base_url, model_id, case.prompt, case.max_tokens) for _ in range(max(repeats, 1))]
        scores: list[int] = []
        for run in runs:
            score, issues = case.scorer(run["content"])
            run["score"] = score
            run["issues"] = issues
            scores.append(score)

        representative = sorted(runs, key=lambda item: item["elapsed_sec"])[len(runs) // 2]
        case_result = {
            "name": case.name,
            "description": case.description,
            "max_score": case.max_score,
            "score_avg": round(statistics.mean(scores), 2),
            "score_best": max(scores),
            "elapsed_avg": round(statistics.mean([run["elapsed_sec"] for run in runs]), 2),
            "predicted_per_second_avg": round(
                statistics.mean([float(run["timings"].get("predicted_per_second") or 0.0) for run in runs]),
                2,
            ),
            "output_variants": len({run["content"] for run in runs}),
            "representative_output": representative["content"],
            "representative_issues": representative["issues"],
            "runs": runs,
        }
        results["cases"].append(case_result)
        print(
            f"{case.name}\t"
            f"score={case_result['score_avg']}/{case.max_score}\t"
            f"elapsed={case_result['elapsed_avg']}s\t"
            f"tok_s={case_result['predicted_per_second_avg']}\t"
            f"variants={case_result['output_variants']}\t"
            f"issues={','.join(case_result['representative_issues']) or 'ok'}"
        )

    total_score = sum(case["score_avg"] for case in results["cases"])
    total_max = sum(case["max_score"] for case in results["cases"])
    results["summary"] = {
        "total_score_avg": round(total_score, 2),
        "total_max_score": total_max,
        "normalized_score_avg": round(total_score / total_max * 100, 2),
        "elapsed_avg_all_cases": round(statistics.mean([case["elapsed_avg"] for case in results["cases"]]), 2),
    }
    print(
        f"TOTAL\t"
        f"score={results['summary']['total_score_avg']}/{total_max}\t"
        f"normalized={results['summary']['normalized_score_avg']}\t"
        f"elapsed_avg={results['summary']['elapsed_avg_all_cases']}s"
    )

    out_dir = ROOT_DIR / "backend" / "storage" / "llm_compare_local"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"creative_benchmark_{label}_{datetime.now():%Y%m%d_%H%M%S}.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"REPORT={out_path.relative_to(ROOT_DIR)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
