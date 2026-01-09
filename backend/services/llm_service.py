import os
import logging
import random
import time

logger = logging.getLogger(__name__)

# LLM 모델 경로 및 쓰레드 설정 (env에서 가져오거나 기본값)
LLM_MODEL_PATH = os.getenv("LOCAL_LLM_MODEL_PATH", "backend/data/gemma-3-4b-it-q4_k_m.gguf")
LLM_THREADS = int(os.getenv("LOCAL_LLM_THREADS", "4")) # 기본값 4 (저전력 PC에서 빠르게 작업을 끝내기 위함)
NEWS_LLM_BASE_URL = os.getenv("NEWS_LLM_BASE_URL")
NEWS_LLM_MODEL = os.getenv("NEWS_LLM_MODEL", "local")
NEWS_LLM_API_KEY = os.getenv("NEWS_LLM_API_KEY")

class LLMService:
    _instance = None
    _model = None

    def __init__(self):
        if LLMService._instance is not None:
            raise Exception("This class is a singleton!")
        else:
            self._load_model()
            LLMService._instance = self

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = LLMService()
        return cls._instance

    def _load_model(self):
        try:
            from llama_cpp import Llama
            if os.path.exists(LLM_MODEL_PATH):
                logger.info(f"Loading LLM model from {LLM_MODEL_PATH} with {LLM_THREADS} threads...")
                self._model = Llama(model_path=LLM_MODEL_PATH, n_ctx=2048, n_threads=LLM_THREADS, verbose=False)
            else:
                logger.warning(f"LLM model not found at {LLM_MODEL_PATH}")
                self._model = None
        except ImportError:
            logger.error("llama-cpp-python not installed.")
            self._model = None
        except Exception as e:
            logger.error(f"Failed to load LLM: {e}")
            self._model = None

    def generate(self, prompt: str, max_tokens: int = 512, temperature: float = 0.7, stop: list = None, echo: bool = False, seed: int = None) -> str:
        """
        텍스트 생성 (Inference)
        """
        if self._model is None:
            logger.warning("LLM model is not loaded.")
            return ""

        try:
            # 시드 설정 (없으면 시간 기반)
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

    def is_remote_ready(self) -> bool:
        return bool(NEWS_LLM_BASE_URL)

    def generate_remote(self, prompt: str, max_tokens: int = 512, temperature: float = 0.7) -> str:
        """
        llama.cpp OpenAI 호환 서버로 원격 텍스트 생성 요청.
        """
        if not NEWS_LLM_BASE_URL:
            logger.warning("NEWS_LLM_BASE_URL not configured.")
            return ""

        try:
            import httpx
        except ImportError:
            logger.error("httpx not installed.")
            return ""

        url = f"{NEWS_LLM_BASE_URL.rstrip('/')}/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
        if NEWS_LLM_API_KEY:
            headers["Authorization"] = f"Bearer {NEWS_LLM_API_KEY}"

        payload = {
            "model": NEWS_LLM_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        try:
            with httpx.Client(timeout=60.0) as client:
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

    def is_loaded(self) -> bool:
        return self._model is not None
