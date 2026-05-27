from contextlib import contextmanager
from typing import Any
from unittest.mock import patch


DEFAULT_LLM_SETTINGS = {
    "llm_base_url": None,
    "llm_api_key": None,
    "llm_timeout": 30,
    "open_api_key": None,
    "ai_report_api_key": "test-key",
    "ai_report_base_url": "https://api.openai.com/v1",
    "ai_report_model": "gpt-5.4-mini",
    "ai_report_fallback_model": "gpt-5.4-mini",
    "ai_report_timeout_sec": 30,
    "llm_remote_model_path_file": None,
    "llm_remote_model_dir": "/data",
    "llm_remote_default_model": "dummy.gguf",
}


class FakeResponse:
    def __init__(self, status_code: int, json_data: Any = None, text: str = ""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    def json(self):
        if isinstance(self._json_data, Exception):
            raise self._json_data
        return self._json_data


@contextmanager
def patched_llm_settings(**overrides):
    values = dict(DEFAULT_LLM_SETTINGS)
    values.update(overrides)

    with patch("backend.services.llm.config.settings") as mock_settings:
        for key, value in values.items():
            setattr(mock_settings, key, value)
        yield mock_settings
