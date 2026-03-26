from __future__ import annotations

import json
import re
import sys
import time
from argparse import ArgumentParser
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from typing import Any

import requests


ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from backend.services.prompt_loader import load_prompt  # noqa: E402


DEFAULT_LEFT = "http://127.0.0.1:8082"
DEFAULT_RIGHT = "http://127.0.0.1:8083"
DEFAULT_LEFT_LABEL = "openvino"
DEFAULT_RIGHT_LABEL = "llama-vulkan"
STOP_TOKENS = [
    "Okay",
    "let me",
    "Let me",
    "I'll",
    "사용자가",
    "지시사항을",
    "지문을",
    "지시를",
    "알겠습니다",
    "확인했습니다",
    "요청하신 대로",
    "아래는",
]
META_PATTERNS = (
    "요약하면",
    "정리하면",
    "알려드릴게요",
    "다음과 같습니다",
    "첫 번째는",
    "제목은",
    "분석하면",
)
DEFAULT_WARMUPS = 1
DEFAULT_REPEATS = 3


@dataclass(frozen=True)
class Case:
    name: str
    description: str
    messages: list[dict[str, str]]
    max_tokens: int
    temperature: float = 0.0
    top_p: float = 1.0
    expected_shape: str = "plain"


def _build_cases() -> list[Case]:
    notifications = "\n".join(
        [
            json.dumps(
                {
                    "idx": 1,
                    "app": "카카오톡",
                    "title": "민수",
                    "conversation": "가족방",
                    "body": "엄마가 오늘 저녁 7시에 집에서 보자고 함",
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "idx": 2,
                    "app": "카카오톡",
                    "title": "지훈",
                    "conversation": "회사 단톡",
                    "body": "내일 오전 9시 회의 자료 올려달라고 함",
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "idx": 3,
                    "app": "토스증권",
                    "title": "주식 체결",
                    "conversation": "",
                    "body": "삼성전자 10주 매수 체결 완료",
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "idx": 4,
                    "app": "배달의민족",
                    "title": "주문 상태",
                    "conversation": "",
                    "body": "[순살치킨] 배달 시작, 18분 후 도착 예정",
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "idx": 5,
                    "app": "Gmail",
                    "title": "Google",
                    "conversation": "",
                    "body": "보안 알림: 새 기기에서 계정 로그인 감지",
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "idx": 6,
                    "app": "쿠팡",
                    "title": "광고",
                    "conversation": "",
                    "body": "오늘만 특가 쿠폰 지급",
                },
                ensure_ascii=False,
            ),
        ]
    )
    alarm_prompt = load_prompt("alarm_summary", notifications=notifications)

    refine_draft = """요약입니다.
<think>같은 메시지라서 두 건으로 합치면 된다.</think>
- 카카오톡에서 가족방, 회사 단톡 메시지 2건
- 토스증권에서 삼성전자 10주 매수 체결 완료
- 토스증권에서 삼성전자 10주 매수 체결 완료
- 배달의민족에서 [순살치킨] 배달 시작
"""
    refine_prompt = load_prompt("refine_alarm_summary", draft=refine_draft)

    memory_prompt = load_prompt(
        "memory_chat_summary",
        summary_text=(
            "- 사용자는 한국 주식 자동매매와 가계부 앱을 함께 관리 중입니다.\n"
            "- 최근에는 트레이딩엔진 주문 가능 수량 로직을 수정했습니다.\n"
            "- 답변은 군더더기 없이 빠르게 받는 편을 선호합니다."
        ),
        messages_text=(
            "user: 내일 장 시작하면 파킹 주문이 실제 매수가능수량 기준으로 나가는지 볼 거야.\n"
            "assistant: 매수가능조회와 매도가능수량조회 둘 다 붙여뒀습니다.\n"
            "user: 그리고 Codex fast 모드는 꺼둘 생각이야.\n"
            "assistant: ~/.codex/config.toml 에서 service_tier 설정을 빼면 됩니다."
        ),
    )

    general_messages = [
        {
            "role": "user",
            "content": (
                "한국어로만 답해. 원/달러 환율이 급등할 때 한국 반도체주 투자자가 확인해야 할 핵심 지표를 "
                "3가지만 짧고 명확하게 설명해줘."
            ),
        }
    ]

    return [
        Case(
            name="alarm_summary",
            description="실서비스 알림 요약 규칙 준수",
            messages=[{"role": "user", "content": alarm_prompt}],
            max_tokens=180,
            expected_shape="bullets",
        ),
        Case(
            name="refine_alarm_summary",
            description="메타/사고과정 제거와 중복 정리",
            messages=[{"role": "user", "content": refine_prompt}],
            max_tokens=120,
            expected_shape="bullets",
        ),
        Case(
            name="memory_chat_summary",
            description="대화 메모리 요약 안정성",
            messages=[{"role": "user", "content": memory_prompt}],
            max_tokens=160,
            expected_shape="plain",
        ),
        Case(
            name="general_finance",
            description="일반 한국어 설명 품질",
            messages=general_messages,
            max_tokens=140,
            expected_shape="plain",
        ),
    ]


def _get_model_id(base_url: str) -> str:
    response = requests.get(f"{base_url.rstrip('/')}/v1/models", timeout=30)
    response.raise_for_status()
    data = response.json()
    items = data.get("data") or []
    if items and isinstance(items[0], dict):
        return str(items[0].get("id") or "unknown-model")
    return "unknown-model"


def _contains_meta(text: str) -> bool:
    lowered = text.lower()
    return any(token.lower() in lowered for token in META_PATTERNS)


def _english_ratio(text: str) -> float:
    letters = re.findall(r"[A-Za-z]", text or "")
    chars = re.findall(r"[A-Za-z가-힣]", text or "")
    if not chars:
        return 0.0
    return len(letters) / len(chars)


def _line_count(text: str) -> int:
    return len([line for line in (text or "").splitlines() if line.strip()])


def _bullet_shape_ok(text: str) -> bool:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return False
    return all(line.startswith("-") for line in lines)


def _quality_notes(case: Case, text: str) -> list[str]:
    notes: list[str] = []
    if not text.strip():
        notes.append("empty")
        return notes
    if case.expected_shape == "bullets" and not _bullet_shape_ok(text):
        notes.append("bullet_format_miss")
    if _contains_meta(text):
        notes.append("meta_leak")
    if _english_ratio(text) > 0.15:
        notes.append("english_heavy")
    if case.name == "refine_alarm_summary" and text.count("삼성전자 10주 매수 체결 완료") > 1:
        notes.append("duplicate_not_removed")
    return notes


def _call_case(base_url: str, model_id: str, case: Case) -> dict[str, Any]:
    payload = {
        "model": model_id,
        "messages": case.messages,
        "max_tokens": case.max_tokens,
        "temperature": case.temperature,
        "top_p": case.top_p,
        "stop": STOP_TOKENS,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    started = time.time()
    response = requests.post(
        f"{base_url.rstrip('/')}/v1/chat/completions",
        json=payload,
        timeout=600,
    )
    elapsed = time.time() - started
    response.raise_for_status()
    data = response.json()
    content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "").strip()
    timings = data.get("timings") or {}
    usage = data.get("usage") or {}
    return {
        "content": content,
        "elapsed_sec": round(elapsed, 2),
        "usage": usage,
        "timings": timings,
        "quality_notes": _quality_notes(case, content),
        "line_count": _line_count(content),
    }


def _average_usage(runs: list[dict[str, Any]]) -> dict[str, float]:
    if not runs:
        return {}
    numeric_keys = ("prompt_tokens", "completion_tokens", "total_tokens")
    averaged: dict[str, float] = {}
    for key in numeric_keys:
        values = [float(run.get("usage", {}).get(key, 0)) for run in runs]
        averaged[key] = round(mean(values), 2)
    return averaged


def _average_predicted_per_second(runs: list[dict[str, Any]]) -> float | None:
    values = [
        float(run.get("timings", {}).get("predicted_per_second"))
        for run in runs
        if run.get("timings", {}).get("predicted_per_second") is not None
    ]
    if not values:
        return None
    return round(mean(values), 2)


def _select_representative_run(runs: list[dict[str, Any]]) -> dict[str, Any]:
    sorted_runs = sorted(runs, key=lambda run: float(run["elapsed_sec"]))
    return sorted_runs[len(sorted_runs) // 2]


def _summarize_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    elapsed_values = [float(run["elapsed_sec"]) for run in runs]
    unique_outputs = sorted({run["content"] for run in runs})
    quality_notes = sorted({note for run in runs for note in run["quality_notes"]})
    representative = _select_representative_run(runs)
    summary: dict[str, Any] = {
        "content": representative["content"],
        "elapsed_sec": representative["elapsed_sec"],
        "elapsed_sec_avg": round(mean(elapsed_values), 2),
        "elapsed_sec_median": round(median(elapsed_values), 2),
        "usage_avg": _average_usage(runs),
        "predicted_per_second_avg": _average_predicted_per_second(runs),
        "quality_notes": quality_notes,
        "line_count": representative["line_count"],
        "output_variants": len(unique_outputs),
        "runs": runs,
    }
    return summary


def _run_case_with_repeats(
    base_url: str,
    model_id: str,
    case: Case,
    warmups: int,
    repeats: int,
) -> dict[str, Any]:
    warmup_runs: list[dict[str, Any]] = []
    measured_runs: list[dict[str, Any]] = []

    for _ in range(max(warmups, 0)):
        warmup_runs.append(_call_case(base_url, model_id, case))

    for _ in range(max(repeats, 1)):
        measured_runs.append(_call_case(base_url, model_id, case))

    summary = _summarize_runs(measured_runs)
    summary["warmup_runs"] = warmup_runs
    return summary


def _build_parser() -> ArgumentParser:
    parser = ArgumentParser(description="Compare two OpenAI-compatible LLM endpoints fairly.")
    parser.add_argument("left_base", nargs="?", default=DEFAULT_LEFT)
    parser.add_argument("right_base", nargs="?", default=DEFAULT_RIGHT)
    parser.add_argument("left_label", nargs="?", default=DEFAULT_LEFT_LABEL)
    parser.add_argument("right_label", nargs="?", default=DEFAULT_RIGHT_LABEL)
    parser.add_argument("--warmups", type=int, default=DEFAULT_WARMUPS)
    parser.add_argument("--repeats", type=int, default=DEFAULT_REPEATS)
    return parser


def _write_report(results: dict[str, Any]) -> Path:
    filename = f"compare_{datetime.now():%Y%m%d_%H%M%S}.json"
    candidates = [
        ROOT_DIR / "backend" / "storage" / "llm_compare",
        ROOT_DIR / "backend" / "storage" / "llm_compare_local",
        ROOT_DIR / "devplan" / "llm_compare",
    ]
    payload = json.dumps(results, ensure_ascii=False, indent=2)

    last_error: Exception | None = None
    for directory in candidates:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            out_path = directory / filename
            out_path.write_text(payload, encoding="utf-8")
            return out_path
        except PermissionError as exc:
            last_error = exc
            continue

    if last_error is not None:
        raise last_error
    raise RuntimeError("Failed to write comparison report")


def main() -> int:
    args = _build_parser().parse_args()
    left_base = args.left_base
    right_base = args.right_base
    left_label = args.left_label
    right_label = args.right_label

    cases = _build_cases()
    services = [
        {"label": left_label, "base_url": left_base},
        {"label": right_label, "base_url": right_base},
    ]

    results: dict[str, Any] = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "fairness": {
            "warmup_runs_per_case": max(args.warmups, 0),
            "measured_runs_per_case": max(args.repeats, 1),
            "temperature": 0.0,
            "top_p": 1.0,
            "notes": [
                "same prompts/cases for both services",
                "deterministic decoding for lower run-to-run variance",
                "warmup runs excluded from measured averages",
                "measured runs retain per-run details for auditability",
            ],
        },
        "services": {},
        "cases": [],
    }

    for service in services:
        service["model_id"] = _get_model_id(service["base_url"])
        results["services"][service["label"]] = {
            "base_url": service["base_url"],
            "model_id": service["model_id"],
        }

    for case in cases:
        row: dict[str, Any] = {
            "name": case.name,
            "description": case.description,
            "expected_shape": case.expected_shape,
            "results": {},
        }
        print(f"\n=== {case.name} | {case.description} ===")
        for service in services:
            result = _run_case_with_repeats(
                service["base_url"],
                service["model_id"],
                case,
                warmups=args.warmups,
                repeats=args.repeats,
            )
            row["results"][service["label"]] = result
            print(f"\n[{service['label']}] {service['model_id']}")
            print(
                f"elapsed_avg={result['elapsed_sec_avg']}s "
                f"elapsed_median={result['elapsed_sec_median']}s "
                f"line_count={result['line_count']} "
                f"variants={result['output_variants']} "
                f"notes={','.join(result['quality_notes']) or 'ok'}"
            )
            print(result["content"])
        results["cases"].append(row)

    out_path = _write_report(results)
    print(f"\nSaved JSON report to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
