from .llm import LLMService

# 하위 호환성을 위해 기존 위치에서 LLMService를 내보냄
# 이 파일은 이제 llm/ 패키지의 브릿지 역할을 함
__all__ = ["LLMService"]
