from __future__ import annotations

import time

import pytest
import requests


URL = "http://127.0.0.1:8080/v1/chat/completions"

PROMPTS = [
    ("Short", "오늘 점심 메뉴로 추천할 만한 한식 3가지만 짧게 알려줘."),
    ("Medium", "Intel B580 그래픽카드에서 LLM을 구동할 때 SYCL 백엔드가 왜 중요한지 설명해줘."),
    ("Long", "LLM의 오프로딩(Offloading) 개념을 초보자에게 설명하듯이 아주 자세하게 서술해줘. (레이어, VRAM, CPU 관계 포함)"),
]


def _server_reachable() -> bool:
    try:
        requests.get("http://127.0.0.1:8080/health", timeout=1.0)
        return True
    except requests.RequestException:
        return False


@pytest.mark.integration
def test_llm_quick_prompts() -> None:
    if not _server_reachable():
        pytest.skip("local LLM server is not running on 127.0.0.1:8080")

    for _, prompt in PROMPTS:
        payload = {
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
            "max_tokens": 1000,
        }
        start = time.time()
        response = requests.post(URL, json=payload, timeout=600)
        elapsed = time.time() - start
        response.raise_for_status()
        data = response.json()
        assert data["choices"][0]["message"]["content"]
        assert elapsed >= 0.0
