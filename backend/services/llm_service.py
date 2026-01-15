import os
import logging
import random
import time
import json
from typing import List, Optional

# Monkeypatch jinja2 to enable loopcontrols (for 'continue' support in some models like EXAONE)
try:
    import jinja2
    original_init = jinja2.Environment.__init__
    def new_init(self, *args, **kwargs):
        extensions = list(kwargs.get('extensions', []))
        if 'jinja2.ext.loopcontrols' not in extensions:
            extensions.append('jinja2.ext.loopcontrols')
        kwargs['extensions'] = extensions
        original_init(self, *args, **kwargs)
    jinja2.Environment.__init__ = new_init
except ImportError:
    pass
except Exception as e:
    logging.getLogger(__name__).warning(f"Failed to monkeypatch jinja2: {e}")

logger = logging.getLogger(__name__)

# LLM 모델 경로 및 쓰레드 설정 (env에서 가져오거나 기본값)
CONFIG_PATH = "backend/data/llm_config.json"
DEFAULT_MODEL_PATH = os.getenv("LOCAL_LLM_MODEL_PATH", "backend/data/gemma-3-4b-it-Q3_K_M.gguf")
LLM_THREADS = int(os.getenv("LOCAL_LLM_THREADS", "4")) # 기본값 4 (저전력 PC에서 빠르게 작업을 끝내기 위함)
LOCAL_LLM_CHAT_FORMAT = os.getenv("LOCAL_LLM_CHAT_FORMAT")
LLM_BASE_URL = os.getenv("LLM_BASE_URL")
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "120"))
REMOTE_MODEL_PATH_FILE = os.getenv(
    "LLM_REMOTE_MODEL_PATH_FILE",
    os.path.join("backend", "data", "llm_model_path.txt"),
)
REMOTE_MODEL_DIR = os.getenv("LLM_REMOTE_MODEL_DIR", "/data")
REMOTE_DEFAULT_MODEL = os.getenv("LLM_REMOTE_DEFAULT_MODEL")

class LLMService:
    _instance = None
    _model = None
    _current_model_path = None
    _last_error = None
    _http_client = None
    _base_url = None

    def __init__(self):
        if LLMService._instance is not None:
            raise Exception("This class is a singleton!")
        else:
            self._last_error = None
            self._base_url = LLM_BASE_URL
            if self._is_remote_mode():
                self._current_model_path = (
                    self._load_remote_model_path()
                    or self._resolve_remote_default_model()
                    or DEFAULT_MODEL_PATH
                )
            else:
                self._current_model_path = self._load_config()
                self._load_model()
            LLMService._instance = self

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = LLMService()
        return cls._instance

    def _load_config(self) -> str:
        """설정 파일에서 활성화된 모델 경로를 로드한다."""
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r") as f:
                    config = json.load(f)
                    return config.get("active_model", DEFAULT_MODEL_PATH)
            except Exception as e:
                logger.error(f"Failed to load LLM config: {e}")
        return DEFAULT_MODEL_PATH

    def _save_config(self, model_path: str):
        """활성화된 모델 경로를 설정 파일에 저장한다."""
        try:
            with open(CONFIG_PATH, "w") as f:
                json.dump({"active_model": model_path}, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save LLM config: {e}")

    def _load_model(self):
        if self._is_remote_mode():
            return
        try:
            from llama_cpp import Llama
            model_path = self._current_model_path
            if os.path.exists(model_path):
                logger.info(f"Loading LLM model from {model_path} with {LLM_THREADS} threads...")
                load_kwargs = {
                    "model_path": model_path,
                    "n_ctx": 2048,
                    "n_threads": LLM_THREADS,
                    "verbose": False,
                }
                try:
                    if LOCAL_LLM_CHAT_FORMAT:
                        logger.info(f"Using LOCAL_LLM_CHAT_FORMAT={LOCAL_LLM_CHAT_FORMAT}")
                        self._model = Llama(**load_kwargs, chat_format=LOCAL_LLM_CHAT_FORMAT)
                    elif "exaone" in model_path.lower():
                        template_path = "backend/data/chat_template_exaone.jinja"
                        if os.path.exists(template_path):
                            logger.info(f"Detected EXAONE model. Loading chat template from {template_path}")
                            with open(template_path, "r") as f:
                                chat_template = f.read()
                            self._model = Llama(**load_kwargs, chat_template=chat_template)
                        else:
                            logger.warning(f"EXAONE model detected but template not found at {template_path}. Falling back.")
                            self._model = Llama(**load_kwargs)
                    else:
                        self._model = Llama(**load_kwargs)
                except Exception as e:
                    # Jinja2 템플릿 에러 (EXAONE 모델 등에서 발생 가능) 발생 시 chat_format을 수동 지정하여 우회
                    err_text = str(e)
                    if "Jinja" in err_text or "unknown tag" in err_text.lower():
                        fallback_formats = ["llama-3", "llama-2", "chatml"]
                        for fmt in fallback_formats:
                            try:
                                logger.warning(
                                    f"Jinja template error detected in metadata, retrying with chat_format='{fmt}': {e}"
                                )
                                self._model = Llama(**load_kwargs, chat_format=fmt)
                                break
                            except Exception as retry_err:
                                self._last_error = str(retry_err)
                        if self._model is None:
                            raise e
                    else:
                        raise e
                self._last_error = None
            else:
                logger.warning(f"LLM model not found at {model_path}, falling back to default.")
                self._last_error = f"model not found: {model_path}"
                if model_path != DEFAULT_MODEL_PATH:
                    self._current_model_path = DEFAULT_MODEL_PATH
                    self._load_model()
                else:
                    self._model = None
        except ImportError:
            logger.error("llama-cpp-python not installed.")
            self._last_error = "llama-cpp-python not installed"
            self._model = None
        except Exception as e:
            logger.error(f"Failed to load LLM: {e}")
            self._last_error = str(e)
            self._model = None

    def switch_model(self, model_path: str) -> bool:
        """실시간으로 모델을 교체한다."""
        if self._is_remote_mode():
            if not os.path.exists(model_path):
                logger.error(f"Cannot switch to non-existent model: {model_path}")
                self._last_error = f"model not found: {model_path}"
                return False
            remote_path = self._to_remote_model_path(model_path)
            if not self._write_remote_model_path(remote_path):
                return False
            self._current_model_path = model_path
            self._last_error = None
            return True
        if not os.path.exists(model_path):
            logger.error(f"Cannot switch to non-existent model: {model_path}")
            return False
        
        logger.info(f"Switching LLM model to {model_path}...")
        self._current_model_path = model_path
        self._model = None # 기존 모델 해제
        self._load_model()
        
        if self.is_loaded():
            self._save_config(model_path)
            return True
        return False

    def list_available_models(self) -> List[str]:
        """backend/data 디렉토리의 사용 가능한 GGUF 모델 목록을 반환한다."""
        models = []
        data_dir = "backend/data"
        if os.path.exists(data_dir):
            for file in os.listdir(data_dir):
                if file.endswith(".gguf"):
                    models.append(os.path.join(data_dir, file))
        return sorted(models)

    def get_current_model(self) -> str:
        if self._is_remote_mode():
            remote_path = self._read_remote_model_path()
            if remote_path:
                self._current_model_path = self._to_local_model_path(remote_path)
        return self._current_model_path

    def get_last_error(self) -> Optional[str]:
        return self._last_error

    def _is_remote_mode(self) -> bool:
        """원격 llama-server 모드인지 확인."""
        return bool(self._base_url)

    def _to_remote_model_path(self, local_path: str) -> str:
        if local_path.startswith(REMOTE_MODEL_DIR.rstrip("/") + "/"):
            return local_path
        filename = os.path.basename(local_path)
        return f"{REMOTE_MODEL_DIR.rstrip('/')}/{filename}"

    def _to_local_model_path(self, remote_path: str) -> str:
        filename = os.path.basename(remote_path)
        return os.path.join("backend", "data", filename)

    def _read_remote_model_path(self) -> Optional[str]:
        if not os.path.exists(REMOTE_MODEL_PATH_FILE):
            return None
        try:
            with open(REMOTE_MODEL_PATH_FILE, "r") as f:
                raw = f.read().strip()
        except Exception as e:
            logger.error(f"Failed to read remote model path file: {e}")
            return None
        if not raw:
            return None
        if raw.startswith("backend/data/"):
            return self._to_remote_model_path(raw)
        if raw.startswith("/app/backend/data/"):
            return self._to_remote_model_path(raw)
        if raw.startswith("/"):
            return raw
        return f"{REMOTE_MODEL_DIR.rstrip('/')}/{raw}"

    def _load_remote_model_path(self) -> Optional[str]:
        remote_path = self._read_remote_model_path()
        if not remote_path:
            return None
        return self._to_local_model_path(remote_path)

    def _resolve_remote_default_model(self) -> Optional[str]:
        if not REMOTE_DEFAULT_MODEL:
            return None
        if REMOTE_DEFAULT_MODEL.startswith("/"):
            return self._to_local_model_path(REMOTE_DEFAULT_MODEL)
        return os.path.join("backend", "data", REMOTE_DEFAULT_MODEL)

    def _write_remote_model_path(self, remote_path: str) -> bool:
        try:
            os.makedirs(os.path.dirname(REMOTE_MODEL_PATH_FILE), exist_ok=True)
            with open(REMOTE_MODEL_PATH_FILE, "w") as f:
                f.write(remote_path)
            return True
        except Exception as e:
            logger.error(f"Failed to write remote model path file: {e}")
            self._last_error = str(e)
            return False

    def _get_http_client(self):
        if self._http_client is None:
            import httpx
            self._http_client = httpx.Client(timeout=LLM_TIMEOUT)
        return self._http_client

    def _generate_chat_remote(self, messages: List[dict], model: Optional[str] = None, max_tokens: int = 512, temperature: float = 0.7, stop: Optional[list] = None, enable_thinking: bool = False) -> str:
        """llama-server의 OpenAI 호환 API 호출."""
        if not self._base_url:
            logger.warning("LLM_BASE_URL not configured.")
            return ""

        try:
            client = self._get_http_client()
            url = f"{self._base_url.rstrip('/')}/v1/chat/completions"
            headers = {"Content-Type": "application/json"}
            if LLM_API_KEY:
                headers["Authorization"] = f"Bearer {LLM_API_KEY}"
            payload = {
                "model": model or "gpt-3.5-turbo", # Default fallback if not provided
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            if stop:
                payload["stop"] = stop
            if enable_thinking:
                payload["enable_thinking"] = True
            response = client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            logger.error(f"Remote LLM request failed: {e}")
            return ""

        try:
            return data["choices"][0]["message"]["content"].strip()
        except Exception:
            logger.error("Remote LLM response parsing failed.")
            return ""

    def _generate_prompt_remote(self, prompt: str, model: Optional[str] = None, max_tokens: int = 512, temperature: float = 0.7, stop: Optional[list] = None) -> str:
        messages = [{"role": "user", "content": prompt}]
        return self._generate_chat_remote(messages, model=model, max_tokens=max_tokens, temperature=temperature, stop=stop)

    def generate(self, prompt: str, max_tokens: int = 512, temperature: float = 0.7, stop: list = None, echo: bool = False, seed: int = None) -> str:
        """
        텍스트 생성 (Inference) - Legacy Wrapper
        """
        if self._is_remote_mode():
            return self._generate_prompt_remote(prompt, max_tokens, temperature, stop=stop)
        if self._model is None:
            logger.warning("LLM model is not loaded.")
            return ""

        # 만약 프롬프트가 채팅 형식(<start_of_turn> 등)을 포함하고 있다면,
        # 가능한 경우 generate_chat으로 자동 변환 시도 가능하나,
        # 여기서는 기존 호환성을 위해 raw completion으로 유지한다.
        try:
            if seed is None:
                seed = int(time.time()) % 10000
            
            response = self._model(
                prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                stop=stop or [],
                echo=echo,
                seed=seed
            )
            return response["choices"][0]["text"].strip()
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            return ""

    def generate_chat(self, messages: List[dict], model: Optional[str] = None, max_tokens: int = 512, temperature: float = 0.7, stop: list = None, seed: int = None, enable_thinking: bool = False) -> str:
        """
        Chat Completion API를 사용하여 대화 형식으로 텍스트를 생성한다.
        로드된 모델의 chat_template이 자동으로 적용된다.
        
        Args:
            model: 원격 모드 시 사용할 모델 이름
            enable_thinking: True이면 <think> 모드 활성화
        """
        if self._is_remote_mode():
            return self._generate_chat_remote(messages, model=model, max_tokens=max_tokens, temperature=temperature, stop=stop, enable_thinking=enable_thinking)
        if self._model is None:
            logger.warning("LLM model is not loaded.")
            return ""

        try:
            if seed is None:
                seed = int(time.time()) % 10000

            response = self._model.create_chat_completion(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stop=stop or [],
                seed=seed
            )
            return response["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.error(f"LLM chat generation failed: {e}")
            # Fallback to generate (using the last message) if chat completion fails
            if messages:
                last_content = messages[-1]["content"]
                return self.generate(last_content, max_tokens, temperature, stop, seed=seed)
            return ""

    def generate_paid_chat(self, messages: List[dict], model: Optional[str] = None, max_tokens: int = 1024, temperature: float = 0.5) -> str:
        """
        AI_REPORT_BASE_URL/API_KEY 등을 사용하여 외부 유료 LLM을 호출한다.
        """
        base_url = os.getenv("AI_REPORT_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        api_key = os.getenv("AI_REPORT_API_KEY")
        selected_model = model or os.getenv("AI_REPORT_MODEL", "gpt-5.2")
        
        if not api_key:
            logger.warning("AI_REPORT_API_KEY not set. Cannot use paid LLM.")
            return ""

        def _safe_body(text: str) -> str:
            body = (text or "").strip()
            if len(body) > 4000:
                return body[:4000] + "…(truncated)"
            return body

        def _parse_openai_chat_completions(data: dict) -> str:
            try:
                return data["choices"][0]["message"]["content"].strip()
            except Exception:
                return ""

        def _parse_openai_responses(data: dict) -> str:
            # Prefer the server-provided aggregate when present.
            output_text = data.get("output_text")
            if isinstance(output_text, str) and output_text.strip():
                return output_text.strip()

            # Otherwise, best-effort extraction from the structured output.
            chunks: list[str] = []
            output = data.get("output") or []
            if isinstance(output, list):
                for item in output:
                    if not isinstance(item, dict):
                        continue
                    content = item.get("content") or []
                    if not isinstance(content, list):
                        continue
                    for part in content:
                        if not isinstance(part, dict):
                            continue
                        if part.get("type") in ("output_text", "text") and isinstance(part.get("text"), str):
                            chunks.append(part["text"])
            return "".join(chunks).strip()

        def _to_responses_input(msgs: List[dict]) -> list[dict]:
            converted: list[dict] = []
            for m in msgs:
                role = m.get("role")
                content = m.get("content", "")
                if not isinstance(content, str):
                    content = str(content)
                converted.append(
                    {
                        "role": role,
                        "content": [{"type": "input_text", "text": content}],
                    }
                )
            return converted

        try:
            import httpx
            with httpx.Client(timeout=LLM_TIMEOUT) as client:
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                }

                # 1) Try Chat Completions (legacy endpoint).
                chat_url = f"{base_url}/chat/completions"
                # Some newer model families require `max_completion_tokens` instead of `max_tokens`.
                is_gpt5_family = str(selected_model).startswith("gpt-5")
                chat_payload = {
                    "model": selected_model,
                    "messages": messages,
                }
                if not is_gpt5_family:
                    chat_payload["temperature"] = temperature
                if is_gpt5_family:
                    chat_payload["max_completion_tokens"] = max_tokens
                else:
                    chat_payload["max_tokens"] = max_tokens
                chat_res = client.post(chat_url, json=chat_payload, headers=headers)
                if chat_res.status_code < 400:
                    chat_text = _parse_openai_chat_completions(chat_res.json()) or ""
                    if chat_text:
                        return chat_text
                    # Some model families may return an empty `content` while consuming tokens (e.g. reasoning-only output).
                    # In that case, fall back to the Responses API.

                # If Chat Completions fails (common with some newer model families),
                # retry with Responses API.
                responses_url = f"{base_url}/responses"
                responses_payload = {
                    "model": selected_model,
                    "input": _to_responses_input(messages),
                    "max_output_tokens": max_tokens,
                }
                if not is_gpt5_family:
                    responses_payload["temperature"] = temperature
                else:
                    responses_payload["reasoning"] = {"effort": "low"}
                resp_res = client.post(responses_url, json=responses_payload, headers=headers)
                if resp_res.status_code < 400:
                    return _parse_openai_responses(resp_res.json()) or ""

                logger.error(
                    "Paid LLM request failed: chat/completions=%s, responses=%s, model=%s. chat_body=%s responses_body=%s",
                    chat_res.status_code,
                    resp_res.status_code,
                    selected_model,
                    _safe_body(chat_res.text),
                    _safe_body(resp_res.text),
                )
                return ""
        except Exception as e:
            logger.error(f"Paid LLM request failed: {e}")
            return ""

    def is_loaded(self) -> bool:
        if self._is_remote_mode():
            return True
        return self._model is not None

    def reset_context(self):
        """
        LLM의 KV 캐시를 초기화하여 이전 대화 컨텍스트를 리셋한다.
        특정 주제에 집착하는 문제를 해결하기 위해 주기적으로 호출.
        """
        if self._is_remote_mode():
            logger.info("Remote LLM mode does not support local context reset.")
            return
        if self._model is None:
            logger.warning("LLM model is not loaded; nothing to reset.")
            return

        try:
            reset_fn = getattr(self._model, "reset", None)
            if callable(reset_fn):
                reset_fn()
                logger.info("LLM context (KV cache) has been reset.")
                return
            logger.warning("LLM reset() not available; reloading model to clear context.")
        except Exception as e:
            logger.warning(f"Failed to reset LLM context via reset(): {e}")

        # Fallback: reload model to clear any cached state.
        self._model = None
        self._load_model()
