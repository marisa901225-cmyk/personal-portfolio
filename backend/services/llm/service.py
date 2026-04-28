import logging
import json
import os
import time
from datetime import datetime
from typing import List, Optional
from zoneinfo import ZoneInfo

from .config import Settings
from .backends.remote import RemoteLlamaBackend
from .backends.paid import OpenAIPaidBackend

logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")


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
        temperature: float = 1.0,
        top_p: float = 0.95,
        top_k: int = 64,
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
        temperature: float = 1.0,
        top_p: float = 0.95,
        top_k: int = 64,
        stop: Optional[list] = None,
        seed: Optional[int] = None,
        allow_paid_fallback: bool = True,
        **kwargs,
    ) -> str:
        # 호출 시작 시 라우팅 상태 초기화
        self._last_used_paid = False
        self._last_route = None
        self.backend.clear_last_token_metrics()

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

    def reset_context(self) -> bool:
        if not self.settings.is_remote_configured():
            self._last_error = "Remote LLM is not configured"
            return False

        ok = self.backend.reset_context()
        if ok:
            self._last_error = None
        else:
            self._last_error = self.backend.get_last_error() or "Remote LLM reset failed"
        return ok

    def consume_last_remote_token_metrics(self) -> Optional[dict]:
        return self.backend.consume_last_token_metrics()

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

    def telegram_paid_prefix(self) -> str:
        """텔레그램 메시지 앞에 붙일 유료 폴백 표식을 반환한다."""
        if not self.last_used_paid():
            return ""

        notice = self._fan_guard_paid_notice()
        if notice:
            return f"{notice}💰 "
        return "💰 "

    def _fan_guard_paid_notice(self) -> Optional[str]:
        cooldown = self._load_active_fan_guard_cooldown()
        if not cooldown:
            return None

        cooldown_id = f"{cooldown['started_epoch']}:{cooldown['until_epoch']}"
        notice_state_path = self._fan_guard_notice_state_path()
        notice_state = self._load_json_file(notice_state_path)
        if notice_state.get("last_notified_cooldown_id") == cooldown_id:
            return None

        self._write_json_file(
            notice_state_path,
            {
                "last_notified_cooldown_id": cooldown_id,
                "updated_at_epoch": int(time.time()),
            },
        )

        until_text = datetime.fromtimestamp(cooldown["until_epoch"], KST).strftime("%Y-%m-%d %H:%M KST")
        rpm = cooldown.get("last_trigger_rpm")
        rpm_text = f" (팬 {rpm} RPM 보호)" if rpm else ""
        return (
            "⚠️ <i>로컬 LLM은"
            f"{rpm_text} 쿨다운으로 {until_text}까지 잠시 쉬는 중이야. "
            "고장난 건 아니고, 이번 메시지는 유료 폴백으로 보냈어.</i>\n\n"
        )

    def _load_active_fan_guard_cooldown(self) -> Optional[dict]:
        state = self._load_json_file(self._fan_guard_state_path())
        now_epoch = int(time.time())

        try:
            cooldown_active = int(state.get("cooldown_active", 0)) == 1
            started_epoch = int(state.get("cooldown_started_epoch", 0) or 0)
            until_epoch = int(state.get("cooldown_until_epoch", 0) or 0)
        except (TypeError, ValueError):
            return None

        if not cooldown_active or until_epoch <= now_epoch:
            return None

        try:
            last_trigger_rpm = int(state.get("last_trigger_rpm", 0) or 0)
        except (TypeError, ValueError):
            last_trigger_rpm = 0

        return {
            "started_epoch": started_epoch,
            "until_epoch": until_epoch,
            "last_trigger_rpm": last_trigger_rpm,
        }

    def _fan_guard_state_path(self) -> str:
        return os.getenv(
            "LLM_FAN_GUARD_STATE_FILE",
            os.path.join(self.settings.backend_dir_abs, "data", "llm_fan_guard_state.json"),
        )

    def _fan_guard_notice_state_path(self) -> str:
        return os.getenv(
            "LLM_FAN_GUARD_NOTICE_STATE_FILE",
            os.path.join(self.settings.backend_dir_abs, "data", "llm_paid_fallback_notice_state.json"),
        )

    @staticmethod
    def _load_json_file(path: str) -> dict:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _write_json_file(path: str, payload: dict) -> None:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp_path = f"{path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
        except Exception as exc:
            logger.warning("Failed to persist fan guard notice state: %s", exc)
