from typing import List, Optional, Protocol

class LLMBackend(Protocol):
    """
    LLM 엔진(로컬, 원격, 유료 등)을 위한 공통 인터페이스
    """
    def generate(
        self, 
        prompt: str, 
        max_tokens: int = 512, 
        temperature: float = 0.7, 
        stop: Optional[list] = None, 
        seed: Optional[int] = None,
        **kwargs
    ) -> str:
        ...

    def chat(
        self, 
        messages: List[dict], 
        max_tokens: int = 512, 
        temperature: float = 0.7, 
        stop: Optional[list] = None, 
        seed: Optional[int] = None,
        **kwargs
    ) -> str:
        ...

    def is_loaded(self) -> bool:
        ...

    def reset(self) -> None:
        ...
