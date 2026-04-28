from __future__ import annotations

import requests
import pytest


URL = "http://127.0.0.1:8080/v1/chat/completions"
PAYLOAD = {
    "model": "model",
    "messages": [{"role": "user", "content": "spam? [광고] 포인트!"}],
    "max_tokens": 10,
}


def _server_reachable() -> bool:
    try:
        requests.get("http://127.0.0.1:8080/health", timeout=1.0)
        return True
    except requests.RequestException:
        return False


@pytest.mark.integration
def test_direct_chat_completion_endpoint() -> None:
    if not _server_reachable():
        pytest.skip("local chat completion server is not running on 127.0.0.1:8080")

    response = requests.post(URL, json=PAYLOAD, timeout=10.0)
    response.raise_for_status()
    data = response.json()

    assert "choices" in data
    assert data["choices"][0]["message"]["content"]
