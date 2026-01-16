# 🤖 AI Agent Improvement Prompts

> ## 🚨 MANDATORY: FILE MODIFICATION REQUIRED
> 
> **⛔ DO NOT just respond with text or code blocks.**
> **⛔ DO NOT say "you can modify like this" without actually modifying.**
> **⛔ DO NOT explain what needs to be done without doing it.**
> 
> **✅ YOU MUST use file editing tools (`replace_string_in_file`, `create_file`, `multi_replace_string_in_file`) to directly modify files.**
> **✅ After each prompt, confirm "I have modified the file(s)" with the actual changes made.**
> 
> ---
> 
> **Process ALL prompts below SEQUENTIALLY. Do NOT stop after completing one prompt.**

---

## 📋 Execution Checklist

| # | Prompt ID | Title | Priority | Status |
|:---:|:---|:---|:---:|:---:|
| 1 | PROMPT-001 | Fix scheduler monitor exception re-raise + add tests | P1 | ⬜ Pending |
| 2 | PROMPT-002 | Harden LLM service config, errors, and fallback + tests | P2 | ⬜ Pending |
| 3 | PROMPT-003 | Update npm scripts to prefer `python3` | P3 | ⬜ Pending |

**Total: 3 prompts** | **Completed: 0** | **Remaining: 3**

---

## 🔴 Priority 1 (Critical) - Execute First

### [PROMPT-001] Fix scheduler monitor exception re-raise + add tests

**⏱️ Execute this prompt now, then proceed to PROMPT-002**

> **🚨 REQUIRED: Use `replace_string_in_file` or `create_file` to make changes. Do NOT just show code.**

**Task**: Replace `raise e` with `raise` in scheduler job monitors and add unit tests to lock in status transitions and exception propagation.  
**Files to Modify**: `backend/services/scheduler_monitor.py`, `backend/tests/test_scheduler_monitor.py`

#### Instructions:

1. Open `backend/services/scheduler_monitor.py`
2. Update exception re-raise to use `raise` (preserve traceback)
3. Create `backend/tests/test_scheduler_monitor.py` with success/failure coverage

#### Implementation Code:

```python
# backend/services/scheduler_monitor.py
import logging
from datetime import datetime
from contextlib import contextmanager, asynccontextmanager
from sqlalchemy.orm import Session
from ..core.models import SchedulerState

logger = logging.getLogger(__name__)


@contextmanager
def monitor_job(job_id: str, db: Session):
    """
    스케줄러 작업의 실행 상태를 DB에 기록하는 컨텍스트 매니저 (Sync).
    """
    state = db.query(SchedulerState).filter(SchedulerState.job_id == job_id).first()
    if not state:
        state = SchedulerState(job_id=job_id)
        db.add(state)

    state.status = "running"
    state.last_run_at = datetime.utcnow()
    state.message = None
    db.commit()

    try:
        yield
        state.status = "success"
        state.last_success_at = datetime.utcnow()
        db.commit()
    except Exception as e:
        state.status = "failure"
        state.last_failure_at = datetime.utcnow()
        state.message = str(e)
        db.commit()
        logger.exception("Scheduler job failed: %s", job_id)
        raise


@asynccontextmanager
async def monitor_job_async(job_id: str, db: Session):
    """
    스케줄러 작업의 실행 상태를 DB에 기록하는 컨텍스트 매니저 (Async).
    """
    state = db.query(SchedulerState).filter(SchedulerState.job_id == job_id).first()
    if not state:
        state = SchedulerState(job_id=job_id)
        db.add(state)

    state.status = "running"
    state.last_run_at = datetime.utcnow()
    state.message = None
    db.commit()

    try:
        yield
        state.status = "success"
        state.last_success_at = datetime.utcnow()
        db.commit()
    except Exception as e:
        state.status = "failure"
        state.last_failure_at = datetime.utcnow()
        state.message = str(e)
        db.commit()
        logger.exception("Scheduler job failed: %s", job_id)
        raise
```

```python
# backend/tests/test_scheduler_monitor.py
import unittest
from unittest.mock import MagicMock, patch

from backend.services import scheduler_monitor


class _FakeSchedulerState:
    job_id = "job_id"

    def __init__(self, job_id: str):
        self.job_id = job_id
        self.status = None
        self.last_run_at = None
        self.last_success_at = None
        self.last_failure_at = None
        self.message = None


class TestSchedulerMonitor(unittest.TestCase):
    def _build_db(self, existing_state=None):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = existing_state
        return db

    def test_monitor_job_success_creates_and_marks_success(self):
        db = self._build_db(existing_state=None)

        with patch.object(scheduler_monitor, "SchedulerState", _FakeSchedulerState):
            with scheduler_monitor.monitor_job("job-1", db):
                pass

        state = db.add.call_args[0][0]
        self.assertEqual(state.job_id, "job-1")
        self.assertEqual(state.status, "success")
        self.assertIsNotNone(state.last_run_at)
        self.assertIsNotNone(state.last_success_at)
        self.assertIsNone(state.message)
        self.assertGreaterEqual(db.commit.call_count, 2)

    def test_monitor_job_failure_marks_failure_and_reraises(self):
        db = self._build_db(existing_state=None)

        with patch.object(scheduler_monitor, "SchedulerState", _FakeSchedulerState):
            with self.assertRaises(ValueError):
                with scheduler_monitor.monitor_job("job-2", db):
                    raise ValueError("boom")

        state = db.add.call_args[0][0]
        self.assertEqual(state.job_id, "job-2")
        self.assertEqual(state.status, "failure")
        self.assertIsNotNone(state.last_run_at)
        self.assertIsNotNone(state.last_failure_at)
        self.assertEqual(state.message, "boom")
        self.assertGreaterEqual(db.commit.call_count, 2)
```

#### Verification:
- Run: `python3 -m unittest backend/tests/test_scheduler_monitor.py`
- Expected: All tests pass.

**✅ After completing this prompt, proceed to [PROMPT-002]**

---

## 🟡 Priority 2 (High) - Execute Second

### [PROMPT-002] Harden LLM service config, errors, and fallback + tests

**⏱️ Execute this prompt now, then proceed to PROMPT-003**

> **🚨 REQUIRED: Use `replace_string_in_file` or `create_file` to make changes. Do NOT just show code.**

**Task**: Prevent silent LLM failures by adding explicit configuration checks, error propagation (`last_error`), safe fallback from remote → paid backend, and unit tests that run without network.  
**Files to Modify**: `backend/services/llm/config.py`, `backend/services/llm/service.py`, `backend/services/llm/backends/remote.py`, `backend/services/llm/backends/paid.py`, `backend/tests/test_llm_service.py`

#### Instructions:

1. Update `backend/services/llm/config.py` to use absolute backend paths for file IO while keeping displayed model paths stable
2. Update `backend/services/llm/backends/remote.py` and `backend/services/llm/backends/paid.py` to track `_last_error` and avoid network when not configured
3. Update `backend/services/llm/service.py` to choose remote/paid backend deterministically and to expose `get_last_error()`
4. Add `backend/tests/test_llm_service.py` to verify selection/fallback without hitting the network

#### Implementation Code:

```python
# backend/services/llm/config.py
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _resolve_backend_dir_abs() -> str:
    # backend/services/llm/config.py -> backend/
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


BACKEND_DIR_ABS = _resolve_backend_dir_abs()
DATA_DIR_ABS = os.path.join(BACKEND_DIR_ABS, "data")
DATA_DIR_REL = os.path.join("backend", "data")

# 경로 상수 (원격 모드 전용)
REMOTE_MODEL_PATH_FILE = os.getenv(
    "LLM_REMOTE_MODEL_PATH_FILE",
    os.path.join(DATA_DIR_ABS, "llm_model_path.txt"),
)
REMOTE_MODEL_DIR = os.getenv("LLM_REMOTE_MODEL_DIR", "/data")
DEFAULT_MODEL_FILENAME = os.getenv("LLM_REMOTE_DEFAULT_MODEL", "EXAONE-4.0-1.2B-BF16.gguf")


class Settings:
    """
    LLM 설정 및 환경 변수 관리 (원격/유료 백엔드 공용)
    """

    def __init__(self):
        self.llm_base_url = (os.getenv("LLM_BASE_URL") or "").strip() or None
        self.llm_api_key = (os.getenv("LLM_API_KEY") or "").strip() or None
        self.llm_timeout = float(os.getenv("LLM_TIMEOUT", "120"))

        # 유료 모델용
        self.ai_report_base_url = os.getenv("AI_REPORT_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self.ai_report_api_key = (os.getenv("AI_REPORT_API_KEY") or "").strip() or None
        self.ai_report_model = (os.getenv("AI_REPORT_MODEL", "gpt-5.2") or "gpt-5.2").strip()

        self.backend_dir_abs = BACKEND_DIR_ABS
        self.data_dir_abs = DATA_DIR_ABS
        self.data_dir_rel = DATA_DIR_REL
        self.remote_model_path_file = REMOTE_MODEL_PATH_FILE

        self.current_model_path = self._initialize_model_path()

    def is_remote_configured(self) -> bool:
        return bool(self.llm_base_url)

    def is_paid_configured(self) -> bool:
        return bool(self.ai_report_api_key)

    def _initialize_model_path(self) -> str:
        """현재 활성화된 모델의 로컬 표시 경로를 결정한다."""
        return self.load_remote_model_path() or os.path.join(self.data_dir_rel, DEFAULT_MODEL_FILENAME)

    def load_remote_model_path(self) -> Optional[str]:
        remote_path = self.read_remote_model_path_raw()
        if not remote_path:
            return None
        return self.to_local_model_path(remote_path)

    def read_remote_model_path_raw(self) -> Optional[str]:
        """llm_model_path.txt에서 실제 원격 경로를 읽어온다."""
        path = self.remote_model_path_file
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = f.read().strip()
            if not raw:
                return None

            # 경로 정규화 (원격 llama-server 기준)
            if raw.startswith(("backend/data/", "/app/backend/data/")):
                filename = os.path.basename(raw)
                return f"{REMOTE_MODEL_DIR.rstrip('/')}/{filename}"
            if raw.startswith("/"):
                return raw
            return f"{REMOTE_MODEL_DIR.rstrip('/')}/{raw}"
        except Exception as e:
            logger.error("Failed to read remote model path file: %s", e)
            return None

    def write_remote_model_path(self, remote_path: str) -> bool:
        """원격 모델 경로를 파일에 저장하여 llama-server가 감지할 수 있게 한다."""
        path = self.remote_model_path_file
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(remote_path)
            return True
        except Exception as e:
            logger.error("Failed to write remote model path file: %s", e)
            return False

    @staticmethod
    def to_remote_model_path(local_path: str) -> str:
        filename = os.path.basename(local_path)
        return f"{REMOTE_MODEL_DIR.rstrip('/')}/{filename}"

    def to_local_model_path(self, remote_path: str) -> str:
        filename = os.path.basename(remote_path)
        return os.path.join(self.data_dir_rel, filename)
```

```python
# backend/services/llm/backends/remote.py
import logging
from typing import List, Optional

import httpx

from .base import LLMBackend
from ..config import Settings

logger = logging.getLogger(__name__)


class RemoteLlamaBackend(LLMBackend):
    """
    llama-server (OpenAI 호환 API) 백엔드
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = httpx.Client(timeout=settings.llm_timeout)
        self._model_id_cache: Optional[str] = None
        self._last_error: Optional[str] = None

    def get_last_error(self) -> Optional[str]:
        return self._last_error

    def _base_url(self) -> Optional[str]:
        if not self.settings.llm_base_url:
            self._last_error = "LLM_BASE_URL is not set"
            return None
        return self.settings.llm_base_url.rstrip("/")

    def _get_model_id(self) -> str:
        if self._model_id_cache:
            return self._model_id_cache

        base_url = self._base_url()
        if not base_url:
            return "local-model"

        try:
            url = f"{base_url}/v1/models"
            headers = {"Content-Type": "application/json"}
            if self.settings.llm_api_key:
                headers["Authorization"] = f"Bearer {self.settings.llm_api_key}"

            r = self._client.get(url, headers=headers)
            r.raise_for_status()
            data = r.json()
            items = data.get("data") or []
            if items and isinstance(items[0], dict):
                model_id = items[0].get("id")
                if model_id:
                    self._model_id_cache = model_id
                    self._last_error = None
                    return model_id
        except Exception as e:
            self._last_error = f"Failed to fetch model id from remote: {e}"
            logger.warning(self._last_error)

        return "local-model"

    def generate(
        self,
        prompt: str,
        max_tokens: int = 512,
        temperature: float = 0.7,
        stop: Optional[list] = None,
        seed: Optional[int] = None,
        **kwargs,
    ) -> str:
        messages = [{"role": "user", "content": prompt}]
        return self.chat(messages, max_tokens=max_tokens, temperature=temperature, stop=stop, seed=seed, **kwargs)

    def chat(
        self,
        messages: List[dict],
        max_tokens: int = 512,
        temperature: float = 0.7,
        stop: Optional[list] = None,
        seed: Optional[int] = None,
        **kwargs,
    ) -> str:
        base_url = self._base_url()
        if not base_url:
            return ""

        try:
            url = f"{base_url}/v1/chat/completions"
            headers = {"Content-Type": "application/json"}
            if self.settings.llm_api_key:
                headers["Authorization"] = f"Bearer {self.settings.llm_api_key}"

            payload = {
                "model": kwargs.get("model") or self._get_model_id(),
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            if stop:
                payload["stop"] = stop

            # enable_thinking 처리 (llama-server 공식 방식)
            enable_thinking = kwargs.get("enable_thinking")
            if enable_thinking is not None:
                payload["chat_template_kwargs"] = {"enable_thinking": bool(enable_thinking)}

            r = self._client.post(url, json=payload, headers=headers)
            r.raise_for_status()
            self._last_error = None
            return r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            self._last_error = f"Remote LLM request failed: {e}"
            logger.error(self._last_error)
            return ""

    def is_loaded(self) -> bool:
        return True

    def reset(self) -> None:
        pass
```

```python
# backend/services/llm/backends/paid.py
import logging
from typing import List, Optional

import httpx

from .base import LLMBackend
from ..config import Settings

logger = logging.getLogger(__name__)


class OpenAIPaidBackend(LLMBackend):
    """
    OpenAI 유료 API 백엔드 (Chat Completions -> Responses fallback)
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = httpx.Client(timeout=settings.llm_timeout)
        self._last_error: Optional[str] = None

    def get_last_error(self) -> Optional[str]:
        return self._last_error

    def generate(
        self,
        prompt: str,
        max_tokens: int = 512,
        temperature: float = 0.7,
        stop: Optional[list] = None,
        seed: Optional[int] = None,
        **kwargs,
    ) -> str:
        messages = [{"role": "user", "content": prompt}]
        return self.chat(messages, max_tokens=max_tokens, temperature=temperature, **kwargs)

    def chat(
        self,
        messages: List[dict],
        max_tokens: int = 1024,
        temperature: float = 0.5,
        stop: Optional[list] = None,
        seed: Optional[int] = None,
        **kwargs,
    ) -> str:
        api_key = self.settings.ai_report_api_key
        if not api_key:
            self._last_error = "AI_REPORT_API_KEY is not set"
            return ""

        model = kwargs.get("model") or self.settings.ai_report_model
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        is_gpt5 = str(model).startswith("gpt-5")

        # 1) Chat Completions 시도
        try:
            url = f"{self.settings.ai_report_base_url}/chat/completions"
            payload = {"model": model, "messages": messages}
            if not is_gpt5:
                payload["temperature"] = temperature
            payload["max_completion_tokens" if is_gpt5 else "max_tokens"] = max_tokens

            r = self._client.post(url, json=payload, headers=headers)
            if r.status_code < 400:
                self._last_error = None
                return r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.debug("Chat completions failed, trying responses: %s", e)

        # 2) Responses API 시도 (GPT-5 등 지원)
        try:
            url = f"{self.settings.ai_report_base_url}/responses"
            payload = {
                "model": model,
                "input": [
                    {"role": m["role"], "content": [{"type": "input_text", "text": str(m["content"])}]}
                    for m in messages
                ],
                "max_output_tokens": max_tokens,
            }
            if is_gpt5:
                payload["reasoning"] = {"effort": "low"}
            else:
                payload["temperature"] = temperature

            r = self._client.post(url, json=payload, headers=headers)
            if r.status_code < 400:
                data = r.json()
                if output := data.get("output_text"):
                    self._last_error = None
                    return output.strip()

                chunks = []
                for item in (data.get("output") or []):
                    for part in (item.get("content") or []):
                        if part.get("type") in ("text", "output_text"):
                            chunks.append(part.get("text", ""))
                self._last_error = None
                return "".join(chunks).strip()
        except Exception as e:
            self._last_error = f"Paid LLM total failure: {e}"
            logger.error(self._last_error)

        if not self._last_error:
            self._last_error = "Paid LLM request failed"
        return ""

    def is_loaded(self) -> bool:
        return bool(self.settings.ai_report_api_key)

    def reset(self) -> None:
        pass
```

```python
# backend/services/llm/service.py
import logging
import os
from typing import List, Optional

from .config import Settings
from .backends.remote import RemoteLlamaBackend
from .backends.paid import OpenAIPaidBackend

logger = logging.getLogger(__name__)


class LLMService:
    """
    LLM 서비스 파사드 (원격 llama-server + 유료 API 폴백)
    """

    _instance = None

    def __init__(self):
        if LLMService._instance is not None:
            raise Exception("This class is a singleton!")

        self.settings = Settings()

        self.backend = RemoteLlamaBackend(self.settings)
        self.paid_backend = OpenAIPaidBackend(self.settings)
        self._last_error: Optional[str] = None
        LLMService._instance = self

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = LLMService()
        return cls._instance

    def generate(
        self,
        prompt: str,
        max_tokens: int = 512,
        temperature: float = 0.7,
        stop: Optional[list] = None,
        seed: Optional[int] = None,
        **kwargs,
    ) -> str:
        messages = [{"role": "user", "content": prompt}]
        return self.generate_chat(messages, max_tokens=max_tokens, temperature=temperature, stop=stop, seed=seed, **kwargs)

    def generate_chat(
        self,
        messages: List[dict],
        max_tokens: int = 512,
        temperature: float = 0.7,
        stop: Optional[list] = None,
        seed: Optional[int] = None,
        **kwargs,
    ) -> str:
        # 1) 원격 백엔드 우선
        if self.settings.is_remote_configured():
            out = self.backend.chat(messages, max_tokens=max_tokens, temperature=temperature, stop=stop, seed=seed, **kwargs)
            if out:
                self._last_error = None
                return out

            remote_error = getattr(self.backend, "_last_error", None) or "Remote LLM failed"
            logger.warning("Remote LLM failed, trying paid backend: %s", remote_error)

            # 2) 원격 실패 시 유료 백엔드 폴백
            if self.settings.is_paid_configured():
                out_paid = self.paid_backend.chat(messages, max_tokens=max_tokens, temperature=temperature, model=kwargs.get("model"))
                if out_paid:
                    self._last_error = None
                    return out_paid

                paid_error = getattr(self.paid_backend, "_last_error", None) or "Paid LLM failed"
                self._last_error = f"{remote_error} | {paid_error}"
                return ""

            self._last_error = remote_error
            return ""

        # 원격 미구성: 유료 백엔드만 사용
        if self.settings.is_paid_configured():
            out_paid = self.paid_backend.chat(messages, max_tokens=max_tokens, temperature=temperature, model=kwargs.get("model"))
            if out_paid:
                self._last_error = None
                return out_paid
            self._last_error = getattr(self.paid_backend, "_last_error", None) or "Paid LLM failed"
            return ""

        self._last_error = "No LLM backend configured (set LLM_BASE_URL or AI_REPORT_API_KEY)"
        return ""

    def generate_paid_chat(
        self,
        messages: List[dict],
        max_tokens: int = 1024,
        temperature: float = 0.5,
        model: Optional[str] = None,
    ) -> str:
        out = self.paid_backend.chat(messages, max_tokens=max_tokens, temperature=temperature, model=model)
        if out:
            self._last_error = None
            return out
        self._last_error = getattr(self.paid_backend, "_last_error", None) or "Paid LLM failed"
        return ""

    def switch_model(self, model_path: str) -> bool:
        """원격 모델 스위칭 지원"""
        if not os.path.exists(model_path):
            logger.error("Model path does not exist: %s", model_path)
            self._last_error = f"Model path does not exist: {model_path}"
            return False

        remote_path = self.settings.to_remote_model_path(model_path)
        if self.settings.write_remote_model_path(remote_path):
            self.settings.current_model_path = model_path
            self._last_error = None
            return True
        self._last_error = "Failed to write remote model path"
        return False

    def is_loaded(self) -> bool:
        return True

    def reset_context(self):
        pass

    def get_current_model(self) -> str:
        path = self.settings.load_remote_model_path()
        if path:
            self.settings.current_model_path = path
        return self.settings.current_model_path

    def list_available_models(self) -> List[str]:
        models: List[str] = []
        data_dir_abs = self.settings.data_dir_abs
        if os.path.exists(data_dir_abs):
            for file in os.listdir(data_dir_abs):
                if file.endswith(".gguf"):
                    models.append(os.path.join(self.settings.data_dir_rel, file))
        return sorted(models)

    def get_last_error(self) -> Optional[str]:
        return self._last_error or getattr(self.backend, "_last_error", None) or getattr(self.paid_backend, "_last_error", None)
```

```python
# backend/tests/test_llm_service.py
import os
import unittest
from unittest.mock import patch

from backend.services.llm_service import LLMService
from backend.services.llm.backends.remote import RemoteLlamaBackend
from backend.services.llm.backends.paid import OpenAIPaidBackend


class TestLLMService(unittest.TestCase):
    def tearDown(self):
        LLMService._instance = None

    def test_generate_chat_uses_paid_when_remote_not_configured(self):
        env = {
            "AI_REPORT_API_KEY": "test-key",
            "AI_REPORT_BASE_URL": "https://api.openai.com/v1",
            "AI_REPORT_MODEL": "gpt-5.2",
        }

        with patch.dict(os.environ, env, clear=True):
            with patch.object(RemoteLlamaBackend, "chat", side_effect=AssertionError("remote should not be used")):
                with patch.object(OpenAIPaidBackend, "chat", return_value="paid-ok") as paid_chat:
                    llm = LLMService.get_instance()
                    out = llm.generate_chat([{"role": "user", "content": "hi"}])
                    self.assertEqual(out, "paid-ok")
                    paid_chat.assert_called()

    def test_generate_chat_prefers_remote_when_configured(self):
        env = {
            "LLM_BASE_URL": "http://localhost:8080",
            "AI_REPORT_API_KEY": "test-key",
            "AI_REPORT_BASE_URL": "https://api.openai.com/v1",
            "AI_REPORT_MODEL": "gpt-5.2",
        }

        with patch.dict(os.environ, env, clear=True):
            with patch.object(RemoteLlamaBackend, "chat", return_value="remote-ok") as remote_chat:
                with patch.object(OpenAIPaidBackend, "chat", side_effect=AssertionError("paid should not be used")):
                    llm = LLMService.get_instance()
                    out = llm.generate_chat([{"role": "user", "content": "hi"}])
                    self.assertEqual(out, "remote-ok")
                    remote_chat.assert_called()

    def test_generate_chat_falls_back_to_paid_on_remote_failure(self):
        env = {
            "LLM_BASE_URL": "http://localhost:8080",
            "AI_REPORT_API_KEY": "test-key",
            "AI_REPORT_BASE_URL": "https://api.openai.com/v1",
            "AI_REPORT_MODEL": "gpt-5.2",
        }

        def _remote_fail(self, *args, **kwargs):
            self._last_error = "remote boom"
            return ""

        with patch.dict(os.environ, env, clear=True):
            with patch.object(RemoteLlamaBackend, "chat", new=_remote_fail):
                with patch.object(OpenAIPaidBackend, "chat", return_value="paid-ok"):
                    llm = LLMService.get_instance()
                    out = llm.generate_chat([{"role": "user", "content": "hi"}])
                    self.assertEqual(out, "paid-ok")
                    self.assertIsNone(llm.get_last_error())
```

#### Verification:
- Run: `python3 -m unittest backend/tests/test_llm_service.py`
- Expected: All tests pass (no network access required).

**✅ After completing this prompt, proceed to [PROMPT-003]**

---

## 🟢 Priority 3 (Medium) - Execute Last

### [PROMPT-003] Update npm scripts to prefer `python3`

**⏱️ Execute this prompt now, then proceed to FINAL VERIFICATION**

> **🚨 REQUIRED: Use `replace_string_in_file` or `create_file` to make changes. Do NOT just show code.**

**Task**: Reduce environment-specific failures by updating backend npm scripts to prefer `python3` inside the venv.  
**Files to Modify**: `package.json`

#### Instructions:

1. Open `package.json`
2. Update `dev:backend` and `test:backend` scripts to use `python3 -m ...` where applicable

#### Implementation Code:

```json
{
    "name": "personal-portfolio",
    "private": true,
    "version": "1.0.0",
    "description": "MyAsset Portfolio Project (Frontend + Backend)",
    "scripts": {
        "dev:frontend": "npm run dev --prefix frontend",
        "dev:backend": "cd backend && . .venv/bin/activate && python3 -m uvicorn main:app --reload --port 8000",
        "test:frontend": "npm run test --prefix frontend",
        "test:backend": "cd backend && . .venv/bin/activate && PYTHONPATH=.. python3 -m unittest discover tests"
    },
    "dependencies": {
        "react-markdown": "^10.1.0",
        "remark-gfm": "^4.0.1"
    }
}
```

#### Verification:
- Run: `npm run test:backend`
- Expected: Backend unit tests run successfully under the activated venv.

**🎉 ALL PROMPTS COMPLETED! Run final verification.**

Final verification:
- Run: `python3 -m unittest discover backend/tests`
- Expected: All tests pass.
