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
        self._last_used_paid: bool = False  # 이번 호출이 유료였나
        self._last_route: Optional[str] = None  # "remote" | "paid" | "remote_failed_no_paid" | "paid_failed" | "no_backend" | "remote_failed_paid_disabled" | "paid_disabled" | None
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
        temperature: float = 0.6,
        top_p: float = 0.8,
        top_k: int = 20,
        stop: Optional[list] = None,
        seed: Optional[int] = None,
        **kwargs,
    ) -> str:
        messages = [{"role": "user", "content": prompt}]
        return self.generate_chat(
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            stop=stop,
            seed=seed,
            **kwargs
        )

    def generate_chat(
        self,
        messages: List[dict],
        max_tokens: int = 512,
        temperature: float = 0.6,
        top_p: float = 0.8,
        top_k: int = 20,
        stop: Optional[list] = None,
        seed: Optional[int] = None,
        allow_paid_fallback: bool = True,
        **kwargs,
    ) -> str:
        # 호출 시작 시 라우팅 상태 초기화
        self._last_used_paid = False
        self._last_route = None

        requested_model = kwargs.get("model")
        paid_kwargs = dict(kwargs)
        paid_kwargs.pop("model", None)  # model은 명시 인자로만 전달

        # 1) 원격 백엔드 우선
        if self.settings.is_remote_configured():
            out = self.backend.chat(
                messages,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
                stop=stop,
                seed=seed,
                **kwargs
            )
            if out:
                self._last_error = None
                self._last_route = "remote"
                return out

            remote_error = getattr(self.backend, "_last_error", None) or "Remote LLM failed"
            if not allow_paid_fallback:
                logger.warning("Remote LLM failed; paid fallback disabled: %s", remote_error)
                self._last_error = remote_error
                self._last_route = "remote_failed_paid_disabled"
                return ""
            logger.warning("Remote LLM failed, trying paid backend: %s", remote_error)

            # 2) 원격 실패 시 유료 백엔드 폴백 (가장 저렴한 모델 사용)
            if self.settings.is_paid_configured():
                # 명시 모델이 있으면 우선 사용하고, 없을 때만 저가 폴백 모델 사용
                fallback_model = requested_model or self.settings.ai_report_fallback_model
                out_paid = self.paid_backend.chat(
                    messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    model=fallback_model,
                    stop=stop,
                    seed=seed,
                    **paid_kwargs,
                )
                if out_paid:
                    self._last_error = None
                    self._last_used_paid = True
                    self._last_route = "paid"
                    return out_paid  # 순수 텍스트 반환 (💰는 전송 단계에서 붙임)

                paid_error = getattr(self.paid_backend, "_last_error", None) or "Paid LLM failed"
                self._last_error = f"{remote_error} | {paid_error}"
                self._last_route = "paid_failed"
                return ""

            self._last_error = remote_error
            self._last_route = "remote_failed_no_paid"
            return ""

        # 원격 미구성: 유료 백엔드만 사용
        if not allow_paid_fallback:
            self._last_error = "Paid fallback disabled"
            self._last_route = "paid_disabled"
            return ""

        if self.settings.is_paid_configured():
            paid_model = kwargs.get("model")
            out_paid = self.paid_backend.chat(
                messages,
                max_tokens=max_tokens,
                temperature=temperature,
                model=paid_model,
                stop=stop,
                seed=seed,
                **paid_kwargs,
            )
            if out_paid:
                self._last_error = None
                self._last_used_paid = True
                self._last_route = "paid"
                return out_paid
            self._last_error = getattr(self.paid_backend, "_last_error", None) or "Paid LLM failed"
            self._last_route = "paid_failed"
            return ""

        self._last_error = "No LLM backend configured (set LLM_BASE_URL or AI_REPORT_API_KEY)"
        self._last_route = "no_backend"
        return ""

    def generate_paid_chat(
        self,
        messages: List[dict],
        max_tokens: int = 1024,
        temperature: float = 0.5,
        top_p: float = 0.8,
        model: Optional[str] = None,
        stop: Optional[list] = None,
        seed: Optional[int] = None,
        **kwargs,
    ) -> str:
        # 호출 시작 시 라우팅 상태 초기화
        self._last_used_paid = False
        self._last_route = None

        out = self.paid_backend.chat(
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            model=model,
            stop=stop,
            seed=seed,
            **kwargs,
        )
        if out:
            self._last_error = None
            self._last_used_paid = True
            self._last_route = "paid"
            return out
        self._last_error = getattr(self.paid_backend, "_last_error", None) or "Paid LLM failed"
        self._last_route = "paid_failed"
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

    def last_used_paid(self) -> bool:
        """이번 호출이 유료 백엔드를 사용했는지 반환"""
        return bool(self._last_used_paid)

    def last_route(self) -> Optional[str]:
        """이번 호출의 라우팅 경로 반환."""
        return self._last_route
