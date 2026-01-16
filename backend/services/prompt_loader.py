"""
프롬프트 로더 유틸리티
외부 .txt 파일에서 프롬프트 템플릿을 불러온다.
"""
import os
import logging

logger = logging.getLogger(__name__)

PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "prompts")

# 캐시 (파일 수정 시간 기반)
_prompt_cache = {}
_prompt_mtime = {}


def load_prompt(prompt_name: str, **kwargs) -> str:
    """
    프롬프트 템플릿을 로드하고 변수를 치환한다.
    
    Args:
        prompt_name: 프롬프트 파일 이름 (확장자 제외, 예: "random_topic")
        **kwargs: 템플릿 변수 (예: category="지식/과학")
    
    Returns:
        변수가 치환된 프롬프트 문자열
    """
    filepath = os.path.join(PROMPTS_DIR, f"{prompt_name}.txt")
    
    if not os.path.exists(filepath):
        logger.warning(f"Prompt file not found: {filepath}")
        return ""

    # 캐시 + mtime 기반으로 변경 여부를 판단해 필요할 때만 재로드한다.
    mtime = os.path.getmtime(filepath)
    if filepath in _prompt_cache and _prompt_mtime.get(filepath) == mtime:
        template = _prompt_cache[filepath]
    else:
        with open(filepath, "r", encoding="utf-8") as f:
            template = f.read()
        _prompt_cache[filepath] = template
        _prompt_mtime[filepath] = mtime
        logger.info(f"Prompt loaded/reloaded: {prompt_name}")
    
    # 변수 치환
    try:
        # EXAONE 특수 토큰 [|system|] 등에서 발생하는 중괄호 문제를 피하기 위해 
        # format() 대신 필요한 변수만 명시적으로 replace 하거나, 
        # 안전한 string.Template 방식 또는 예외 처리를 강화합니다.
        result = template
        for key, value in kwargs.items():
            result = result.replace("{" + key + "}", str(value))
        return result
    except Exception as e:
        logger.warning(f"Error during template substitution in {prompt_name}: {e}")
        return template


def list_prompts() -> list:
    """사용 가능한 프롬프트 목록 반환"""
    if not os.path.exists(PROMPTS_DIR):
        return []
    return [f.replace(".txt", "") for f in os.listdir(PROMPTS_DIR) if f.endswith(".txt")]
