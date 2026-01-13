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
# NEWS_LLM_BASE_URL = os.getenv("NEWS_LLM_BASE_URL")
# NEWS_LLM_MODEL = os.getenv("NEWS_LLM_MODEL", "local")
# NEWS_LLM_API_KEY = os.getenv("NEWS_LLM_API_KEY")
NEWS_LLM_BASE_URL = None
NEWS_LLM_MODEL = "local"
NEWS_LLM_API_KEY = None

class LLMService:
    _instance = None
    _model = None
    _current_model_path = None
    _last_error = None

    def __init__(self):
        if LLMService._instance is not None:
            raise Exception("This class is a singleton!")
        else:
            self._last_error = None
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
        return self._current_model_path

    def get_last_error(self) -> Optional[str]:
        return self._last_error

    def generate(self, prompt: str, max_tokens: int = 512, temperature: float = 0.7, stop: list = None, echo: bool = False, seed: int = None) -> str:
        """
        텍스트 생성 (Inference) - Legacy Wrapper
        """
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

    def generate_chat(self, messages: List[dict], max_tokens: int = 512, temperature: float = 0.7, stop: list = None, seed: int = None) -> str:
        """
        Chat Completion API를 사용하여 대화 형식으로 텍스트를 생성한다.
        로드된 모델의 chat_template이 자동으로 적용된다.
        """
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

    # def is_remote_ready(self) -> bool:
    #     return bool(NEWS_LLM_BASE_URL)

    # def generate_remote(self, prompt: str, max_tokens: int = 512, temperature: float = 0.7) -> str:
    #     """
    #     llama.cpp OpenAI 호환 서버로 원격 텍스트 생성 요청.
    #     """
    #     if not NEWS_LLM_BASE_URL:
    #         logger.warning("NEWS_LLM_BASE_URL not configured.")
    #         return ""

    #     try:
    #         import httpx
    #     except ImportError:
    #         logger.error("httpx not installed.")
    #         return ""

    #     url = f"{NEWS_LLM_BASE_URL.rstrip('/')}/v1/chat/completions"
    #     headers = {"Content-Type": "application/json"}
    #     if NEWS_LLM_API_KEY:
    #         headers["Authorization"] = f"Bearer {NEWS_LLM_API_KEY}"

    #     payload = {
    #         "model": NEWS_LLM_MODEL,
    #         "messages": [{"role": "user", "content": prompt}],
    #         "temperature": temperature,
    #         "max_tokens": max_tokens,
    #     }

    #     try:
    #         with httpx.Client(timeout=60.0) as client:
    #             response = client.post(url, json=payload, headers=headers)
    #             response.raise_for_status()
    #             data = response.json()
    #     except Exception as e:
    #         logger.error(f"Remote LLM request failed: {e}")
    #         return ""

    #     try:
    #         return data["choices"][0]["message"]["content"].strip()
    #     except Exception:
    #         logger.error("Remote LLM response parsing failed.")
    #         return ""

    def is_loaded(self) -> bool:
        return self._model is not None

    def reset_context(self):
        """
        LLM의 KV 캐시를 초기화하여 이전 대화 컨텍스트를 리셋한다.
        특정 주제에 집착하는 문제를 해결하기 위해 주기적으로 호출.
        """
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
